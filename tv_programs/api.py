"""django-ninja router for the tv SPA (mounted at /api/tv/).

GET ops are public (auth=None) — the template pages they replace
were public; the like/dislike reaction mutation keeps the default
django_auth (session + CSRF) — a deliberate tightening vs. the old
anonymous-write form, matching the migration README's "mutations
keep django_auth" rule. The queryset logic mirrors the retired
program_list view in tv_programs/views.py exactly, including the
not_content_rating default of 'R' and the 7-day default window.
"""
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional
from uuid import UUID

from django.db.models import F, Q
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema

from industry_analyser.api import ApiHttpError

from .dedup import ensure_show
from .models import Channel, Program, Show, ShowPreference
from .views import _fetch_spoki_page, _preference_qs

router = Router()


# --- Schemas ---


class ShowRef(Schema):
    """The canonical Show slice a program card needs."""
    id: UUID
    title_lv: str
    title_eng: Optional[str]
    imdb_rating: Optional[Decimal]
    imdb_url: Optional[str]
    pg_rating: Optional[str]
    image_url: Optional[str]
    title_match_ratio: float


class ProgramOut(Schema):
    id: UUID
    title_lv: str
    title_eng: Optional[str]
    description_lv: Optional[str]
    channel_name: str
    start_time: str
    image_url: Optional[str]
    url: Optional[str]
    pg_rating: Optional[str]
    # Program.imdb_rating is a CharField (scraped string); the card's
    # "Rating:" falls back to it when show.imdb_rating is falsy.
    imdb_rating: Optional[str]
    title_match_ratio: float
    show: Optional[ShowRef]
    user_reaction: Optional[str]

    @staticmethod
    def resolve_channel_name(obj):
        return obj.channel.name

    @staticmethod
    def resolve_start_time(obj):
        # Django's {{ program.start_time }} rendered DATETIME_FORMAT
        # ("N j, Y, P"); the SPA formats the ISO value client-side.
        return obj.start_time.isoformat()

    @staticmethod
    def resolve_user_reaction(obj):
        return getattr(obj, 'user_reaction', None)


class ProgramFiltersOut(Schema):
    """Effective filter state — echoes the template's context
    `filters` dict so the SPA can render the applied window."""
    content_rating: Optional[str]
    not_content_rating: Optional[str]
    rating_value: Optional[float]
    ratio: Optional[float]
    start_date: date
    end_date: date
    channel_name: Optional[str]
    exclude_channel_name: Optional[str]
    show_disliked: bool


class ProgramsOut(Schema):
    """The whole program_list page payload — filtered programs plus
    the channel option list (the template's `channels` context)."""
    programs: List[ProgramOut]
    channels: List[str]
    filters: ProgramFiltersOut


class SpokiPageOut(Schema):
    title: str
    content: str


class ReactionOut(Schema):
    success: bool
    show_id: UUID
    # The reaction now in effect — null when the toggle removed it.
    reaction: Optional[str]
    message: str


# --- Ops ---


@router.get('/programs/', auth=None, response=ProgramsOut)
def list_programs(
    request,
    content_rating: Optional[str] = Query(None, max_length=50),
    not_content_rating: Optional[str] = Query(None, max_length=50),
    rating_value: Optional[float] = Query(None),
    ratio: Optional[float] = Query(None),
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    channel: Optional[str] = Query(None, max_length=255),
    exclude_channel: Optional[str] = Query(None, max_length=255),
    show_disliked: bool = False,
):
    """Program feed — mirrors the retired program_list view.

    `not_content_rating` defaults to 'R' when the param is absent;
    an explicit empty value (?not_content_rating=) disables the
    exclusion, like clearing the template input did. `ratio` was a
    declared-but-dead input in the template form — it now filters on
    the displayed match ratio (show's when truthy, falling back to
    the program's like the card's |default-style fallback).
    """
    # Default 'not_content_rating' to 'R' if not specified (verbatim
    # from the view — an explicit empty string disables it).
    if not_content_rating is None:
        not_content_rating = 'R'

    # Default dates to a 7-day window if not provided.
    if end_date is None:
        end_date = date.today()
    if start_date is None:
        start_date = end_date - timedelta(days=7)

    query = Q()

    if content_rating:
        query &= Q(show__pg_rating=content_rating)
    if not_content_rating:
        query &= (
            Q(show__isnull=True)
            | ~Q(show__pg_rating=not_content_rating)
        )
    if rating_value is not None:
        query &= Q(show__imdb_rating__gte=rating_value)
    if ratio is not None:
        # Match the card's |default-style fallback: the show's ratio
        # wins when truthy, otherwise the program's own ratio is the
        # displayed value — so a show ratio of 0 hands the filter to
        # the program's ratio, not to nothing.
        query &= (
            Q(
                show__title_match_ratio__gt=0,
                show__title_match_ratio__gte=ratio,
            )
            | Q(
                Q(show__isnull=True)
                | Q(show__title_match_ratio=0),
                title_match_ratio__gte=ratio,
            )
        )

    query &= Q(start_time__date__gte=start_date)
    query &= Q(start_time__date__lte=end_date)
    if channel:
        query &= Q(channel__name=channel)
    if exclude_channel:
        query &= ~Q(channel__name=exclude_channel)

    programs = Program.objects.select_related('show', 'channel').filter(
        query
    ).order_by('channel__name')

    # Anonymous (user NULL) rows sort first so a user's own row
    # overwrites the shared bucket on a per-show conflict — unordered,
    # which row wins the dict merge is DB-row-order dependent.
    preferences = list(
        _preference_qs(request)
        .select_related('show')
        .order_by(F('user').asc(nulls_first=True))
    )
    reactions = {p.show_id: p.reaction for p in preferences}

    # Disliked shows are hidden unless ?show_disliked=1 — judged on
    # the effective (post-merge) reaction, so a user's own row
    # outranks the anon bucket here too. A non-movie dislike also
    # hides the rest of the series: the key is series_title when the
    # source title carried episode markers, else the show's own
    # title_lv — daily slots without markers get a fresh Show per
    # airing (the dedup key covers description), so title_lv is the
    # only link between episodes. Movie dislikes hide just the Show.
    if not show_disliked:
        disliked_ids = {
            show_id
            for show_id, reaction in reactions.items()
            if reaction == ShowPreference.Reaction.DISLIKE
        }
        disliked_series_keys = {
            p.show.series_title or p.show.title_lv
            for p in preferences
            if reactions.get(p.show_id)
            == ShowPreference.Reaction.DISLIKE
            and p.show.content_type != Program.ContentType.MOVIE
        }
        if disliked_ids:
            programs = programs.exclude(show_id__in=disliked_ids)
        if disliked_series_keys:
            programs = programs.exclude(
                Q(show__series_title__in=disliked_series_keys)
                | Q(show__title_lv__in=disliked_series_keys)
            )

    programs = list(programs)
    for program in programs:
        program.user_reaction = reactions.get(program.show_id)

    return ProgramsOut(
        programs=programs,
        channels=[
            c.name for c in Channel.objects.order_by('name')
        ],
        filters=ProgramFiltersOut(
            content_rating=content_rating,
            not_content_rating=not_content_rating,
            rating_value=rating_value,
            ratio=ratio,
            start_date=start_date,
            end_date=end_date,
            channel_name=channel,
            exclude_channel_name=exclude_channel,
            show_disliked=show_disliked,
        ),
    )


@router.get('/spoki-page/', auth=None, response=SpokiPageOut)
def spoki_page(request):
    """Live-fetches the hardcoded spoki.lv article and returns
    {title, content} — the SPA renders content as HTML (same trust
    posture as the template's |safe render)."""
    title, content = _fetch_spoki_page()
    return SpokiPageOut(title=title, content=content)


def _toggle_reaction(user, show, reaction):
    """Upsert/delete the user's ShowPreference row — posting the
    same reaction again removes it. Returns the reaction now in
    effect (None when toggled off)."""
    pref = ShowPreference.objects.filter(
        show=show, user=user
    ).first()
    if pref is not None and pref.reaction == reaction:
        pref.delete()
        return None
    if pref is not None:
        pref.reaction = reaction
        pref.save(update_fields=['reaction'])
    else:
        ShowPreference.objects.create(
            show=show, user=user, reaction=reaction
        )
    return reaction


def _reaction_response(show, reaction, new_reaction):
    return ReactionOut(
        success=True,
        show_id=show.pk,
        reaction=new_reaction,
        message=(
            f'{reaction} removed'
            if new_reaction is None
            else f'reaction set to {reaction}'
        ),
    )


def _check_reaction(reaction):
    if reaction not in ShowPreference.Reaction.values:
        raise ApiHttpError(
            400, 'unknown reaction', code='unknown_reaction'
        )


@router.post('/shows/{show_id}/react/{reaction}/', response=ReactionOut)
def react_to_show(request, show_id: UUID, reaction: str):
    """Toggle a like/dislike on a Show — posting the same reaction
    again removes it. Session-auth (was: anonymous form POST)."""
    show = get_object_or_404(Show, pk=show_id)
    _check_reaction(reaction)
    new_reaction = _toggle_reaction(request.user, show, reaction)
    return _reaction_response(show, reaction, new_reaction)


@router.post(
    '/programs/{program_id}/react/{reaction}/', response=ReactionOut
)
def react_to_program(request, program_id: UUID, reaction: str):
    """Toggle a like/dislike from a program card — unlinked airings
    lazily resolve their canonical Show via ensure_show() (the same
    dedup path backfill_program_shows uses), so every card is
    reactable. Session-auth."""
    program = get_object_or_404(Program, pk=program_id)
    _check_reaction(reaction)
    show = ensure_show(program)
    new_reaction = _toggle_reaction(request.user, show, reaction)
    return _reaction_response(show, reaction, new_reaction)

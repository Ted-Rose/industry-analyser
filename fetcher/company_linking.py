"""Company identity resolution shared by the vacancy scraper and
the ``link_vacancies_to_companies`` backfill command.

Implements docs/company_linking_plan.md §4: ``employerId`` is the
stable join key (survives renames), ``regCode`` is a strong but
self-reported signal — collisions and changes are flagged with
``needs_review`` instead of auto-merging.
"""
import logging
import re

from bs4 import BeautifulSoup
from django.db import transaction
from django.utils import timezone

from .models import (
    Company,
    CompanyAlias,
    CompanyIdentity,
    CompanyPreference,
)

logger = logging.getLogger('fetcher')

# All cv.lv portals (api/nextjs) share one employerId namespace.
SOURCE_CVLV = 'cv.lv'

_WS_RE = re.compile(r'\s+')


def normalize_reg_code(value):
    """strip + drop all whitespace + upper; empty -> None."""
    code = _WS_RE.sub('', (value or '').strip()).upper()
    return code or None


def clip_field(model, value, field_name):
    """Coerce ``value`` to stripped str bounded by the model
    field's max_length; falsy -> None.

    cv.lv payloads occasionally exceed our varchar bounds — an
    unclipped assignment raises StringDataRightTruncation on save
    and rolls back the whole page's writes.
    """
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    max_len = model._meta.get_field(field_name).max_length
    if max_len and len(value) > max_len:
        logger.warning(
            f"{model.__name__}.{field_name} truncated from "
            f"{len(value)} to {max_len} chars"
        )
        value = value[:max_len]
    return value


def extract_vacancy_detail(next_data, vacancy_id):
    """Return ``props.pageProps.vacancy[str(vacancy_id)]`` from a
    parsed ``__NEXT_DATA__`` blob, or None."""
    if not next_data:
        return None
    vacancies = (
        next_data.get('props', {})
        .get('pageProps', {})
        .get('vacancy') or {}
    )
    return vacancies.get(str(vacancy_id))


def employer_detail_slice(detail):
    """Pull the company-relevant slices out of a vacancy detail
    dict (the ``pageProps.vacancy[<id>]`` object)."""
    if not detail:
        return None
    employer = detail.get('employer') or {}
    employer_id = detail.get('employerId') or employer.get(
        'employerId'
    )
    try:
        employer_id = int(employer_id)
    except (TypeError, ValueError):
        employer_id = None
    return {
        'employer_id': employer_id,
        'employer_name': detail.get('employerName'),
        'employer': employer,
        'contacts': detail.get('contacts') or {},
        'applying_url': (
            detail.get('settings') or {}
        ).get('applyingUrl'),
        'address': (
            detail.get('highlights') or {}
        ).get('address'),
    }


def strip_html(html):
    return (
        BeautifulSoup(html or '', 'html.parser')
        .get_text(' ')
        .strip()
    )


def observe_alias(company, kind, value, now=None):
    """get_or_create a (company, kind, value) alias row and bump
    ``last_seen`` on repeats."""
    value = clip_field(CompanyAlias, value, 'value') or ''
    if not value:
        return
    now = now or timezone.now()
    alias, created = CompanyAlias.objects.get_or_create(
        company=company, kind=kind, value=value,
        defaults={'first_seen': now, 'last_seen': now},
    )
    if not created:
        alias.last_seen = now
        alias.save(update_fields=['last_seen'])


def resolve_company(employer_id, employer_name=None,
                    source=SOURCE_CVLV, now=None):
    """Return the canonical Company for a portal employer id.

    First sight creates a fresh Company + identity; later sights
    bump ``last_seen`` and apply rename bookkeeping (new 'name'
    alias + updated display name — routine, no review flag).
    """
    now = now or timezone.now()
    name = clip_field(Company, employer_name, 'name') or ''
    identity = (
        CompanyIdentity.objects
        .filter(source=source, employer_id=employer_id)
        .select_related('company')
        .first()
    )
    if identity is None:
        company = Company.objects.create(
            name=name,
            first_seen=now,
            last_seen=now,
        )
        CompanyIdentity.objects.create(
            company=company, source=source,
            employer_id=employer_id,
            first_seen=now, last_seen=now,
        )
    else:
        company = identity.company
        if company.merged_into_id is not None:
            company = company.canonical()
        identity.last_seen = now
        identity.save(update_fields=['last_seen'])
    if name:
        observe_alias(company, CompanyAlias.KIND_NAME, name, now)
    update_fields = ['last_seen']
    company.last_seen = now
    if name and company.name != name:
        company.name = name
        update_fields.append('name')
    company.save(update_fields=update_fields)
    return company


def apply_employer_detail(company, detail_slice, now=None):
    """Upsert rich employer fields onto ``company`` from a
    ``employer_detail_slice()`` dict and apply the §4.1 conflict
    rules (reg-code collision / change -> needs_review)."""
    now = now or timezone.now()
    employer = detail_slice.get('employer') or {}
    if not employer:
        logger.warning(
            f"Vacancy detail for employer_id "
            f"{detail_slice.get('employer_id')} carries no "
            f"'employer' object — company {company.pk} "
            f"({company.name}) keeps empty about/contacts"
        )

    name = (
        clip_field(Company, detail_slice.get('employer_name'),
                   'name') or ''
    )
    if name:
        observe_alias(company, CompanyAlias.KIND_NAME, name, now)
        if company.name != name:
            company.name = name

    reg_code = clip_field(
        Company,
        normalize_reg_code(employer.get('regCode')),
        'reg_code',
    )
    if reg_code:
        observe_alias(
            company, CompanyAlias.KIND_REG_CODE, reg_code, now
        )
        collides = (
            Company.objects
            .filter(reg_code=reg_code)
            .exclude(pk=company.pk)
            .exists()
        )
        if collides:
            # Same regCode under a different employerId — strong
            # same-entity evidence or a typo; never auto-merge.
            # The observed code stays in the alias history.
            if not company.needs_review:
                company.needs_review = True
                logger.warning(
                    f"regCode {reg_code} observed on company "
                    f"{company.pk} ({company.name}) is already "
                    f"held by another company — flagged for review"
                )
        elif company.reg_code != reg_code:
            if company.reg_code:
                # regCode changed under the same employerId —
                # possible acquisition; keep the old code in the
                # alias history and flag for review.
                observe_alias(
                    company, CompanyAlias.KIND_REG_CODE,
                    company.reg_code, now,
                )
                company.needs_review = True
                logger.warning(
                    f"Company {company.pk} ({company.name}) "
                    f"regCode {company.reg_code} -> {reg_code} "
                    f"— flagged for review"
                )
            company.reg_code = reg_code

    contacts = detail_slice.get('contacts') or {}
    contact_name = clip_field(
        Company,
        ' '.join(
            part for part in (
                (contacts.get('firstName') or '').strip(),
                (contacts.get('lastName') or '').strip(),
            ) if part
        ),
        'contact_name',
    )

    company.about = strip_html(employer.get('about')) or None
    company.webpage_url = clip_field(
        Company, employer.get('webpageUrl'), 'webpage_url'
    )
    company.video_url = clip_field(
        Company, employer.get('videoUrl'), 'video_url'
    )
    company.logo_file_id = clip_field(
        Company, employer.get('logoFileId'), 'logo_file_id'
    )
    company.cover_file_id = clip_field(
        Company, employer.get('coverFileId'), 'cover_file_id'
    )
    company.gallery = employer.get('gallery') or []
    company.contact_name = contact_name
    company.contact_email = clip_field(
        Company, contacts.get('email'), 'contact_email'
    )
    company.contact_phone = clip_field(
        Company, contacts.get('phone'), 'contact_phone'
    )
    company.applying_url = clip_field(
        Company, detail_slice.get('applying_url'), 'applying_url'
    )
    company.address = clip_field(
        Company, detail_slice.get('address'), 'address'
    )
    company.raw_employer = employer or None
    company.detail_fetched_at = now
    company.last_seen = now
    company.save()
    return company


def merge_companies(target, sources):
    """Repoint identities, vacancies, aliases and preferences
    from ``sources`` onto ``target``, then soft-redirect the
    losers via ``merged_into``. Clears ``needs_review`` on both
    sides."""
    for source in sources:
        if source.pk == target.pk:
            continue
        # Atomic per source — a mid-merge failure must not leave a
        # half-repointed company (identities moved, merged_into unset).
        with transaction.atomic():
            CompanyIdentity.objects.filter(
                company=source
            ).update(company=target)
            source.vacancies.update(company=target)
            for alias in source.aliases.all():
                existing = target.aliases.filter(
                    kind=alias.kind, value=alias.value
                ).first()
                if existing is None:
                    alias.company = target
                    alias.save(update_fields=['company'])
                    continue
                if alias.first_seen < existing.first_seen:
                    existing.first_seen = alias.first_seen
                if alias.last_seen > existing.last_seen:
                    existing.last_seen = alias.last_seen
                existing.save()
                alias.delete()
            # Per-user like/dislike rows follow the survivor. A
            # user who marked both keeps the target's pref — the
            # (user, company) unique_together forbids a duplicate.
            source_prefs = CompanyPreference.objects.filter(
                company=source
            )
            source_prefs.filter(
                user__in=target.preferences.values('user')
            ).delete()
            source_prefs.update(company=target)
            source.merged_into = target
            source.needs_review = False
            source.save(
                update_fields=['merged_into', 'needs_review']
            )
    if target.needs_review:
        target.needs_review = False
        target.save(update_fields=['needs_review'])

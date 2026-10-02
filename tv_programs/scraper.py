import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone

from ai_providers import errors as ai_errors
from ai_providers.client import get_job_client
from core_scraper.base import BaseScraper
from .ai_jobs import TITLE_TRANSLATION
from .classification import EXCLUDED_LOCAL_SHOWS, classify
from .dedup import annotate_result, get_or_create_show, normalize_title
from .enrichment import OMDbClient, enrich_show
from .models import Program, Channel, Show

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger("tv_programs")

_UNSET = object()


class TVProgramScraper(BaseScraper):
    """
    Scraper for TV programs from tet.lv: grid parse + Show dedup +
    OMDb/Cinemeta enrichment for new shows (see
    docs/tv_show_normalization_plan.md).
    """

    # Class-level defaults so instances built without __init__ are safe.
    runner = None
    dry_run = False

    def __init__(self, config=None, runner=None, dry_run=False,
                 enrich=True):
        self.validate_result = True
        self.enrich_search_results = True
        self.channels = {
            "filmzone_hd": "filmzone_hd",
            "ltv7_hd": "ltv7_hd",
            "ltv1_hd": "ltv1_hd",
        }
        self.current_channel = None
        self.current_start_time = None
        self.runner = runner
        self.dry_run = dry_run
        self.enrich_enabled = enrich
        self._omdb = _UNSET
        self._ai_client = _UNSET
        self._excluded_titles = {
            normalize_title(t).casefold() for t in EXCLUDED_LOCAL_SHOWS
        }
        super().__init__(config)
        # BaseScraper appends here when enrich_result returns a falsy value
        self.excluded_resources = []

    def get_search_urls(self):
        day_range, start_date = self.get_days()
        base_url = (
            "https://www.tet.lv/televizija/tv-programma"
            "?tv-type=interactive&view-type=list"
            "&date={date_string}&channel={channel_id}"
        )

        runner = getattr(self, 'runner', None)
        if runner is None:
            for _day in day_range:
                date = start_date + timedelta(days=_day)
                for channel_name in self.channels:
                    yield self._channel_day_url(
                        base_url, channel_name, date
                    )
            return

        # Runner path: each channel x date cell is one checkpointed
        # item; oldest dates get the highest priority.
        entries = []
        for day_index in day_range:
            date = start_date + timedelta(days=day_index)
            date_str = date.strftime("%Y-%m-%d")
            for channel_name in self.channels:
                entries.append((
                    f"{channel_name}:{date_str}",
                    f"{channel_name} {date_str}",
                    -day_index,
                    (channel_name, date),
                ))
        items = runner.sync_items(entries)
        for item in runner.pending_items(items):
            channel_name, date = item.obj
            try:
                yield self._channel_day_url(base_url, channel_name, date)
                runner.touch()
            except Exception as e:
                runner.item_failed(item, e)
                continue
            runner.item_done(item)

    def _channel_day_url(self, base_url, channel_name, date):
        """Set current_channel/current_start_time for a channel x date
        cell and build its listing URL."""
        if self.dry_run:
            self.current_channel = (
                Channel.objects.filter(name=channel_name).first()
                or Channel(name=channel_name)
            )
        else:
            self.current_channel, _ = Channel.objects.get_or_create(
                name=channel_name
            )
        self.current_start_time = date
        return base_url.format(
            date_string=date.strftime("%Y-%m-%d"),
            channel_id=channel_name,
        )

    def get_days(self):
        days_in_past = self.config.get("days_in_past", 7)
        days_in_future = self.config.get("days_in_future", 7)
        day_range = range(days_in_past + days_in_future)
        start_date = timezone.now() - timedelta(days=days_in_past)
        return day_range, start_date

    def parse_results(self, search_response):
        """
        Parses the TV program listing page into a list of structured dictionaries.
        """
        soup = BeautifulSoup(search_response.data, "html.parser")
        program_soup = soup.find_all("div", class_="show-expander-content")

        ch_key = self.current_channel.name if self.current_channel else ""
        parsed_programs = []
        for program_html in program_soup:
            title_lv = None
            try:
                title_element = program_html.find("h2", class_="tet-font__headline--s")
                if not title_element:
                    continue
                title_lv = title_element.text.strip()

                subtitle_element = program_html.find("p", class_="subtitle")
                if not subtitle_element:
                    continue

                time_element = subtitle_element.find("span")
                if not time_element:
                    continue

                time_str_full = time_element.text.strip()
                time_parts = time_str_full.split(" - ")
                start_time_str, end_time_str = time_parts[0], time_parts[1]

                description_lv_element = program_html.find(
                    "p", class_="text tet-font__body--s"
                )
                description_lv = (
                    description_lv_element.text.strip()
                    if description_lv_element
                    else ""
                )

                image_container = program_html.find("div", class_="expander-image")
                image_url = ""
                if image_container:
                    image_element = image_container.find("img")
                    image_url = (
                        image_element["src"]
                        if image_element and image_element.has_attr("src")
                        else ""
                    )

                # Per-airing event id lives on the wrapping
                # .show-expander div (verified 1:1 with .show-line).
                expander = program_html.find_parent(
                    "div", class_="show-expander"
                )
                source_event_id = (
                    expander.get("data-id") if expander else None
                )

                start_time_obj = datetime.strptime(start_time_str, "%H:%M").time()
                full_start_time = self.current_start_time.replace(
                    hour=start_time_obj.hour,
                    minute=start_time_obj.minute,
                    second=0,
                    microsecond=0,
                )

                end_time_obj = datetime.strptime(end_time_str, "%H:%M").time()
                start_dt = datetime.combine(self.current_start_time.date(), start_time_obj)
                end_dt = datetime.combine(self.current_start_time.date(), end_time_obj)
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                duration_minutes = int((end_dt - start_dt).total_seconds() / 60)

                classification = classify(
                    title_lv, description_lv, ch_key, duration_minutes
                )
                parsed_programs.append(
                    annotate_result(
                        {
                            "title_lv": title_lv,
                            "description_lv": description_lv,
                            "start_time": full_start_time,
                            "duration_minutes": duration_minutes,
                            "image_url": image_url,
                            "channel": self.current_channel,
                            "classification": classification,
                            "source_event_id": source_event_id,
                        }
                    )
                )
            except (IndexError, ValueError) as e:
                label = title_lv or "?"
                logger.warning(
                    f"Skipping program '{label}' due to a data parsing error: {e}"
                )
                continue

        logger.info(f"Parsed {len(parsed_programs)} programs from the page.")
        return parsed_programs

    def _is_excluded_title(self, result):
        """Exclusions match on the normalized title (fixes the
        ``(atkārtojums)`` bypass) and on the parsed series base."""
        if result['title_norm'].casefold() in self._excluded_titles:
            return True
        series = (result.get('series_title') or '').casefold()
        return bool(series) and series in self._excluded_titles

    def remove_redundant_results(self, programs):
        """
        Drop excluded titles and airings already in the DB; attach the
        resolved Show to each surviving result. Airings of known shows
        are kept — they become new Program rows on the same Show.
        """
        # current_start_time carries the scrape time-of-day; the
        # listing day spans from its midnight.
        day_start = self.current_start_time.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_end = day_start + timedelta(days=1)

        # Batch-resolve existing Shows by dedup key.
        shows_by_key = {
            s.dedup_key: s
            for s in Show.objects.filter(
                dedup_key__in={p['dedup_key'] for p in programs}
            )
        }

        # Airings already stored for this channel-day: by source event
        # id, by (show, start_time), and — for pre-backfill rows with
        # no Show — by (normalized title, start_time). An unsaved
        # channel (dry-run) can have no stored airings.
        seen_events = set()
        seen_show_times = set()
        seen_title_times = set()
        existing_airings = (
            Program.objects.filter(
                channel_id=self.current_channel.pk,
                start_time__gte=day_start,
                start_time__lt=day_end,
            ).values_list(
                'show_id', 'start_time', 'title_lv', 'source_event_id'
            )
            if self.current_channel and self.current_channel.pk
            else []
        )
        for show_id, start_time, title_lv, event_id in existing_airings:
            if event_id:
                seen_events.add(event_id)
            if show_id:
                seen_show_times.add((show_id, start_time))
            else:
                seen_title_times.add(
                    (normalize_title(title_lv).casefold(), start_time)
                )

        filtered_programs = []
        batch_events = set()
        for program in programs:
            if self._is_excluded_title(program):
                continue
            event_id = program.get('source_event_id')
            if (
                event_id
                and (event_id in seen_events or event_id in batch_events)
            ):
                continue
            # Pre-backfill airings have no Show — match them by
            # normalized title + start_time regardless of whether this
            # result resolved to a Show.
            title_time = (
                program['title_norm'].casefold(),
                program['start_time'],
            )
            if title_time in seen_title_times:
                continue
            show = shows_by_key.get(program['dedup_key'])
            if show is not None:
                if show.is_excluded:
                    continue
                if (show.pk, program['start_time']) in seen_show_times:
                    continue
                program['show'] = show
            if event_id:
                batch_events.add(event_id)
            filtered_programs.append(program)

        removed_count = len(programs) - len(filtered_programs)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} redundant programs.")

        return filtered_programs

    def _get_omdb(self):
        """Lazy OMDbClient; None when OMDB_KEY is not configured."""
        if self._omdb is _UNSET:
            api_key = getattr(settings, 'OMDB_KEY', '') or ''
            if api_key:
                self._omdb = OMDbClient(self.make_request, api_key)
            else:
                logger.info(
                    'OMDB_KEY not set — OMDb enrichment disabled'
                )
                self._omdb = None
        return self._omdb

    def _get_ai_client(self):
        """Lazy JobClient for title translation; None when the job is
        unavailable/disabled or its cap is already reached."""
        if self._ai_client is _UNSET:
            try:
                self._ai_client = get_job_client(TITLE_TRANSLATION)
            except ai_errors.AIError as e:
                logger.warning(
                    'Title translation job unavailable, shows will '
                    'not be translated this run: %s', e
                )
                self._ai_client = None
        return self._ai_client

    def enrich_result(self, result):
        """
        Resolve the airing to a Show (creating + enriching it on first
        sight) and build the resource dict for ``initiate_resource``.
        """
        show = result.get('show')
        if show is None and not self.dry_run:
            show, created = get_or_create_show(result)
            if created and self.enrich_enabled and not show.is_excluded:
                enrich_show(
                    show,
                    omdb=self._get_omdb(),
                    ai_client=self._get_ai_client(),
                    request_fn=self.make_request,
                )

        c = result["classification"]
        description_lv = result.get("description_lv") or ""
        raw_description = description_lv
        description_lv = (
            re.sub(r"&\w+;", "", raw_description)
            if raw_description else ""
        )

        reasoning = (c.reasoning or "")[:255]
        return {
            "show": show,
            "source_event_id": result.get("source_event_id"),
            "title_lv": result["title_lv"],
            "title_eng": show.title_eng if show else None,
            "description_lv": description_lv,
            "description_eng": show.description_eng if show else None,
            "image": result.get("image_url") or (
                show.image_url if show else ""
            ) or "",
            "url": show.imdb_url if show else None,
            "content_rating": show.pg_rating if show else "",
            "rating_value": (
                str(show.imdb_rating)
                if show and show.imdb_rating is not None
                else None
            ),
            "imdb_id": show.imdb_id if show else None,
            "content_type": (
                show.content_type if show else c.content_type
            ),
            "classification_confidence": (
                show.classification_confidence if show else c.confidence
            ),
            "classification_reasoning": (
                show.classification_reasoning if show else reasoning
            ),
            "match_ratio": show.title_match_ratio if show else 0.0,
            "start_time": result.get("start_time", self.current_start_time),
            "duration_minutes": result.get("duration_minutes"),
        }

    def initiate_resource(self, resource_link):
        """Create an unsaved Program airing instance to be bulk
        inserted later."""
        ct = resource_link.get("content_type", Program.ContentType.UNKNOWN)
        if ct not in Program.ContentType.values:
            ct = Program.ContentType.UNKNOWN

        program = Program(
            show=resource_link.get("show"),
            source_event_id=resource_link.get("source_event_id"),
            title_lv=resource_link["title_lv"],
            title_eng=resource_link.get("title_eng"),
            description_lv=resource_link.get("description_lv"),
            description_eng=resource_link.get("description_eng"),
            image_url=resource_link.get("image"),
            url=resource_link.get("url"),
            pg_rating=resource_link.get("content_rating"),
            imdb_rating=resource_link.get("rating_value"),
            imdb_id=resource_link.get("imdb_id"),
            title_match_ratio=resource_link.get("match_ratio", 0.0),
            description_match_ratio=0.0,
            combined_match_ratio=resource_link.get("match_ratio", 0.0),
            content_type=ct,
            classification_confidence=float(
                resource_link.get("classification_confidence", 0.0) or 0.0
            ),
            classification_reasoning=resource_link.get(
                "classification_reasoning"
            ),
            channel=self.current_channel,
            start_time=resource_link.get(
                "start_time", self.current_start_time
            ),
            duration_minutes=resource_link.get("duration_minutes"),
        )
        return program

    def create_or_update_resources(self, resources: list[Program]):
        """Bulk creates program airings; overlapping reruns are
        idempotent via ``ignore_conflicts``."""
        if not resources:
            return
        if self.dry_run:
            logger.info(
                "[dry-run] would bulk-create %d program(s)",
                len(resources),
            )
            return
        Program.objects.bulk_create(resources, ignore_conflicts=True)
        return

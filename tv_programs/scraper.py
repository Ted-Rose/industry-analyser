import logging
import re
from datetime import datetime, timedelta

from bs4 import BeautifulSoup
from django.utils import timezone

from core_scraper.base import BaseScraper
from .classification import EXCLUDED_LOCAL_SHOWS, classify
from .models import Program, Channel

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger("tv_programs")


class TVProgramScraper(BaseScraper):
    """
    Scraper for TV programs from tet.lv: grid parse + local heuristic
    classification (no IMDb; see TV_CONTENT_IDENTIFICATION_PLAN.md).
    """

    def __init__(self, config=None):
        self.validate_result = True
        self.enrich_search_results = True
        self.channels = {
            "filmzone_hd": "filmzone_hd",
            "ltv7_hd": "ltv7_hd",
            "ltv1_hd": "ltv1_hd",
        }
        self.current_channel = None
        self.current_start_time = None
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

        for _day in day_range:
            date = start_date + timedelta(days=_day)
            for channel_name in self.channels:
                self.current_channel, _ = Channel.objects.get_or_create(
                    name=channel_name
                )
                self.current_start_time = date
                url = base_url.format(
                    date_string=date.strftime("%Y-%m-%d"),
                    channel_id=channel_name,
                )
                yield url
        return

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
                    {
                        "title_lv": title_lv,
                        "description_lv": description_lv,
                        "start_time": full_start_time,
                        "duration_minutes": duration_minutes,
                        "image_url": image_url,
                        "channel": self.current_channel,
                        "classification": classification,
                    }
                )
            except (IndexError, ValueError) as e:
                label = title_lv or "?"
                logger.warning(
                    f"Skipping program '{label}' due to a data parsing error: {e}"
                )
                continue

        logger.info(f"Parsed {len(parsed_programs)} programs from the page.")
        return parsed_programs

    def remove_redundant_results(self, programs):
        """
        Remove programs that are excluded or already in DB for the current day.
        """
        day_start = self.current_start_time
        day_end = day_start + timedelta(days=1)

        titles_to_check = [p["title_lv"] for p in programs]
        existing_titles = set(
            Program.objects.filter(
                title_lv__in=titles_to_check,
                channel=self.current_channel,
                start_time__gte=day_start,
                start_time__lt=day_end,
            ).values_list("title_lv", flat=True)
        )

        initial_program_count = len(programs)
        filtered_programs = []
        for program in programs:
            title = program["title_lv"]
            if title in EXCLUDED_LOCAL_SHOWS or title in existing_titles:
                continue
            filtered_programs.append(program)

        removed_count = initial_program_count - len(filtered_programs)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} redundant programs.")

        return filtered_programs

    def enrich_result(self, result):
        """
        Build a resource dict from tet fields + local classification (no IMDb).
        """
        c = result["classification"]
        description_lv = result.get("description_lv") or ""
        raw_description = description_lv
        description_lv = re.sub(r"&\w+;", "", raw_description) if raw_description else ""

        reasoning = (c.reasoning or "")[:255]
        return {
            "title_lv": result["title_lv"],
            "title_eng": None,
            "description_lv": description_lv,
            "description_eng": None,
            "image": result.get("image_url") or "",
            "url": None,
            "content_rating": "",
            "rating_value": None,
            "content_type": c.content_type,
            "classification_confidence": c.confidence,
            "classification_reasoning": reasoning,
            "match_ratio": 0.0,
            "start_time": result.get("start_time", self.current_start_time),
            "duration_minutes": result.get("duration_minutes"),
        }

    def initiate_resource(self, resource_link):
        """Create an unsaved Program instance to be bulk inserted later."""
        ct = resource_link.get("content_type", Program.ContentType.UNKNOWN)
        if ct not in Program.ContentType.values:
            ct = Program.ContentType.UNKNOWN

        program = Program(
            title_lv=resource_link["title_lv"],
            title_eng=resource_link.get("title_eng"),
            description_lv=resource_link.get("description_lv"),
            description_eng=resource_link.get("description_eng"),
            image_url=resource_link.get("image"),
            url=resource_link.get("url"),
            pg_rating=resource_link.get("content_rating"),
            imdb_rating=resource_link.get("rating_value")
            if resource_link.get("rating_value") is not None
            else None,
            title_match_ratio=resource_link.get("match_ratio", 0.0),
            description_match_ratio=0.0,
            combined_match_ratio=resource_link.get("match_ratio", 0.0),
            content_type=ct,
            classification_confidence=float(
                resource_link.get("classification_confidence", 0.0) or 0.0
            ),
            classification_reasoning=resource_link.get("classification_reasoning"),
            channel=self.current_channel,
            start_time=resource_link.get("start_time", self.current_start_time),
            duration_minutes=resource_link.get("duration_minutes"),
        )
        return program

    def create_or_update_resources(self, resources: list[Program]):
        """Bulk creates program resources."""
        if not resources:
            return
        # TODO: This won't update existing resources, only create new ones
        Program.objects.bulk_create(resources)
        return

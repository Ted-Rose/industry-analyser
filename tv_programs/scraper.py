import logging
import json
import re
from bs4 import BeautifulSoup
import urllib3
from datetime import datetime, timedelta
from django.utils import timezone
from difflib import SequenceMatcher
from urllib.parse import quote_plus
from typing import List

from core_scraper.base import BaseScraper
from .models import Program, Channel
from .utils import translate_lv_to_eng

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger('tv_programs')


class TVProgramScraper(BaseScraper):
    """
    Scraper for TV programs from various sources.
    """

    def __init__(self, config=None):
        """
        Initialize the TV program scraper.

        Args:
            config (dict, optional): Configuration for the scraper
        """
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
        self.excluded_resources = [
            'Panorāma', 'Dienas ziņas', 'Krustpunktā', 'Rīta Panorāma',
            'Laika ziņas', 'Sporta ziņas', 'Nakts ziņas', 'Kultūras ziņas',
            'Saki Jā!', 'Spiegu spēles', 'De Facto', 'Laika ziņas',
            'Basketbols.Basketbols: NBA.', 'Leģendārais loms', 'Rīta Panorāma',
            'Aizliegtais paņēmiens', 'UgunsGrēks 4', 'Vides fakti',
            'Aculiecinieks', '1 :1. Aktuālā intervija', 'Sporta studija',
            'Autoziņas', 'Bez Tabu', '900 sekundes', 'Kultūršoks',
            'SuperBingo', 'Kobra 17', 'Tāskmāsters'
        ]

    def get_search_urls(self):
        day_range, start_date = self.get_days()
        base_url = (
            "https://www.tet.lv/televizija/tv-programma"
            "?tv-type=interactive&view-type=list"
            "&date={date_string}&channel={channel_id}"
        )

        for day in day_range:
            date = start_date + timedelta(days=day)
            for channel_name in self.channels:
                self.current_channel, _ = Channel.objects.get_or_create(
                  name=channel_name
                )
                self.current_start_time = date
                url = base_url.format(
                  date_string=date.strftime('%Y-%m-%d'),
                  channel_id=channel_name
                )
                yield url
        return

    def get_days(self):
        days_in_past = self.config.get('days_in_past', 7)
        days_in_future = self.config.get('days_in_future', 7)
        day_range = range(days_in_past + days_in_future)
        start_date = timezone.now() - timedelta(days=days_in_past)
        return day_range, start_date

    def parse_results(
        self,
        search_response: urllib3.response.HTTPResponse
    ) -> List:
        """
        Parses the TV program listing page into a list of structured dictionaries.
        """
        soup = BeautifulSoup(search_response.data, 'html.parser')
        program_soup = soup.find_all('div', class_="show-expander-content")

        parsed_programs = []
        for program_html in program_soup:
            try:
                title_element = program_html.find('h2', class_="tet-font__headline--s")
                if not title_element:
                    continue  # Skip if there's no title
                title_lv = title_element.text.strip()

                subtitle_element = program_html.find('p', class_="subtitle")
                if not subtitle_element:
                    continue  # Skip if there's no time/subtitle info

                time_element = subtitle_element.find('span')
                if not time_element:
                    continue

                time_str_full = time_element.text.strip()
                time_parts = time_str_full.split(' - ')
                start_time_str, end_time_str = time_parts[0], time_parts[1]

                description_lv_element = program_html.find('p', class_="text tet-font__body--s")
                description_lv = description_lv_element.text.strip() if description_lv_element else ""

                image_container = program_html.find('div', class_='expander-image')
                image_url = ""
                if image_container:
                    image_element = image_container.find('img')
                    image_url = image_element['src'] if image_element and image_element.has_attr('src') else ""

                # Calculate start time
                start_time_obj = datetime.strptime(start_time_str, '%H:%M').time()
                full_start_time = self.current_start_time.replace(
                    hour=start_time_obj.hour, minute=start_time_obj.minute, second=0, microsecond=0
                )

                # Calculate duration
                end_time_obj = datetime.strptime(end_time_str, '%H:%M').time()
                start_dt = datetime.combine(self.current_start_time.date(), start_time_obj)
                end_dt = datetime.combine(self.current_start_time.date(), end_time_obj)
                if end_dt < start_dt:
                    end_dt += timedelta(days=1)
                duration_minutes = int((end_dt - start_dt).total_seconds() / 60)

                parsed_programs.append({
                    'title_lv': title_lv,
                    'description_lv': description_lv,
                    'start_time': full_start_time,
                    'duration_minutes': duration_minutes,
                    'image_url': image_url,
                    'channel': self.current_channel,
                })
            except (IndexError, ValueError) as e:
                logger.warning(f"Skipping program '{title_lv}' due to a data parsing error: {e}")
                continue

        logger.info(f"Parsed {len(parsed_programs)} programs from the page.")
        return parsed_programs

    def remove_redundant_results(self, programs):
        """
        Remove programs that are excluded or already in DB for the current day.
        """
        day_start = self.current_start_time
        day_end = day_start + timedelta(days=1)

        titles_to_check = [p['title_lv'] for p in programs]
        # TODO: This has to be retrieved in single query for howl scrape
        existing_titles = set(
            Program.objects.filter(
                title_lv__in=titles_to_check,
                channel=self.current_channel,
                start_time__gte=day_start,
                start_time__lt=day_end
            ).values_list('title_lv', flat=True)
        )

        initial_program_count = len(programs)
        filtered_programs = []
        for program in programs:
            title = program['title_lv']
            if title in self.excluded_resources or title in existing_titles:
                continue
            filtered_programs.append(program)

        removed_count = initial_program_count - len(filtered_programs)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} redundant programs.")

        return filtered_programs

    def get_resource_info_link(self, program):
        title_lv = program["title_lv"]
        encoded_title_lv = quote_plus(title_lv, encoding='utf-8')
        return f"https://www.imdb.com/find/?q={encoded_title_lv}&ref_=nv_sr_sm"

    def validate_and_return(self, program, imdb_search_results):
        """Validate and enrich program data with IMDB information.

        Args:
            program: Dictionary containing program data (title_lv, etc.)
            imdb_search_results: HTTP response from IMDB search

        Returns:
            dict: Program data enriched with IMDB information or None
              if validation fails
        """
        title_lv = program['title_lv']

        # Process IMDB search results
        imdb_search_soup = BeautifulSoup(
            imdb_search_results.data, 'html.parser')
        search_results = imdb_search_soup.find(
            'div', class_="ipc-metadata-list-summary-item__tc")
        if search_results is None:
            logger.info(f"Not found in IMDb: {title_lv}")
            return None

        link_element = search_results.find('a')
        if not link_element:
            logger.info(f"Link not found in IMDb: {title_lv}")
            return None

        # Get detailed IMDB data
        link = "https://www.imdb.com/" + link_element['href']
        imdb_program_response = self.make_request(link)
        if not imdb_program_response:
            # If doesn't exist in IMDb, then program probably not a movie/show
            return None

        imdb_soup = BeautifulSoup(imdb_program_response.data, 'html.parser')
        return self.enrich_with_imdb_data(program, imdb_soup)

    def initiate_resource(self, resource_link):
        """Create an unsaved Program instance to be bulk inserted later."""
        program = Program(
            title_lv=resource_link['title_lv'],
            title_eng=resource_link['title_eng'],
            description_lv=resource_link.get('description_lv'),
            description_eng=resource_link.get('description_eng'),
            image_url=resource_link.get('image'),
            url=resource_link.get('url'),
            pg_rating=resource_link.get('content_rating'),
            imdb_rating=resource_link.get('rating_value'),
            title_match_ratio=resource_link.get('match_ratio', 0),
            combined_match_ratio=resource_link.get('match_ratio', 0),
            channel=self.current_channel,
            start_time=self.current_start_time,
            duration_minutes=resource_link.get('duration_minutes', None),
        )
        return program

    def create_or_update_resources(self, resources: list[Program]):
        """Bulk creates program resources."""
        if not resources:
            return
        # TODO: This won't update existing resources, only create new ones
        Program.objects.bulk_create(resources)
        return

    def enrich_with_imdb_data(self, program, imdb_program):
        """
        Enrich program data with information from IMDB.

        Args:
            program: Dictionary containing program data
                (title_lv, description_lv, etc.)
            imdb_program: BeautifulSoup object for the detailed IMDb page

        Returns:
            dict: Program data enriched with IMDB information or None
              if processing fails
        """
        title_lv = program['title_lv']

        # Clean description HTML entities
        raw_description = program.get('description_lv', '')
        description_lv = re.sub(
            r"&\w+;", "", raw_description
        ) if raw_description else ""

        # Extract structured data from the JSON-LD script tag on the IMDb page
        script_tag = imdb_program.find(
          'script', {'type': 'application/ld+json'}
        )
        if not script_tag:
            return None

        try:
            json_data = json.loads(script_tag.string)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse JSON-LD for {title_lv}")
            return None

        # Calculate match ratios
        title_match_ratio = 0
        description_match_ratio = 0

        title_lv_to_eng = translate_lv_to_eng(title_lv)
        title_match_ratio = SequenceMatcher(
            None, json_data.get("name", ""), title_lv_to_eng
        ).ratio()

        if description_lv:
            description_lv_to_eng = translate_lv_to_eng(description_lv)
            description_match_ratio = SequenceMatcher(
                None, json_data.get("description", ""), description_lv_to_eng
            ).ratio()

        combined_match_ratio = (
            (title_match_ratio + description_match_ratio) / 2
            if description_match_ratio > 0
            else title_match_ratio
        )

        # Get IMDB ratings
        aggregate_rating = json_data.get("aggregateRating", {})
        rating_value = aggregate_rating.get("ratingValue")

        logger.info(f"Found title: {json_data.get('name')}")
        logger.info(f"For LV title: {title_lv}")

        # Merge program data with IMDB data
        return {
            "title_eng": json_data.get("name"),
            "description_eng": json_data.get("description"),
            "image": program.get('image_url', '') or json_data.get("image"),
            "url": json_data.get("url"),
            "content_rating": json_data.get("contentRating", ""),
            "rating_value": rating_value,
            "published_date": json_data.get("datePublished"),
            "type": json_data.get("@type", ""),
            "match_ratio": combined_match_ratio,
            # Preserve any additional fields from input dictionary
            **(program if isinstance(program, dict) else {})
        }

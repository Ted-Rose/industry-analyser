import logging
import json
import re
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from django.utils import timezone
from difflib import SequenceMatcher
from urllib.parse import urlencode

from django.conf import settings

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
            config (dict, optional): Configuration for the scraper.
        """
        super().__init__(config)
        self.validate_result = True
        self.enrich_search_results = True
        self.channels = {
            "filmzone_hd": "filmzone_hd",
            "ltv7_hd": "ltv7_hd",
            "ltv1_hd": "ltv1_hd",
        }
        self.current_channel = None
        self.current_start_time = None
        self.omdb_request_count = 0
        self.omdb_request_limit = 1000  # Daily limit
        self.last_omdb_request_time = 0
        self.min_request_interval = 0.1  # 100ms between requests
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

    def parse_results(self, search_results):
        html_content = search_results.data
        soup = BeautifulSoup(html_content, 'html.parser')

        programs = soup.find_all('div', class_="show-expander-content")
        return programs

    def remove_redundant_results(self, programs):
        """
        Remove programs that are excluded or already in DB for the current day.
        """
        if not programs:
            return []

        day_start = self.current_start_time
        day_end = day_start + timedelta(days=1)

        titles_to_check = []
        for p in programs:
            title = p.find(class_="tet-font__headline--s").text.strip()
            titles_to_check.append(title)

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
            title = program.find(class_="tet-font__headline--s").text.strip()
            if title in self.excluded_resources or title in existing_titles:
                continue
            filtered_programs.append(program)

        removed_count = initial_program_count - len(filtered_programs)
        if removed_count > 0:
            logger.info(f"Removed {removed_count} redundant programs.")

        return filtered_programs

    def extract_resources(self, search_results):
        """Overrides BaseScraper to implement a single-step enrichment."""
        resources = []
        for result in search_results:
            # In this scraper, initiate_resource handles the entire enrichment
            # process, including fetching data from the OMDb API.
            resource = self.initiate_resource(result)
            if resource:
                resources.append(resource)
        return resources

    def initiate_resource(self, resource_link):
        # Step 1.3 & 1.4: Extract data, call OMDb API, and process
        title_lv_element = resource_link.find(class_="tet-font__headline--s")
        if not title_lv_element:
            logger.debug("No title element found, skipping.")
            return None
        title_lv = title_lv_element.text.strip()

        description_lv_element = resource_link.find(
            class_="text tet-font__body--s"
        )
        description_lv = (
            description_lv_element.text.strip() if description_lv_element else ""
        )

        # Extract year for better matching (Phase 2 enhancement)
        year_match = re.search(r'\b(19\d{2}|20\d{2})\b', title_lv)
        year = year_match.group(1) if year_match else None

        # Translate title for OMDb search
        title_eng = translate_lv_to_eng(title_lv)

        # Determine content type
        content_type = 'movie' if 'filma' in description_lv.lower() else 'series'

        # Get data from OMDb
        omdb_data = self.get_omdb_data(
            title_eng, year=year, content_type=content_type
        )

        # If no results, try without content_type filter
        if not omdb_data:
            omdb_data = self.get_omdb_data(title_eng, year=year)

        if not omdb_data:
            logger.warning(f"Could not find '{title_lv}' in OMDb.")
            return None

        # Process and map fields
        processed_data = self.process_item(
            resource_link, omdb_data, title_lv, description_lv
        )

        # Create an unsaved Program instance
        program = Program(
            title_lv=processed_data['title_lv'],
            title_eng=processed_data['title_eng'],
            description_lv=processed_data.get('description_lv'),
            description_eng=processed_data.get('description_eng'),
            image_url=processed_data.get('image_url'),
            url=processed_data.get('url'),
            pg_rating=processed_data.get('pg_rating'),
            imdb_rating=processed_data.get('imdb_rating'),
            title_match_ratio=processed_data.get('combined_match_ratio', 0),
            combined_match_ratio=processed_data.get('combined_match_ratio', 0),
            channel=self.current_channel,
            start_time=self.current_start_time,
            duration_minutes=processed_data.get('duration_minutes', None),
        )
        return program

    def create_or_update_resources(self, resources):
        if not resources:
            return
        # TODO: This won't update existing resources, only create new ones
        Program.objects.bulk_create(resources)
        return

    # Helper methods

    def get_days(self):
        days_in_past = self.config.get(
          'days_in_past',
          7
        )
        days_in_future = self.config.get(
          'days_in_future',
          7
        )
        day_range = range(days_in_past + days_in_future)
        start_date = timezone.now() - timedelta(days=days_in_past)
        return day_range, start_date

    def _omdb_request(self, **kwargs):
        """Make a single request to OMDb API."""
        # Check rate limit
        if self.omdb_request_count >= self.omdb_request_limit:
            logger.warning("OMDb daily request limit reached")
            return None

        # Throttle requests
        time_since_last = time.time() - self.last_omdb_request_time
        if time_since_last < self.min_request_interval:
            time.sleep(self.min_request_interval - time_since_last)

        base_params = {'apikey': settings.OMDB_KEY}
        params = {**base_params, **kwargs}
        encoded_params = urlencode(params)
        url = f"http://www.omdbapi.com/?{encoded_params}"

        response = self.make_request(url)

        # Update counters
        self.omdb_request_count += 1
        self.last_omdb_request_time = time.time()
        logger.debug(
            f"OMDb requests: {self.omdb_request_count}/{self.omdb_request_limit}"
        )

        if response and response.status == 200:
            data = json.loads(response.data)
            if data.get('Response') == 'True':
                return data
        return None

    def get_omdb_data(self, title, year=None, content_type=None):
        """Get data from OMDb, with fallback to search."""
        # First try: Direct title match
        params = {'t': title}
        if year:
            params['y'] = year
        if content_type:
            params['type'] = content_type

        data = self._omdb_request(**params)
        if data:
            return data

        # Second try: Search and pick best match (Phase 2 enhancement)
        search_params = {'s': title}
        if content_type:
            search_params['type'] = content_type

        search_results = self._omdb_request(**search_params)

        if search_results and 'Search' in search_results:
            # Get full details for the first result
            best_match = search_results['Search'][0]
            return self._omdb_request(i=best_match['imdbID'])

        return None

    def process_item(self, program_data, omdb_data, title_lv, description_lv):
        """Process and map fields from OMDb data."""
        title_eng = omdb_data.get("Title", "")
        title_lv_to_eng = translate_lv_to_eng(title_lv)
        title_match_ratio = SequenceMatcher(None, title_eng, title_lv_to_eng).ratio()

        description_eng = omdb_data.get("Plot", "")
        description_lv_to_eng = translate_lv_to_eng(description_lv)
        description_match_ratio = SequenceMatcher(
            None, description_eng, description_lv_to_eng
        ).ratio()

        combined_match_ratio = (
            (title_match_ratio + description_match_ratio) / 2
            if description_match_ratio > 0
            else title_match_ratio
        )
        logger.debug(
            f"Match for '{title_lv}': Title={title_match_ratio:.2f}, "
            f"Desc={description_match_ratio:.2f}, "
            f"Combined={combined_match_ratio:.2f}"
        )

        tet_image_element = program_data.find('img')
        tet_image_url = tet_image_element['src'] if tet_image_element else None

        return {
            "title_lv": title_lv,
            "title_eng": title_eng,
            "description_lv": description_lv,
            "description_eng": description_eng,
            "image_url": omdb_data.get("Poster") or tet_image_url,
            "url": f"https://www.imdb.com/title/{omdb_data.get('imdbID')}/",
            "pg_rating": omdb_data.get("Rated"),
            "imdb_rating": omdb_data.get("imdbRating"),
            "published_date": omdb_data.get("Released"),
            "type": omdb_data.get("Type"),
            "combined_match_ratio": combined_match_ratio
        }

    def save_item(self, processed_item, channel_name, start_date):
        """
        Save a processed TV program item to the database.

        Args:
            processed_item (dict): Processed program data
            channel_name (str): Name of the channel
            start_date (str): Start date of the program in YYYY-MM-DD format

        Returns:
            Program: Saved program object
        """
        if not processed_item:
            return None

        channel, _ = Channel.objects.get_or_create(name=channel_name)

        program, created = Program.objects.update_or_create(
            url=processed_item["url"],
            defaults={
                'title_lv': processed_item.get("title_lv", ""),
                'title_eng': processed_item.get("title_eng"),
                'description_lv': processed_item.get("description_lv", ""),
                'description_eng': processed_item.get("description_eng", ""),
                'channel': channel,
                'start_time': datetime.strptime(start_date, '%Y-%m-%d'),
                'duration_minutes': processed_item.get("duration_minutes", 120),
                'image_url': processed_item.get("image_url"),
                'imdb_rating': processed_item.get("imdb_rating"),
                'pg_rating': processed_item.get("pg_rating"),
                'title_match_ratio': processed_item.get(
                    "combined_match_ratio", 0
                ),
                'combined_match_ratio': processed_item.get(
                    "combined_match_ratio", 0
                ),
            }
        )

        action = 'Created' if created else 'Updated'
        logger.info(f"{action} program: {program.title_eng}")
        return program


def fetch_tv_program_details():
    """
    Fetch TV program details from various sources.

    Returns:
        list: List of saved program objects
    """
    config = {}
    scraper = TVProgramScraper(config)
    return scraper.run()

import logging
import json
import re
import abc
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from django.utils import timezone
from difflib import SequenceMatcher
from urllib.parse import quote_plus

from core_scraper.base import BaseScraper
from .models import Program, Channel, Category, ProgramCategory
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
                self.current_channel, _ = Channel.objects.get_or_create(name=channel_name)
                self.current_start_time = date
                url = base_url.format(date_string=date.strftime('%Y-%m-%d'), channel_id=channel_name)
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

    def get_resource_info_link(self, program):
        title_lv = program.find(class_="tet-font__headline--s").text
        encoded_title_lv = quote_plus(title_lv, encoding='utf-8')
        return f"https://www.imdb.com/find/?q={encoded_title_lv}&ref_=nv_sr_sm"

    def validate_and_return(self, program, imdb_search_results):
        # TODO: Refactor down the callstack and consider refactoring up the callstack as well
        title_element = program.find(class_="tet-font__headline--s")
        if not title_element:
            logger.info("No title element found")
            return None

        title_lv = title_element.text.strip()

        soup = BeautifulSoup(imdb_search_results.data, 'html.parser')
        search_results = soup.find('div', class_="ipc-metadata-list-summary-item__tc")
        if search_results is None:
            logger.info(f"Not found in IMDB: {title_lv}")
            return None

        link_element = search_results.find('a')
        if link_element:
            link = "https://www.imdb.com/" + link_element['href']
        else:
            logger.info(f"Link not found in IMDB: {title_lv}")
            return None

        imdb_program = self.make_request(link)
        return self.process_item(program, imdb_program)

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

    def create_or_update_resources(self, resources):
        if not resources:
            return

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

    def get_ratings(self, query, content_type=None):
        """
        Get ratings and metadata for a TV program from IMDB.

        Args:
            query (str): The title of the program to search for
            content_type (str, optional): Type of content ('movie', 'tv', etc.)

        Returns:
            dict: Program metadata or None if not found
        """
        logger.info(f"Getting ratings for: {query}")

        encoded_query = quote_plus(query, encoding='utf-8')
        filter_param = "?s=tt" if content_type == "movie" else ""
        url = f"https://www.imdb.com/find/{filter_param}?q={encoded_query}&ref_=nv_sr_sm"

        search_results = self.make_request(url)
        if not search_results:
            logger.error("Failed to get search results")
            return None

        html_content = search_results.data
        soup = BeautifulSoup(html_content, 'html.parser')
        summary = soup.find('div', class_="ipc-metadata-list-summary-item__tc")

        if summary is None:
            logger.info(f"Summary not found for: {query}")
            return None

        link_element = summary.find('a')
        if link_element:
            link = "https://www.imdb.com/" + link_element['href']
        else:
            logger.info("Link not found")
            return None

        content_description = self.make_request(link)
        if not content_description:
            logger.error("Failed to get content description")
            return None

        html_content = content_description.data
        soup = BeautifulSoup(html_content, 'html.parser')

        script_tags = soup.find_all('script', type='application/ld+json')
        if not script_tags:
            logger.info("No script tags found")
            return None

        logger.info(f"Found {len(script_tags)} script tags")
        script_tag = script_tags[0]
        json_data = script_tag.string

        if not json_data:
            logger.info("No JSON data found in script tag")
            return None

        try:
            parsed_data = json.loads(json_data)

            description = parsed_data.get("description", "")
            description = re.sub(r"&\\w+;", "", description)

            published_date = parsed_data.get("datePublished")

            content_title = parsed_data.get("name")

            return {
                "title": content_title,
                "type": parsed_data.get("@type"),
                "description": description,
                "image": parsed_data.get("image"),
                "url": parsed_data.get("url"),
                "content_rating": parsed_data.get("contentRating"),
                "rating_value": parsed_data.get("aggregateRating", {}).get("ratingValue"),
                "published_date": published_date,
            }
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing JSON: {e}")
            return None

    def process_item(self, program, imdb_program):
        """
        Process a single TV program item.

        Args:
            content_description: Raw program data from the scraper

        Returns:
            dict: Processed program data
        """
        title_lv = None
        description_lv = None

        title_element = program.find(class_="tet-font__headline--s")
        if title_element:
            title_lv = title_element.text.strip()
        else:
            logger.info("No title found for program")
            return None

        description_element = imdb_program.find(
            class_="text tet-font__body--s")
        if description_element:
            description_lv = re.sub(
                r"&\w+;",
                "",
                description_element.text.strip()
            )
        ratings = imdb_program
        if not ratings:
            logger.info(f"No ratings found for: {title_lv}")
            # TODO: Add to skippable programs
            return None

        # Calculate match ratio between original and translated titles with IMDb data
        title_match_ratio = 0
        description_match_ratio = 0

        if title_lv:
            title_lv_to_eng = translate_lv_to_eng(title_lv)
            title_match_ratio = SequenceMatcher(
                None, ratings["title"], title_lv_to_eng
            ).ratio()
            logger.info(f"Title LV: {title_lv}")
            logger.info(f"Title LV to ENG: {title_lv_to_eng}")
            logger.info(f"Title ENG: {ratings['title']}")
            logger.info(f"Title match ratio: {title_match_ratio}")

        if description_lv:
            description_lv_to_eng = translate_lv_to_eng(description_lv)
            description_match_ratio = SequenceMatcher(None, ratings["description"], description_lv_to_eng).ratio()
            logger.info(f"Description LV: {description_lv}")
            logger.info(f"Description LV to ENG: {description_lv_to_eng}")
            logger.info(f"Description ENG: {ratings['description']}")
            logger.info(f"Description match ratio: {description_match_ratio}")

        combined_match_ratio = (title_match_ratio + description_match_ratio) / 2 if description_match_ratio > 0 else title_match_ratio
        logger.info(f"Overall match ratio: {combined_match_ratio}")

        image_element = program.find('img')
        image_url = image_element['src'] if image_element else ratings.get("image")

        return {
            "title_lv": title_lv,
            "title_eng": ratings["title"],
            "description_lv": description_lv,
            "description_eng": ratings["description"],
            "image": image_url,
            "url": ratings["url"],
            "content_rating": ratings.get("content_rating", ""),
            "rating_value": ratings.get("rating_value"),
            "published_date": ratings.get("published_date"),
            "type": ratings.get("type", ""),
            "match_ratio": combined_match_ratio
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
                'title_eng': processed_item["title_eng"],
                'description_lv': processed_item.get("description_lv", ""),
                'description_eng': processed_item.get("description_eng", ""),
                'channel': channel,
                'start_time': datetime.strptime(start_date, '%Y-%m-%d'),
                'duration_minutes': processed_item.get("duration_minutes", 120),
                'url': processed_item["url"],
                'image_url': processed_item.get("image", None),
                'imdb_rating': processed_item.get("rating_value", None),
                'pg_rating': processed_item.get("content_rating", None),
                'title_match_ratio': processed_item.get("match_ratio", 0),
                'combined_match_ratio': processed_item.get("match_ratio", 0)
            }
        )

        action = 'Created' if created else 'Updated'
        logger.info(f"{action} program: {program.title_eng}")
        return program

    def scrape_tv_programs(self):
        """
        Scrape TV programs from Tet.lv

        Returns:
            list: List of saved program objects
        """
        channels = {
            "filmzone_hd": "filmzone_hd",
            "ltv7_hd": "ltv7_hd",
            "ltv1_hd": "ltv1_hd",
        }
        oldest_date = (timezone.now() - timedelta(days=6))
        saved_programs = []

        for channel_name, channel_id in channels.items():
            logger.info(f"Scraping channel: {channel_name}")

            # Data is available for a span of 14 days
            for day in range(14):
                date = (oldest_date + timedelta(days=day))
                date_string = date.strftime('%d-%m-%Y')
                start_date = date.strftime('%Y-%m-%d')

                logger.info(f"Scraping date: {date_string}")
                url = f"https://www.tet.lv/televizija/tv-programma?tv-type=interactive&view-type=list&date={date_string}&channel={channel_id}"

                response = self.make_request(url)
                if not response:
                    logger.error(f"Failed to get data for {channel_name} on {date_string}")
                    continue

                html_content = response.data
                soup = BeautifulSoup(html_content, 'html.parser')

                contents = soup.find_all('div', class_="show-expander-content")
                logger.info(f"Found {len(contents)} programs for {channel_name} on {date_string}")

                for program_data in contents:
                    processed_item = self.process_item(program_data)
                    if processed_item:
                        saved_program = self.save_item(processed_item, channel_name, start_date)
                        if saved_program:
                            saved_programs.append(saved_program)

        return saved_programs

    def old_run(self):
        """
        Run the TV program scraper.

        Returns:
            list: List of saved program objects
        """
        logger.info("Starting TV program scraper")

        return self.scrape_tv_programs()


def fetch_tv_program_details():
    """
    Fetch TV program details from various sources.

    Returns:
        list: List of saved program objects
    """
    config = {}
    scraper = TVProgramScraper(config)
    return scraper.run()

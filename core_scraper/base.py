import abc
import logging
import time
import random
import urllib3
from typing import List
from django.conf import settings
from urllib.parse import urlparse
import json
from urllib3.util.retry import Retry
from urllib3.exceptions import MaxRetryError

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger('core_scraper')


class BaseScraper(abc.ABC):
    """
    Abstract base class for all scrapers in the industry-analyser project.
    Provides common functionality for scraping different types of content.
    """

    def __init__(self, config=None):
        """
        Initialize the scraper with configuration.

        Args:
            config (dict, optional): Configuration for the scraper
        """
        if settings.DEBUG:
            raise ValueError(
                "Scrapers should not be run with DEBUG=True. "
                "This is a safety measure to prevent accidental scraping of live sites during development."
            )

        self.config = config or {}
        self.last_sleep_by_domain = {}
        self.default_domain = 'default'
        retry_strategy = Retry(
            total=3,
            backoff_factor=30,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        self.http = urllib3.PoolManager(
            retries=retry_strategy,
        )

        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6446.75"
        }

        logger.debug(f"Initialized {self.__class__.__name__}")

    def run(self):
        for search_url in self.get_search_urls():
            new_or_updated_resources = self.search_portal(search_url)
            if new_or_updated_resources:
                self.create_or_update_resources(new_or_updated_resources)
        return

    def search_portal(self, search_url):
        search_results = self.make_request(search_url)
        # Format and prune redundant resources
        formatted_results = self.format_results(search_results)

        if not formatted_results:
            return

        pruned_results = self.remove_redundant_results(formatted_results)

        return self.extract_resources(pruned_results)

    def format_results(self, search_results):
        raise NotImplementedError

    def extract_resources(self, search_results):
        if self.enrich_search_results:
            resources = []
            for result in search_results:
                enriched_result = self.enrich_result(result)
                
                if not enriched_result:
                    self.excluded_resources.append(result)
                    continue
                
                resource = self.initiate_resource(enriched_result)
                resources.append(resource)
                
                if len(resources) >= 2:
                    break
            
            return resources
        else:
            return self.initiate_resources(search_results)

    def enrich_result(self, result):
        info_link = self.get_resource_info_link(result)
        extra_info = self.make_request(info_link)

        if self.validate_result:
            return self.validate_and_return(result, extra_info)
        else:
            return result

    def validate_and_return(self, result, extra_info):
        raise NotImplementedError

    def get_resource_info_links(self, search_results):
        raise NotImplementedError

    def initiate_resource(self, resource_link) -> 'self.resource_model':
        raise NotImplementedError

    def initiate_resources(self, search_results) -> List['resource_model']:
        raise NotImplementedError

    def remove_redundant_results(self, resources):
        raise NotImplementedError

    def create_or_update_resources(self, resources):
        raise NotImplementedError

    def make_request(self, url, headers=None, method="GET"):
        """
        Make an HTTP request using urllib3 with retry logic.

        Args:
            url (str): URL to request
            headers (dict, optional): HTTP headers
            method (str): HTTP method (GET, POST, etc.)

        Returns:
            urllib3.response.HTTPResponse: The response object
        """
        headers = headers or self.default_headers

        domain = urlparse(url).netloc
        self.sleep(domain=domain)

        try:
            return self.http.request(method, url, headers=headers)
        except MaxRetryError as e:
            logger.error(f"Max retries exceeded: {e}")
            return None

    def parse_json(self, content):
        """
        Parse JSON content.

        Args:
            content: JSON content to parse

        Returns:
            dict: Parsed JSON data or None if parsing fails
        """
        try:
            if isinstance(content, bytes):
                content = content.decode('utf-8')
            return json.loads(content)
        except json.JSONDecodeError:
            logger.warning("The content is not valid JSON.")
            return None

    def sleep(self, min_seconds=1, max_seconds=3, domain=None):
        """
        Sleep between requests to avoid overwhelming the target site.
        Only sleeps if necessary based on the time since the last sleep.
        Uses per-domain tracking when domain is provided.

        Args:
            min_seconds (float): Minimum seconds to wait
            max_seconds (float): Maximum seconds to wait
            domain (str, optional): The domain being accessed, for throttling
        """
        current_time = time.time()
        sleep_time = random.uniform(min_seconds, max_seconds)

        domain_key = domain if domain else self.default_domain
        last_sleep_time = self.last_sleep_by_domain.get(domain_key, 0)

        time_since_last_sleep = current_time - last_sleep_time
        domain_info = f" for {domain}" if domain else ""

        if time_since_last_sleep < sleep_time:
            actual_sleep_time = sleep_time - time_since_last_sleep
            logger.info(
                f"Time since last sleep{domain_info}: "
                f"{time_since_last_sleep:.2f}s, "
                f"sleeping for {actual_sleep_time:.2f}s"
            )
            time.sleep(actual_sleep_time)
        else:
            logger.info(
                f"No sleep needed{domain_info}. "
                f"Time since last sleep: {time_since_last_sleep:.2f}s "
                f"(required: {sleep_time:.2f}s)"
            )

        self.last_sleep_by_domain[domain_key] = time.time()

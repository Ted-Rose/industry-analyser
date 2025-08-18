import abc
import logging
import time
import random
import urllib3
import json
from urllib3.util.retry import Retry
from urllib3.exceptions import MaxRetryError

logger = logging.getLogger(__name__)


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
        self.config = config or {}

        retry_strategy = Retry(
            total=3,
            backoff_factor=30,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        self.http = urllib3.PoolManager(
            retries=retry_strategy,
            # cert_reqs='CERT_REQUIRED',
            # ca_certs=certifi.where()
        )

        self.default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.6446.75"
        }

        logger.debug(f"Initialized {self.__class__.__name__}")

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

        self.throttle()

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

    def throttle(self, min_seconds=1, max_seconds=3):
        """
        Throttle requests to avoid overwhelming the target site.

        Args:
            min_seconds (float): Minimum seconds to wait
            max_seconds (float): Maximum seconds to wait
        """
        sleep_time = random.uniform(min_seconds, max_seconds)
        logger.debug(f"Throttling for {sleep_time:.2f} seconds")
        time.sleep(sleep_time)

import os
import yaml
import logging
from bs4 import BeautifulSoup
from django.conf import settings
from core_scraper.base import BaseScraper

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger('blogs')


class BlogScraper(BaseScraper):
    """A scraper for fetching blog posts."""

    def __init__(self):
        """Initializes the scraper and loads its configuration."""
        super().__init__()
        self.config = self.load_config()
        self.enrich_search_results = True
        self.validate_result = True

    def load_config(self):
        """Loads the scraper's configuration from a YAML file."""
        config_path = os.path.join(
            settings.BASE_DIR, 'blogs', 'config.yaml'
        )
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)

    def get_search_urls(self):
        """Yields the blog listing URL from the configuration."""
        yield self.config['blog_listing_url']

    def format_results(self, search_results):
        """Parses the blog listing page to find links to individual posts."""
        html_content = search_results.data
        soup = BeautifulSoup(html_content, 'html.parser')

        # This is a placeholder selector. You will need to update it to match
        # the actual structure of the blog you are scraping.
        post_links = [
            a['href'] for a in soup.select('article .h2_wrap h2 a')
            if '#' not in a['href']
        ]

        logger.info(f"Found {len(post_links)} blog post links.")
        return post_links

    def remove_redundant_results(self, formatted_results):
        """Removes redundant results from the list of formatted results."""
        return formatted_results
  
    def get_resource_info_link(self, resource):
        info_link = self.config['base_url'] + resource
        return info_link
    
    def validate_and_return(self, result, extra_info):
        return result
import os
import json
import time
import yaml
import logging
from google import genai
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from google.api_core import exceptions
from django.conf import settings
from django.db.models import Count
from core_scraper.base import BaseScraper
from .models import Page, Theme, PageAnalysis

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
        self.excluded_resources = []
        self.total_themes_count = Theme.objects.count()

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
        if self.total_themes_count == 0:
            logger.info("No themes found in the database.\
                        Skipping redundancy check.")
            return formatted_results

        # Find pages that exist and have at least as many analyses as there are themes.
        # This is a more robust check than equality in case of data inconsistencies.
        fully_analyzed_pages = Page.objects.filter(
            url__in=formatted_results
        ).annotate(
            analysis_count=Count('pageanalysis')
        ).filter(
            analysis_count__gte=self.total_themes_count
        )

        # Get the URLs of the pages that are already fully analyzed.
        completed_urls = set(fully_analyzed_pages.values_list('url', flat=True))

        if completed_urls:
            logger.info(
                "Found %d fully analyzed pages. Removing them from the queue.",
                len(completed_urls)
            )
            # Filter out the completed URLs from the original list.
            new_results = [
                href for href in formatted_results if href not in completed_urls
            ]
            return new_results
        else:
            logger.info("No fully analyzed pages found. Processing all results.")
            return formatted_results

    def get_resource_info_link(self, resource):
        info_link = self.config['base_url'] + resource
        return info_link

    def validate_and_return(self, href, extra_info):
        # TODO: If 
        prompt_path = os.path.join(
            settings.BASE_DIR, 'blogs', 'prompts', 'romantic.txt'
        )
        with open(prompt_path, 'r') as file:
            prompt = file.read()

        article_content = self.format_extra_info(extra_info, href)
        full_prompt = prompt + article_content

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = None
        models = [
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
        retries_per_model = 3
        response_received = False

        try:
            for model_name in models:
                for attempt in range(retries_per_model):
                    try:
                        logger.info(
                            f"Attempting model {model_name} (Attempt {attempt + 1}/{retries_per_model})"
                        )
                        response = client.models.generate_content(
                            model=model_name,
                            contents=full_prompt,
                        )
                        logger.info(f"Success with model: {model_name}")
                        response_received = True
                        break  # Exit inner loop on success
                    except exceptions.ServerError as e:
                        logger.warning(
                            "Model %s failed on attempt %s. Retrying in %ss. Error: %s",
                            model_name, attempt + 1, 2 ** attempt, e
                        )
                        time.sleep(2 ** attempt)
                if response_received:
                    break  # Exit outer loop on success
        except Exception as e:
            logger.error("An unexpected error occurred with Gemini API: %s", e)
            return None

        if not response:
            logger.error(
                "Failed to get a response from Gemini API after %s retries.",
                max_retries
            )
            return None
        if response.prompt_feedback:
            logger.error(
                "Prompt probably blocked by Gemini API: %s",
                response.prompt_feedback
            )
            if response.prompt_feedback.block_reason:
                logger.error(
                    "Prompt blocked by Gemini API: %s",
                    response.prompt_feedback.block_reason
                )
            return None

        enriched_result = json.dumps({
            'title': response.text.strip(),
            'url': href,
            'content': article_content
        })

        return enriched_result

    def format_extra_info(self, extra_info, href):
        soup = BeautifulSoup(extra_info.data, 'html.parser')

        # Create a new soup to build the clean content
        clean_soup = BeautifulSoup('<div></div>', 'html.parser')
        container = clean_soup.div

        # Find the main article container to scope our search
        article_container = soup.find(
            'article', class_='open_article v2'
        )

        content = ''
        if article_container:
            # Extract the title, intro, and all gallery images
            title = article_container.find('h1')
            intro = article_container.find('div', class_='intro')
            gallery_images = article_container.find_all('div', class_='gallery_img')

            if title:
                container.append(title)
            if intro:
                container.append(intro)
            for img_div in gallery_images:
                container.append(img_div)

            # Clean up the extracted content
            for img in container.find_all('img'):
                if img.has_attr('data-src'):
                    img['src'] = img['data-src']
                if (img.has_attr('src') and
                        not img['src'].startswith('http')):
                    img['src'] = urljoin(
                        self.config['base_url'],
                        href,
                        img['src']
                    )
                attrs_to_remove = [
                    'data-src', 'class', 'onmouseover', 'onmouseout',
                    'style', 'itemprop', 'width', 'height'
                ]
                for attr in attrs_to_remove:
                    if img.has_attr(attr):
                        del img[attr]

            for a in container.find_all('a'):
                if (a.has_attr('href') and
                        not a['href'].startswith('http')):
                    a['href'] = urljoin(
                        self.config['base_url'],
                        href,
                        a['href']
                    )

            # Remove the comment count link
            comment_link = container.find('a', class_='com')
            if comment_link:
                comment_link.decompose()

            content = str(container)

        return content

    def create_resource(self, enriched_result):
        """Parses the enriched result from the API to create a resource dictionary."""
        try:
            page_data = json.loads(enriched_result)
            logger.info(f"Successfully parsed outer JSON: {page_data}")

            if 'title' not in page_data or 'url' not in page_data:
                logger.error("'title' or 'url' missing from API response.")
                return None

            # Clean and parse the nested JSON from the 'title' field
            title_json_str = page_data['title'].strip().replace('```json', '').replace('```', '')
            analysis_data = json.loads(title_json_str)

            # Extract the actual page title from the content HTML
            content_html = page_data.get('content', '')
            soup = BeautifulSoup(content_html, 'html.parser')
            page_title = soup.find('h1').get_text(strip=True) if soup.find('h1') else "No Title Found"

            # Create or get the page
            page, created = Page.objects.get_or_create(
                url=page_data['url'],
                defaults={'title': page_title}
            )

            # Dynamically find the theme key from the analysis data
            common_keys = {'confidence_score', 'reasoning_summary'}
            theme_key = next((key for key in analysis_data if key not in common_keys), None)

            if theme_key and analysis_data.get(theme_key) is True:
                try:
                    theme = Theme.objects.get(key_name=theme_key)
                    PageAnalysis.objects.update_or_create(
                        page=page,
                        theme=theme,
                        defaults={
                            'confidence_score': analysis_data.get('confidence_score'),
                            'reasoning_summary': analysis_data.get('reasoning_summary')
                        }
                    )
                    logger.info(
                        "Created analysis for page %s with theme %s",
                        page.id, theme.name
                    )
                except Theme.DoesNotExist:
                    logger.warning(
                        "Theme with key_name '%s' not found in database.",
                        theme_key
                    )
            return page
        except json.JSONDecodeError:
            logger.error(
                "Failed to decode JSON from API response: %s",
                enriched_result
            )
            return None


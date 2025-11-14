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
from core_scraper.base import BaseScraper
from .models import Post

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
        max_retries = 10

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model="gemini-2.5-pro",
                    contents=full_prompt,
                )
                logger.info(f"Gemini response: {response.text}")
                break  # Success, exit the loop
            except exceptions.ServiceUnavailable as e:
                logger.warning(
                    "Gemini API is unavailable, attempt %s of %s. "
                    "Retrying in %s seconds... Error: %s",
                    attempt + 1, max_retries, 2 ** attempt, e
                )
                time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(
                    "An unexpected error occurred with Gemini API: %s", e
                )
                return None

        if not response:
            logger.error(
                "Failed to get a response from Gemini API after %s retries.",
                max_retries
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

    def initiate_resource(self, enriched_result):
        """Parses the enriched result from the API to create a resource dictionary."""
        try:
            post_data = json.loads(enriched_result)
            logger.info(f"Successfully parsed outer JSON: {post_data}")

            if 'title' not in post_data or 'url' not in post_data:
                logger.error("'title' or 'url' missing from API response.")
                return None

            # Clean and parse the nested JSON from the 'title' field
            title_json_str = post_data['title'].strip().replace('```json', '').replace('```', '')
            title_data = json.loads(title_json_str)
            is_romantic = title_data.get('is_romantic_relationship_focused', False)
            logger.info(f"'is_romantic_relationship_focused' is set to: {is_romantic}")

            # Extract the actual post title from the content HTML
            content_html = post_data.get('content', '')
            soup = BeautifulSoup(content_html, 'html.parser')
            post_title = soup.find('h1').get_text(strip=True) if soup.find('h1') else "No Title Found"

            post = Post(
                title=post_title,
                url=post_data['url'],
                content=content_html
            )
            return post
        except json.JSONDecodeError:
            logger.error(
                f"Failed to decode JSON from API response: {enriched_result}"
            )
            return None


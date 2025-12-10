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
from django.db.models import Count, Q
from core_scraper.base import BaseScraper
from .models import Page, Theme, PageAnalysis

# Use the app name as the logger name to match settings configuration
logger = logging.getLogger('blogs')


class BlogScraper(BaseScraper):
    """A scraper for fetching blog posts."""

    def __init__(self, target_theme=None, reanalyze=False):
        """Initializes the scraper and loads its configuration."""
        super().__init__()
        self.config = self.load_config()
        self.enrich_search_results = True
        self.validate_result = False
        self.ai_analysis = True
        self.excluded_resources = []
        self.total_themes_count = Theme.objects.count()
        self.target_theme = target_theme
        self.reanalyze = reanalyze
        self.max_pages = self.config.get('max_pages', 1)

    def load_config(self):
        """Loads the scraper's configuration from a YAML file."""
        config_path = os.path.join(
            settings.BASE_DIR, 'blogs', 'config.yaml'
        )
        with open(config_path, 'r') as file:
            return yaml.safe_load(file)

    def get_search_urls(self):
        """
        Yields blog listing URLs, following pagination links.
        Supports both single URL (blog_listing_url) and multiple URLs
        (blog_listing_urls).
        Stops after max_pages per URL or when no next link is found.
        """
        listing_urls = self.config['blog_listing_urls']

        for listing_url in listing_urls:
            logger.info(
                f"Starting to scrape listing: {listing_url}"
            )
            current_url = listing_url
            pages_scraped = 0

            while current_url and pages_scraped < self.max_pages:
                logger.info(
                    f"Scraping page {pages_scraped + 1}/"
                    f"{self.max_pages}: {current_url}"
                )
                yield current_url

                # Fetch the page to find the next link
                response = self.make_request(current_url)
                if not response:
                    break

                next_url = self.extract_next_page_url(response)
                if not next_url:
                    logger.info(
                        f"No more pages for {listing_url}"
                    )
                    break

                current_url = next_url
                pages_scraped += 1

            if pages_scraped >= self.max_pages:
                logger.info(
                    f"Reached max pages limit ({self.max_pages}) "
                    f"for {listing_url}"
                )

    def extract_next_page_url(self, response):
        """
        Extracts the next pagination URL from the response.
        Looks for <link rel="next" href="..."> in the HTML.
        """
        soup = BeautifulSoup(response.data, 'html.parser')
        next_link = soup.find('link', rel='next')

        if next_link and next_link.get('href'):
            next_url = next_link['href']
            logger.info(f"Found next page: {next_url}")
            return next_url

        return None

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
            logger.info(
                "No themes found in the database. "
                "Skipping redundancy check."
            )
            return formatted_results

        # If analyzing a specific theme with reanalyze=False,
        # filter out pages that already have analysis for that theme
        if self.target_theme and not self.reanalyze:
            pages_with_theme_analysis = Page.objects.filter(
                url__in=formatted_results,
                pageanalysis__theme=self.target_theme
            )
            analyzed_urls = set(
                pages_with_theme_analysis.values_list('url', flat=True)
            )

            if analyzed_urls:
                logger.info(
                    "Found %d pages already analyzed for theme '%s'. "
                    "Removing them from the queue.",
                    len(analyzed_urls), self.target_theme.name
                )
                return [
                    href for href in formatted_results
                    if href not in analyzed_urls
                ]
            else:
                logger.info(
                    "No pages found with existing analysis for "
                    "theme '%s'.",
                    self.target_theme.name
                )
                return formatted_results

        # Original logic for analyzing all themes
        fully_analyzed_pages = Page.objects.filter(
            url__in=formatted_results
        ).annotate(
            analysis_count=Count('pageanalysis'),
            match_count=Count(
                'pageanalysis',
                filter=Q(pageanalysis__theme_match=True)
            )
        ).filter(
            Q(analysis_count__gte=self.total_themes_count) |
            Q(match_count__gt=0)
        )

        completed_urls = set(
            fully_analyzed_pages.values_list('url', flat=True)
        )

        if completed_urls:
            logger.info(
                "Found %d fully analyzed pages. "
                "Removing them from the queue.",
                len(completed_urls)
            )
            new_results = [
                href for href in formatted_results
                if href not in completed_urls
            ]
            return new_results
        else:
            logger.info(
                "No fully analyzed pages found. Processing all results."
            )
            return formatted_results

    def get_resource_info_link(self, resource):
        info_link = self.config['base_url'] + resource
        return info_link

    def extract_resource(self, href, extra_info):
        """
        Extracts and cleans the article content from the raw HTML.
        Also analyzes content characteristics (images, videos, text).
        """
        article_content = self.format_extra_info(extra_info, href)

        # Parse content for analysis
        soup = BeautifulSoup(article_content, 'html.parser')
        page_title = (
            soup.find('h1').get_text(strip=True)
            if soup.find('h1') else "No Title Found"
        )

        # Count images (exclude emotions/emojis)
        all_images = soup.find_all('img')
        image_count = len([
            img for img in all_images
            if img.get('alt') != 'emotion'
        ])

        # Count videos (direct tags and embeds)
        video_count = 0
        video_count += len(soup.find_all('video'))

        # YouTube embeds
        youtube_iframes = soup.find_all(
            'iframe',
            src=lambda x: x and 'youtube.com' in x
        )
        video_count += len(youtube_iframes)

        # Vimeo embeds
        vimeo_iframes = soup.find_all(
            'iframe',
            src=lambda x: x and 'vimeo.com' in x
        )
        video_count += len(vimeo_iframes)

        # Dailymotion embeds
        dailymotion_iframes = soup.find_all(
            'iframe',
            src=lambda x: x and 'dailymotion.com' in x
        )
        video_count += len(dailymotion_iframes)

        # Get text length (excluding script/style tags)
        soup_copy = BeautifulSoup(article_content, 'html.parser')
        for script in soup_copy(['script', 'style']):
            script.decompose()
        text_content = soup_copy.get_text(strip=True)
        text_length = len(text_content)

        # Check if video mentioned in text (for dynamic embeds)
        has_video_keyword = 'video' in text_content.lower()
        has_video = video_count > 0 or has_video_keyword

        return {
            'url': href,
            'title': page_title,
            'content': text_content,
            'has_video': has_video,
            'video_count': video_count,
            'image_count': image_count,
            'text_length': text_length,
        }

    def analyse_content(self, article_content, themes_to_analyse):
        """Calls the Gemini API to analyze content against a specific list of themes."""
        aggregated_results = {}

        for theme in themes_to_analyse:
            # 1. Load the prompt dynamically based on the theme's name
            try:
                prompt_path = os.path.join(
                    settings.BASE_DIR, 'blogs', 'prompts', f'{theme.name}.txt'
                )
                with open(prompt_path, 'r') as file:
                    prompt_instructions = file.read()
            except FileNotFoundError:
                logger.error("Prompt file not found for theme '%s' at %s", theme.name, prompt_path)
                continue  # Skip to the next theme

            full_prompt = prompt_instructions + "\n\n---\n\n" + article_content

            # 2. Make a separate API call for each theme
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            response = None
            models = [
                "gemini-2.5-pro",
                # Rest of the models provided unsatisfying results
                # "gemini-2.5-flash",
                # "gemini-2.5-flash-lite",
                # "gemini-2.0-flash",
                # "gemini-2.0-flash-lite",
                # "gemini-2.0-flash-exp"
            ]
            retries_per_model = 2
            response_received = False

            try:
                for model_name in models:
                    for attempt in range(retries_per_model):
                        try:
                            logger.info(
                                f"Attempting model {model_name} for theme '{theme.name}' (Attempt {attempt + 1})"
                            )
                            response = client.models.generate_content(
                                model=model_name,
                                contents=full_prompt,
                            )
                            if response.prompt_feedback and response.prompt_feedback.block_reason:
                                logger.warning(
                                    "Gemini API call blocked for theme '%s' with reason: %s",
                                    theme.name, response.prompt_feedback.block_reason
                                )
                                synthetic_analysis = {
                                    theme.name: True,
                                    'confidence_score': 1.0,
                                    'reasoning_summary': f"Content analysis blocked by API safety filters. Reason: {response.prompt_feedback.block_reason}",
                                    'model': model_name,
                                    'blocked': True,
                                }
                                aggregated_results[theme.name] = synthetic_analysis
                                return aggregated_results
                            else:
                                logger.info(f"Success with model: {model_name} for theme '{theme.name}'")
                                response_received = True
                                used_model = model_name  # Keep track of the successful model
                                break  # Exit inner loop on success
                        except Exception as e:
                            logger.warning(
                                "Model %s failed for theme '%s'. Retrying. Error: %s",
                                model_name, theme.name, e
                            )
                            time.sleep(2 ** attempt)
                    if response_received:
                        break  # Exit outer loop if we have a result (real or synthetic)
            except Exception as e:
                logger.error("An unexpected error occurred with Gemini API for theme '%s': %s", theme.name, e)
                time.sleep(2 ** attempt)
                continue  # Skip to the next theme

            if not response_received or not response:
                logger.error("Failed to get a valid response from Gemini API for theme '%s'.", theme.name)
                continue  # Skip to the next theme

            # 3. Aggregate the successful (non-blocked) results
            try:
                # Clean the response from the model to remove markdown formatting
                cleaned_json_str = response.text.strip().replace('```json', '').replace('```', '').strip()
                theme_analysis = json.loads(cleaned_json_str)
                theme_analysis['model'] = used_model  # Add the model info
                aggregated_results[theme.name] = theme_analysis
                # Return analysis if page matches the theme for
                # this content is not appropriate
                if theme_analysis[theme.name]:
                    return aggregated_results
            except json.JSONDecodeError:
                logger.error(
                    "Failed to decode JSON response for theme '%s': %s",
                    theme.name, response.text.strip()
                )

        # 4. Return the combined JSON for all successfully analyzed themes
        if not aggregated_results:
            logger.warning("No themes were successfully analyzed.")
            return None

        return aggregated_results

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

    def analyse_and_save_resource(self, http_response, url):
        """Analyzes a page against missing themes and saves the results."""
        page_data = self.extract_resource(url, http_response)

        # 1. Get or create the Page
        page, created = Page.objects.get_or_create(
            url=page_data['url'],
            defaults={'title': page_data.get('title', 'No Title Found')}
        )
        if created:
            logger.info("Created new page: %s", page.title)

        # 1.5 Update content characteristics
        page.has_video = page_data.get('has_video', False)
        page.video_count = page_data.get('video_count', 0)
        page.image_count = page_data.get('image_count', 0)
        page.text_length = page_data.get('text_length', 0)
        page.save()

        if page.is_media_heavy:
            logger.warning(
                "Page '%s' is media-heavy (video: %s, videos: %d, "
                "images: %d, text: %d chars). Skipping AI analysis.",
                page.title, page.has_video, page.video_count,
                page.image_count, page.text_length
            )
            # Skip AI analysis and mark as kid_unfriendly directly
            kid_unfriendly_theme = Theme.objects.get(
                name='kid_unfriendly'
            )
            PageAnalysis.objects.update_or_create(
                page=page,
                theme=kid_unfriendly_theme,
                defaults={
                    'confidence_score': 1.0,
                    'reasoning_summary': (
                        f"Media-heavy content detected: "
                        f"{'video present, ' if page.has_video else ''}"
                        f"{page.video_count} video(s), "
                        f"{page.image_count} images, "
                        f"{page.text_length} chars of text"
                    ),
                    'theme_match': True,
                    'model': 'content_analyzer'
                }
            )
            logger.info(
                "Marked page '%s' as kid_unfriendly due to "
                "media-heavy content",
                page.title
            )
            return page

        # 2. Determine which themes need analysis
        if self.target_theme:
            # Theme-specific mode
            if self.reanalyze:
                # Force re-analysis for this theme
                themes_to_analyse = [self.target_theme]
                logger.info(
                    "Re-analyzing page '%s' for theme '%s'",
                    page.title, self.target_theme.name
                )
            else:
                # Check if theme already analyzed
                already_analyzed = PageAnalysis.objects.filter(
                    page=page,
                    theme=self.target_theme
                ).exists()

                if already_analyzed:
                    logger.info(
                        "Page '%s' already analyzed for theme '%s'. "
                        "Skipping.",
                        page.title, self.target_theme.name
                    )
                    return page

                themes_to_analyse = [self.target_theme]
        else:
            # Original mode: analyze all missing themes
            all_themes = list(Theme.objects.all())
            analyzed_theme_ids = set(
                Theme.objects.filter(
                    pageanalysis__page=page
                ).values_list('id', flat=True)
            )
            # Filter out already analyzed themes, maintaining order
            themes_to_analyse = [
                theme for theme in all_themes
                if theme.id not in analyzed_theme_ids
            ]

        if not themes_to_analyse:
            logger.info(
                "Page '%s' is already fully analyzed. Skipping.",
                page.title
            )
            return page

        logger.info(
            "\nPage \n%s\nrequires analysis for themes: %s",
            page.title, [t.name for t in themes_to_analyse]
        )

        # 3. Call the AI for analysis on the missing themes
        analysis_json = self.analyse_content(
            page_data['content'], themes_to_analyse
        )
        if not analysis_json:
            logger.error("Analysis failed for page %s.", page.title)
            return None

        # 4. Save the new analysis results
        for theme_name, results in analysis_json.items():
            try:
                theme = Theme.objects.get(name=theme_name)
                PageAnalysis.objects.update_or_create(
                    page=page,
                    theme=theme,
                    defaults={
                        'confidence_score': results.get('confidence_score'),
                        'reasoning_summary': results.get('reasoning_summary'),
                        'theme_match': results.get(theme_name),
                        'model': results.get('model')
                    }
                )
            except Theme.DoesNotExist:
                logger.warning("Theme '%s' from analysis not found in DB.",
                               theme_name)
            except (TypeError, KeyError) as e:
                logger.error(
                  "Error processing analysis result for theme '%s': %s",
                  theme_name, e
                )

        return page

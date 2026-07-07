import time
from urllib.parse import urljoin, urlparse

import requests
import urllib3
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

from classified_ads.models import Region

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class Command(BaseCommand):
    help = 'Fetch regions from ss.com and sync to DB'

    def handle(self, *args, **options):
        all_regions = self._fetch_all_regions()
        self.stdout.write(f'Fetched {len(all_regions)} regions from ss.com')

        created = updated = 0
        for region_data in all_regions:
            parent_obj = None
            if region_data['parent_url']:
                parent_obj, _ = Region.objects.get_or_create(
                    url=region_data['parent_url'],
                    defaults={
                        'name': region_data['parent_name'],
                        'scrape_enabled': True,
                    },
                )

            region, is_created = Region.objects.get_or_create(
                url=region_data['url'],
                defaults={
                    'name': region_data['name'],
                    'parent': parent_obj,
                    'scrape_enabled': True,
                },
            )
            if not is_created:
                region.name = region_data['name']
                region.parent = parent_obj
                region.save(update_fields=['name', 'parent_id'])
                updated += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done: {created} created, {updated} updated'
        ))

    def _fetch_all_regions(self):
        base_url = 'https://www.ss.com/lv/real-estate/flats/'
        response = requests.get(base_url, timeout=10, verify=False)
        soup = BeautifulSoup(response.content, 'html.parser')

        all_regions = []
        top_level_links = soup.find_all('a', class_='a_category')

        for link in top_level_links:
            name = link.text.strip()
            relative_href = link.get('href', '')
            if not name or not relative_href or '/all/' in relative_href:
                continue

            full_url = urljoin('https://www.ss.com', relative_href)
            en_url = full_url.replace('/lv/', '/en/')

            time.sleep(0.3)
            sub_response = requests.get(full_url, timeout=10, verify=False)
            sub_soup = BeautifulSoup(sub_response.content, 'html.parser')
            sub_links = sub_soup.find_all('a', class_='a_category')

            if not sub_links:
                all_regions.append({
                    'name': name,
                    'url': en_url,
                    'parent_url': None,
                    'parent_name': None,
                })
            else:
                for sub_link in sub_links:
                    sub_relative_href = sub_link.get('href', '')
                    if not sub_relative_href or '/all/' in sub_relative_href:
                        continue

                    sub_name = self._extract_name(sub_link, sub_relative_href)
                    if not sub_name:
                        continue

                    sub_full_url = urljoin(
                        'https://www.ss.com', sub_relative_href
                    )
                    sub_en_url = sub_full_url.replace('/lv/', '/en/')

                    all_regions.append({
                        'name': sub_name,
                        'url': sub_en_url,
                        'parent_url': en_url,
                        'parent_name': name,
                    })

        return all_regions

    @staticmethod
    def _extract_name(link, href=''):
        """
        On ss.com sub-pages the <a class="a_category"> element is a visual
        arrow with no text; the region name sits in a sibling <b> or <td>.
        Falls back to deriving a name from the URL slug.
        """
        name = link.get_text(strip=True)
        if name:
            return name

        row = link.find_parent('tr')
        if row:
            b_tag = row.find('b')
            if b_tag:
                name = b_tag.get_text(strip=True)
                if name:
                    return name

            for td in row.find_all('td'):
                name = td.get_text(strip=True)
                if name:
                    return name

        if href:
            segments = [s for s in urlparse(href).path.split('/') if s]
            if segments:
                slug = segments[-1]
                return slug.replace('-', ' ').title()

        return ''

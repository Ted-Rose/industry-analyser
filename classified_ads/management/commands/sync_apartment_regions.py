import time
from urllib.parse import urljoin

import requests
import urllib3
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand

from classified_ads.models import Region

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_LV = '/lv/real-estate/flats/'


class Command(BaseCommand):
    help = 'Fetch apartment regions from ss.com and sync to DB'

    def handle(self, *args, **options):
        all_regions = self._fetch_all_regions()
        self.stdout.write(f'Fetched {len(all_regions)} regions from ss.com')

        top_level = [r for r in all_regions if not r['parent_url']]
        sub_regions = [r for r in all_regions if r['parent_url']]

        created = updated = 0
        parent_map = {}  # en_url -> Region instance

        for rd in top_level:
            region, is_created = Region.objects.get_or_create(
                url=rd['url'],
                defaults={'name': rd['name'], 'scrape_enabled': False},
            )
            if not is_created:
                region.name = rd['name']
                region.save(update_fields=['name'])
                updated += 1
            else:
                created += 1
            parent_map[rd['url']] = region

        for rd in sub_regions:
            parent = parent_map.get(rd['parent_url'])
            if parent is None:
                self.stderr.write(
                    f"No parent found for {rd['url']} — skipping"
                )
                continue

            region, is_created = Region.objects.get_or_create(
                url=rd['url'],
                defaults={
                    'name': rd['name'],
                    'parent': parent,
                    'scrape_enabled': True,
                },
            )
            if not is_created:
                region.name = rd['name']
                region.parent = parent
                region.save(update_fields=['name', 'parent_id'])
                updated += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done: {created} created, {updated} updated'
        ))

    def _fetch_all_regions(self):
        base_url = f'https://www.ss.com{BASE_LV}'
        response = requests.get(base_url, timeout=30, verify=False)
        soup = BeautifulSoup(response.content, 'html.parser')

        all_regions = []

        for link in self._find_direct_children(soup, BASE_LV):
            href = link.get('href', '')
            name = self._link_name(link, href)
            if not name:
                continue

            full_url = urljoin('https://www.ss.com', href)
            en_url = full_url.replace('/lv/', '/en/')

            # Always add the top-level region itself
            all_regions.append({
                'name': name,
                'url': en_url,
                'parent_url': None,
                'parent_name': None,
            })

            time.sleep(0.3)
            sub_resp = requests.get(full_url, timeout=30, verify=False)
            sub_soup = BeautifulSoup(sub_resp.content, 'html.parser')

            for sub_link in self._find_direct_children(sub_soup, href):
                sub_href = sub_link.get('href', '')
                sub_name = self._link_name(sub_link, sub_href)
                if not sub_name:
                    continue

                sub_full = urljoin('https://www.ss.com', sub_href)
                sub_en_url = sub_full.replace('/lv/', '/en/')

                all_regions.append({
                    'name': sub_name,
                    'url': sub_en_url,
                    'parent_url': en_url,
                    'parent_name': name,
                })

        return all_regions

    @staticmethod
    def _find_direct_children(soup, parent_path):
        """Return <a class="a_category"> tags linking exactly one path
        level below parent_path.

        ss.com region listings use class="a_category" for region links;
        other one-level-deep links on the same page (e.g. /search/,
        /new/) don't carry this class and must be excluded.
        """
        if not parent_path.endswith('/'):
            parent_path += '/'
        seen = set()
        results = []
        for a in soup.find_all('a', class_='a_category', href=True):
            href = a.get('href', '').split('?')[0].split('#')[0]
            if not href.startswith(parent_path):
                continue
            suffix = href[len(parent_path):].strip('/')
            if not suffix or '/' in suffix or suffix == 'all':
                continue
            if href in seen:
                continue
            seen.add(href)
            results.append(a)
        return results

    @staticmethod
    def _link_name(link, href=''):
        """Extract display name: title attr → link text → URL slug fallback."""
        title = link.get('title', '')
        if title:
            return title.split(',')[0].strip()
        name = link.get_text(strip=True)
        if name:
            return name
        if href:
            slug = href.rstrip('/').split('/')[-1]
            if slug:
                return slug.replace('-', ' ').title()
        return ''

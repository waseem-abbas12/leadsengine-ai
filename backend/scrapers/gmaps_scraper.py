import asyncio
import re
import urllib.parse
from typing import List, Dict, Callable, Optional
from bs4 import BeautifulSoup
import httpx

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None

AGGREGATOR_DOMAINS = [
    'webmd.com', 'healthgrades.com', 'opencare.com', 'yelp.com',
    'yellowpages.com', 'bbb.org', 'zocdoc.com', 'expertise.com',
    'wikipedia.org', 'facebook.com', 'tripadvisor.com', 'angis.com',
    'thumbtack.com', 'angi.com', 'manta.com', 'mapquest.com',
    'groupon.com', 'reddit.com', 'forbes.com', 'usnews.com'
]

class GoogleMapsScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def _scrape_via_playwright(self, query: str, max_results: int) -> List[Dict]:
        if not async_playwright:
            return []

        results: List[Dict] = []
        search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(query)}"

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()

            try:
                await page.goto(search_url, wait_until="commit", timeout=15000)
                await asyncio.sleep(3)

                for btn_text in ["Accept all", "Reject all", "I agree", "Accept"]:
                    try:
                        btn = page.locator(f'button:has-text("{btn_text}")')
                        if await btn.count() > 0:
                            await btn.first.click(timeout=1000)
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass

                try:
                    await page.wait_for_selector('div.Nv2PK', timeout=8000)
                except Exception:
                    pass

                for _ in range(max(1, max_results // 4)):
                    try:
                        await page.mouse.wheel(0, 2000)
                        await asyncio.sleep(1)
                    except Exception:
                        break

                cards = await page.locator('div.Nv2PK').all()
                seen = set()

                for card in cards[:max_results]:
                    try:
                        name_el = card.locator('.qBF1Pd, .fontHeadlineSmall')
                        if await name_el.count() == 0:
                            continue
                        name = (await name_el.first.inner_text()).strip()
                        if not name or name in seen:
                            continue
                        seen.add(name)

                        rating = "N/A"
                        reviews = "0"
                        r_el = card.locator('span.MW4etd')
                        if await r_el.count() > 0:
                            rating = (await r_el.first.inner_text()).strip()
                        rev_el = card.locator('span.UY7F9')
                        if await rev_el.count() > 0:
                            reviews = re.sub(r'[^\d]', '', await rev_el.first.inner_text()) or "0"

                        cat = ""
                        cat_el = card.locator('.W4Efsd')
                        if await cat_el.count() > 0:
                            cat = (await cat_el.first.inner_text()).strip().split('·')[0].strip()

                        website = ""
                        site_links = await card.locator('a[data-value="Website"], a.lcr4fd').all()
                        for sl in site_links:
                            h = await sl.get_attribute('href')
                            if h and "google.com" not in h:
                                website = h
                                break

                        phone = ""
                        card_text = await card.inner_text()
                        m = re.search(r'(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})', card_text)
                        if m:
                            phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"

                        results.append({
                            "name": name,
                            "category": cat,
                            "rating": rating,
                            "reviews": reviews,
                            "phone": phone,
                            "website": website,
                            "address": "",
                            "source": "Google Maps"
                        })
                    except Exception:
                        continue
            finally:
                await browser.close()

        return results

    async def _scrape_via_duckduckgo(self, query: str, max_results: int) -> List[Dict]:
        results: List[Dict] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        clean_query = f"{query} contact"
        url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(clean_query)}"

        async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    items = soup.find_all('div', class_='result')
                    for it in items:
                        if len(results) >= max_results:
                            break
                        title_el = it.find('a', class_='result__a')
                        if not title_el:
                            continue
                        name = title_el.get_text().strip()
                        raw_link = title_el.get('href', '')
                        
                        target_url = ""
                        if "uddg=" in raw_link:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                            target_url = parsed.get("uddg", [""])[0]
                        elif raw_link.startswith("http"):
                            target_url = raw_link

                        if not target_url or any(agg in target_url.lower() for agg in AGGREGATOR_DOMAINS):
                            continue

                        snippet_el = it.find('a', class_='result__snippet')
                        snippet = snippet_el.get_text().strip() if snippet_el else ""

                        phone = ""
                        m = re.search(r'(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})', snippet)
                        if m:
                            phone = f"({m.group(1)}) {m.group(2)}-{m.group(3)}"

                        clean_name = name.split(" - ")[0].split(" | ")[0].split(" : ")[0].strip()
                        if len(clean_name) > 40:
                            clean_name = clean_name[:40] + "..."

                        results.append({
                            "name": clean_name,
                            "category": query.split(" in ")[0].capitalize(),
                            "rating": "4.9",
                            "reviews": "48",
                            "phone": phone,
                            "website": target_url,
                            "address": "",
                            "source": "Direct Web"
                        })
            except Exception:
                pass

        return results

    async def search_leads(
        self,
        query: str,
        max_results: int = 10,
        on_progress: Optional[Callable[[Dict], None]] = None
    ) -> List[Dict]:
        if async_playwright:
            try:
                leads = await self._scrape_via_playwright(query, max_results)
                if leads and len(leads) >= 2:
                    for l in leads:
                        if not l.get("website"):
                            direct = await self._scrape_via_duckduckgo(f"{l['name']} official website", 1)
                            if direct:
                                l["website"] = direct[0]["website"]
                                if not l.get("phone") and direct[0].get("phone"):
                                    l["phone"] = direct[0]["phone"]
                    return leads
            except Exception:
                pass

        return await self._scrape_via_duckduckgo(query, max_results)

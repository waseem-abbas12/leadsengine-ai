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
    'groupon.com', 'reddit.com', 'forbes.com', 'usnews.com',
    'clutch.co', 'goodfirms.co', 'upcity.com', 'trustpilot.com',
    'capterra.com', 'g2.com', 'bark.com', 'houzz.com', 'homeadvisor.com',
    'zameen.com', 'olx.com.pk', 'olx.com', 'businesslist.pk', 'ebizpk.co',
    'starofservice.pk', 'starofservice.com', 'graana.com', 'pakwheels.com',
    'justdial.com', 'sulekha.com', 'indiamart.com', 'tradeindia.com',
    'yellowpages.com.pk', 'dialpakistan.com', 'pakistanbusinessdirectory.com',
    'checkatrade.com', 'gumtree.com', 'craigslist.org', 'crunchbase.com'
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

                feed_locator = page.locator('div[role="feed"]')
                scroll_attempts = min(35, max(4, max_results // 2))
                for _ in range(scroll_attempts):
                    current_cards = await page.locator('div.Nv2PK').all()
                    if len(current_cards) >= max_results:
                        break
                    if await feed_locator.count() > 0:
                        await feed_locator.first.evaluate('(el) => el.scrollTop = el.scrollHeight')
                    else:
                        await page.mouse.wheel(0, 3000)
                    await asyncio.sleep(1.0)

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
                        address = ""
                        w_elements = await card.locator('.W4Efsd').all()
                        for w in w_elements:
                            txt = (await w.inner_text()).strip()
                            if re.match(r'^\d+(\.\d+)?\([\d,]+\)$', txt):
                                continue
                            parts = [p.strip() for p in re.split(r'[·•\n]', txt) if p.strip()]
                            for p in parts:
                                if any(term in p for term in ['Opens', 'Closed', 'Open 24', 'AM', 'PM', 'hours', 'Appointment', 'In-store']):
                                    continue
                                if re.search(r'\d+\s+[A-Za-z]+', p):
                                    if not address:
                                        address = p
                                elif not cat and len(p) < 40 and not any(p.startswith(x) for x in ['+', '(', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9']):
                                    cat = p

                        if not cat:
                            cat = query.split(" in ")[0].strip().capitalize()

                        website = ""
                        site_links = await card.locator('a[data-value="Website"], a.lcr4fd, a[aria-label*="Website"], a[aria-label*="website"]').all()
                        for sl in site_links:
                            h = await sl.get_attribute('href')
                            if h and h.startswith("http") and "google.com" not in h and "/aclk" not in h:
                                website = h
                                break

                        phone = ""
                        card_text = await card.inner_text()
                        phone_patterns = [
                            r'(\+?92[-.\s]?[0-9]{3}[-.\s]?[0-9]{7})',            # +92 304 1111250
                            r'(03[0-9]{2}[-.\s]?[0-9]{7})',                      # 0301 6044097
                            r'(\+?1[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',  # US
                            r'(\+?44[-.\s]?[0-9]{2,4}[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4})', # UK
                            r'(\(?[0-9]{3,4}\)?[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4})'   # General
                        ]
                        for pat in phone_patterns:
                            pm = re.search(pat, card_text)
                            if pm:
                                cand = pm.group(1).strip()
                                if 8 <= len(re.sub(r'\D', '', cand)) <= 15:
                                    phone = cand
                                    break

                        results.append({
                            "name": name,
                            "category": cat,
                            "rating": rating,
                            "reviews": reviews,
                            "phone": phone,
                            "website": website,
                            "address": address,
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
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        clean_query = f"{query} contact"

        async with httpx.AsyncClient(headers=headers, timeout=10.0, follow_redirects=True) as client:
            try:
                try:
                    await client.get("https://duckduckgo.com/", timeout=4.0)
                except Exception:
                    pass

                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": clean_query})
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

                        url_lower = target_url.lower()
                        if not target_url or any(agg in url_lower for agg in AGGREGATOR_DOMAINS):
                            continue
                        if any(pat in url_lower for pat in ['/top-10', '/top10', '/top-5', '/best-', '/directory/', '/categories/', '/agents/', '/agent/', '/cate/', '/find/']):
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
                            "rating": "N/A",
                            "reviews": "0",
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
                        site = l.get("website", "")
                        if not site or "/aclk" in site or not site.startswith("http"):
                            try:
                                direct = await self._scrape_via_duckduckgo(f"{l['name']} official website", 1)
                                if direct and direct[0].get("website"):
                                    l["website"] = direct[0]["website"]
                                    if not l.get("phone") and direct[0].get("phone"):
                                        l["phone"] = direct[0]["phone"]
                            except Exception:
                                l["website"] = ""
                    return leads
            except Exception:
                pass

        return await self._scrape_via_duckduckgo(query, max_results)

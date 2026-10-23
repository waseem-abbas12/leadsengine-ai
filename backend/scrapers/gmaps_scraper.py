import asyncio
import re
import urllib.parse
from typing import List, Dict, Callable, Optional, Set
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
    'checkatrade.com', 'gumtree.com', 'craigslist.org', 'crunchbase.com',
    'semfirms.com', 'pakistanproperty.com', 'renews.pk', 'jaageer.com',
    'pakistanplaces.com', 'ilmkidunya.com', 'urdupoint.com', 'hamariweb.com',
    'parhlo.com', 'top10place.com', 'locate92.com', 'locale.online',
    'entireplace.com', 'bizdirpk.com', 'pakistanyp.com', 'tribune.com.pk',
    'dawn.com', 'thenews.com.pk', 'propakistani.pk', 'mustakbil.com', 'rozee.pk',
    'top-agencies.com', 'agencies.pk', 'pakrealestate.com', 'properties.pk',
    'apnafurniture.pk', 'bolnews.com', 'dunya.com.pk', 'dailypakistan.com.pk'
]

PAKISTAN_SUB_AREAS = {
    "faisalabad": [
        "D Ground", "Madina Town", "Peoples Colony", "Canal Road",
        "Kohinoor City", "Citi Housing", "Wapda City", "Gulberg",
        "Samanabad", "Jinnah Colony", "Susan Road", "Satiana Road", "FDA City"
    ],
    "lahore": [
        "DHA", "Gulberg", "Johar Town", "Bahria Town", "Model Town",
        "Cantt", "Faisal Town", "Wapda Town", "Mall Road"
    ],
    "karachi": [
        "DHA", "Clifton", "Gulshan-e-Iqbal", "PECHS", "North Nazimabad",
        "Bahria Town", "Korangi", "Saddar"
    ],
    "islamabad": [
        "F-6", "F-7", "F-8", "F-10", "F-11", "G-11", "Blue Area",
        "DHA", "Bahria Town", "E-11"
    ],
    "rawalpindi": [
        "Saddar", "Bahria Town", "Chaklala Scheme", "Peshawar Road", "Satellite Town"
    ]
}

NICHE_SYNONYMS = {
    "real estate": [
        "property dealer", "real estate agency", "property advisors",
        "real estate consultants", "property consultants", "commercial property"
    ],
    "property": [
        "real estate", "property dealer", "real estate agency", "property consultants"
    ],
    "dentist": ["dental clinic", "orthodontist", "dental hospital", "teeth clinic"],
    "doctor": ["clinic", "hospital", "specialist doctor", "medical center"],
    "lawyer": ["advocate", "law firm", "legal consultant", "attorney"],
    "software": ["software house", "IT company", "digital agency", "web development agency"],
    "car dealer": ["used cars", "car showroom", "auto dealer", "motors"],
    "restaurant": ["cafe", "fast food", "family restaurant", "hotel & restaurant"]
}

PHONE_PATTERNS = [
    r'(\+?92[-.\s]?[0-9]{3}[-.\s]?[0-9]{7})',            # +92 304 1111250
    r'(03[0-9]{2}[-.\s]?[0-9]{7})',                      # 0301 6044097
    r'(\+?1[-.\s]?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})',  # US
    r'(\+?44[-.\s]?[0-9]{2,4}[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4})', # UK
    r'(\(?[0-9]{3,4}\)?[-.\s]?[0-9]{3,4}[-.\s]?[0-9]{3,4})'   # General landline
]

def extract_clean_phone(txt: str) -> str:
    for pat in PHONE_PATTERNS:
        pm = re.search(pat, txt)
        if pm:
            cand = pm.group(1).strip()
            digits = re.sub(r'\D', '', cand)
            if 8 <= len(digits) <= 15:
                return cand
    return ""

from backend.scrapers.keyword_expander import generate_deep_industry_queries

def generate_expanded_queries(niche: str, location: str = "", max_queries: int = 50) -> List[str]:
    """
    Calls the comprehensive Industry Taxonomy & Sub-Area generator to produce all micro-keywords.
    """
    return generate_deep_industry_queries(niche=niche, location=location, max_queries=max_queries)


class GoogleMapsScraper:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def _scrape_multi_queries_playwright(
        self,
        queries: List[str],
        max_results: int,
        on_log: Optional[Callable[[str], None]] = None,
        on_lead: Optional[Callable[[Dict], None]] = None,
        stop_event: Optional[asyncio.Event] = None
    ) -> List[Dict]:
        if not async_playwright:
            return []

        all_results: List[Dict] = []
        seen_keys: Set[str] = set()

        if on_log:
            on_log(f"🚀 Initialized Playwright Chromium Engine across {len(queries)} search variations (Target: {max_results} leads)...")

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
                for q_idx, q in enumerate(queries, 1):
                    if len(all_results) >= max_results:
                        break
                    if stop_event and stop_event.is_set():
                        if on_log: on_log("🛑 Stop signal triggered by user.")
                        break

                    if on_log:
                        on_log(f"🔍 Query [{q_idx}/{len(queries)}]: '{q}' (Collected: {len(all_results)}/{max_results})")

                    search_url = f"https://www.google.com/maps/search/{urllib.parse.quote(q)}"
                    try:
                        await page.goto(search_url, wait_until="commit", timeout=18000)
                        await asyncio.sleep(1.8)

                        # Handle consent buttons once
                        if q_idx == 1:
                            for btn_text in ["Accept all", "Reject all", "I agree", "Accept"]:
                                try:
                                    btn = page.locator(f'button:has-text("{btn_text}")')
                                    if await btn.count() > 0:
                                        await btn.first.click(timeout=1000)
                                        await asyncio.sleep(0.8)
                                        break
                                except Exception:
                                    pass

                        try:
                            await page.wait_for_selector('div.Nv2PK', timeout=7000)
                        except Exception:
                            continue

                        # Continuous feed scrolling
                        feed_locator = page.locator('div[role="feed"]')
                        needed = max_results - len(all_results)
                        scroll_count = min(15, max(3, needed // 3))
                        
                        for _ in range(scroll_count):
                            cards_check = await page.locator('div.Nv2PK').all()
                            if len(cards_check) >= needed + 5:
                                break
                            if await feed_locator.count() > 0:
                                await feed_locator.first.evaluate('(el) => el.scrollTop = el.scrollHeight')
                            else:
                                await page.mouse.wheel(0, 3000)
                            await asyncio.sleep(0.9)

                        cards = await page.locator('div.Nv2PK').all()

                        for card in cards:
                            if len(all_results) >= max_results:
                                break

                            try:
                                name_el = card.locator('.qBF1Pd, .fontHeadlineSmall')
                                if await name_el.count() == 0:
                                    continue
                                name = (await name_el.first.inner_text()).strip()
                                if not name:
                                    continue

                                card_text = await card.inner_text()
                                phone = extract_clean_phone(card_text)

                                # Strong Deduplication Key (Phone or Name)
                                norm_phone = re.sub(r'\D', '', phone) if phone else ""
                                key = f"{name.lower()}::{norm_phone}" if norm_phone else name.lower()
                                if key in seen_keys:
                                    continue
                                seen_keys.add(key)

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
                                    cat = q.split(" in ")[0].strip().capitalize()

                                website = ""
                                site_links = await card.locator('a[data-value="Website"], a.lcr4fd, a[aria-label*="Website"], a[aria-label*="website"]').all()
                                for sl in site_links:
                                    h = await sl.get_attribute('href')
                                    if h and h.startswith("http") and "google.com" not in h and "/aclk" not in h:
                                        website = h
                                        break

                                item_dict = {
                                    "name": name,
                                    "category": cat,
                                    "rating": rating,
                                    "reviews": reviews,
                                    "phone": phone,
                                    "website": website,
                                    "address": address,
                                    "source": "Google Maps",
                                    "matched_query": q
                                }
                                all_results.append(item_dict)
                                if on_lead:
                                    try:
                                        on_lead(item_dict)
                                    except Exception:
                                        pass
                                if on_log:
                                    phone_display = f"📞 {phone}" if phone else "No Phone"
                                    on_log(f"[{len(all_results)}/{max_results}] Found: {name[:32]} | {phone_display}")
                            except Exception:
                                continue

                    except Exception:
                        continue

            finally:
                await browser.close()

        return all_results

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

                        phone = extract_clean_phone(snippet)
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
        max_results: int = 50,
        use_variations: bool = True,
        on_log: Optional[Callable[[str], None]] = None,
        on_lead: Optional[Callable[[Dict], None]] = None,
        stop_event: Optional[asyncio.Event] = None
    ) -> List[Dict]:
        """
        Main Search Gateway:
        If use_variations=True or max_results > 15, generates 10-20 keyword & sub-area variations,
        runs continuous loop with live deduplication, accumulating up to max_results (50, 100, 250, 400+ leads).
        """
        # Parse niche and location
        parts = query.split(" in ")
        niche = parts[0].strip()
        location = parts[1].strip() if len(parts) > 1 else ""

        if use_variations:
            queries = generate_expanded_queries(niche, location, max_queries=min(25, max(4, max_results // 10)))
        else:
            queries = [query]

        if async_playwright:
            try:
                leads = await self._scrape_multi_queries_playwright(
                    queries,
                    max_results,
                    on_log=on_log,
                    on_lead=on_lead,
                    stop_event=stop_event
                )
                if leads and len(leads) >= 1:
                    return leads
            except Exception as e:
                if on_log: on_log(f"⚠️ Playwright run notice: {str(e)}")

        # Fallback if Playwright not available
        all_fallback: List[Dict] = []
        seen = set()
        for q in queries[:5]:
            sub_res = await self._scrape_via_duckduckgo(q, max_results // 2)
            for item in sub_res:
                k = item["name"].lower()
                if k not in seen:
                    seen.add(k)
                    all_fallback.append(item)
                    if len(all_fallback) >= max_results:
                        break
            if len(all_fallback) >= max_results:
                break

        return all_fallback

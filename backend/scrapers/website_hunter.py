import asyncio
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from typing import Dict, Set, Optional, List

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None

import httpx

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+')
PHONE_REGEX = re.compile(r'(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})')
OWNER_REGEX = re.compile(r'(?:founder|ceo|owner|director|president|dr\.|doctor)\s*[:\-–]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})', re.IGNORECASE)

IGNORE_EMAIL_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.pdf', '.css', '.js'}
IGNORE_DOMAINS = {'sentry.io', 'wixpress.com', 'schema.org', 'google.com', 'facebook.com', 'cloudflare.com', 'gravatar.com'}

class WebsiteHunter:
    def __init__(self, timeout: float = 8.0, max_pages_per_site: int = 3):
        self.timeout = timeout
        self.max_pages = max_pages_per_site
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }

    def clean_emails(self, text: str) -> Set[str]:
        raw_emails = EMAIL_REGEX.findall(text)
        cleaned = set()
        for e in raw_emails:
            e_lower = e.lower()
            if any(e_lower.endswith(ext) for ext in IGNORE_EMAIL_EXTS):
                continue
            domain = e_lower.split('@')[-1]
            if domain in IGNORE_DOMAINS:
                continue
            if len(e_lower) > 6:
                cleaned.add(e_lower)
        return cleaned

    def extract_socials(self, soup: BeautifulSoup) -> Dict[str, str]:
        socials = {"linkedin": "", "instagram": "", "facebook": "", "twitter": ""}
        for a in soup.find_all('a', href=True):
            href = a['href'].lower()
            if "linkedin.com/company" in href or "linkedin.com/in" in href:
                if not socials["linkedin"]: socials["linkedin"] = a['href']
            elif "instagram.com/" in href and not any(x in href for x in ['/p/', '/explore/']):
                if not socials["instagram"]: socials["instagram"] = a['href']
            elif "facebook.com/" in href and not any(x in href for x in ['sharer', 'dialog', '/photo']):
                if not socials["facebook"]: socials["facebook"] = a['href']
            elif "twitter.com/" in href or "x.com/" in href:
                if not socials["twitter"]: socials["twitter"] = a['href']
        return socials

    def extract_founder(self, text: str) -> Optional[str]:
        m = OWNER_REGEX.search(text)
        if m:
            name = m.group(1).strip()
            if len(name.split()) in [2, 3] and not any(w in name.lower() for w in ['about', 'privacy', 'terms', 'contact', 'home']):
                return name
        return None

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> Optional[str]:
        try:
            resp = await client.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.text
        except Exception:
            pass
        return None

    async def crawl_site(self, website_url: str, client: Optional[httpx.AsyncClient] = None) -> Dict:
        result = {
            "website": website_url,
            "emails": [],
            "primary_email": "",
            "phones": [],
            "socials": {"linkedin": "", "instagram": "", "facebook": "", "twitter": ""},
            "founder_name": "",
            "title": "",
            "description": ""
        }

        if not website_url or "/aclk" in website_url or "google.com" in website_url:
            return result

        if not website_url.startswith("http"):
            website_url = "https://" + website_url

        try:
            parsed = urlparse(website_url)
            if not parsed.netloc or "." not in parsed.netloc:
                return result
            base_domain = f"{parsed.scheme}://{parsed.netloc}"
        except Exception:
            return result

        pages_to_visit = [website_url, urljoin(base_domain, "/contact"), urljoin(base_domain, "/about")]
        pages_to_visit = pages_to_visit[:self.max_pages]

        all_emails: Set[str] = set()
        all_phones: Set[str] = set()

        close_client = False
        if client is None:
            client = httpx.AsyncClient(
                headers=self.headers,
                follow_redirects=True,
                verify=False,
                timeout=self.timeout
            )
            close_client = True

        try:
            fetch_tasks = [self._fetch_page(client, u) for u in pages_to_visit]
            responses = await asyncio.gather(*fetch_tasks, return_exceptions=True)

            for html_text in responses:
                if not html_text or not isinstance(html_text, str):
                    continue

                soup = BeautifulSoup(html_text, 'html.parser')
                page_text = soup.get_text(separator=' ')

                if not result["title"] and soup.title and soup.title.string:
                    result["title"] = soup.title.string.strip()

                # 1. Mailto links
                for mailto in soup.select('a[href^="mailto:"]'):
                    href = mailto.get('href', '').replace('mailto:', '').split('?')[0].strip()
                    if href:
                        all_emails.add(href.lower())

                # 2. Text emails regex
                all_emails.update(self.clean_emails(page_text))

                # 3. Tel: links
                for tel in soup.select('a[href^="tel:"]'):
                    raw_tel = tel.get('href', '').replace('tel:', '').strip()
                    digits = re.sub(r'[^\d]', '', raw_tel)
                    if len(digits) == 10:
                        all_phones.add(f"({digits[:3]}) {digits[3:6]}-{digits[6:]}")
                    elif len(digits) == 11 and digits.startswith('1'):
                        all_phones.add(f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}")

                # 4. Text phone regex
                phones = PHONE_REGEX.findall(page_text)
                for p in phones:
                    all_phones.add(f"({p[0]}) {p[1]}-{p[2]}")

                # 5. Socials
                soc = self.extract_socials(soup)
                for k, v in soc.items():
                    if v and not result["socials"][k]:
                        result["socials"][k] = v

                # 6. Founder name
                if not result["founder_name"]:
                    f_name = self.extract_founder(page_text)
                    if f_name:
                        result["founder_name"] = f_name

        finally:
            if close_client:
                await client.aclose()

        result["emails"] = list(all_emails)
        if result["emails"]:
            def email_rank(em):
                if any(x in em for x in ['contact', 'info', 'hello', 'sales', 'support', 'office']):
                    return 0
                return 1
            sorted_emails = sorted(result["emails"], key=email_rank)
            result["primary_email"] = sorted_emails[0]

        result["phones"] = list(all_phones)[:2]
        return result

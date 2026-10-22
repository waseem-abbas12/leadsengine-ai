import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from typing import Dict, Set, Optional

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
    def __init__(self, timeout: int = 10, max_pages_per_site: int = 3):
        self.timeout = timeout
        self.max_pages = max_pages_per_site

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

    def _fetch_page(self, url: str) -> Optional[str]:
        if curl_requests:
            try:
                r = curl_requests.get(url, impersonate="chrome120", timeout=self.timeout, verify=False)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
        
        # Standard HTTPX fallback (runs anywhere on Vercel)
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            with httpx.Client(headers=headers, timeout=float(self.timeout), follow_redirects=True, verify=False) as client:
                resp = client.get(url)
                if resp.status_code == 200:
                    return resp.text
        except Exception:
            pass
        return None

    async def crawl_site(self, website_url: str) -> Dict:
        if not website_url.startswith("http"):
            website_url = "https://" + website_url

        parsed = urlparse(website_url)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"

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

        pages_to_visit = [website_url, urljoin(base_domain, "/contact"), urljoin(base_domain, "/about")]
        all_emails: Set[str] = set()
        all_phones: Set[str] = set()

        for u in pages_to_visit[:self.max_pages]:
            html_text = self._fetch_page(u)
            if not html_text:
                continue

            soup = BeautifulSoup(html_text, 'html.parser')
            page_text = soup.get_text(separator=' ')

            if not result["title"] and soup.title and soup.title.string:
                result["title"] = soup.title.string.strip()

            for mailto in soup.select('a[href^="mailto:"]'):
                href = mailto.get('href', '').replace('mailto:', '').split('?')[0].strip()
                if href:
                    all_emails.add(href.lower())

            all_emails.update(self.clean_emails(page_text))

            phones = PHONE_REGEX.findall(page_text)
            for p in phones:
                all_phones.add(f"({p[0]}) {p[1]}-{p[2]}")

            soc = self.extract_socials(soup)
            for k, v in soc.items():
                if v and not result["socials"][k]:
                    result["socials"][k] = v

            if not result["founder_name"]:
                f_name = self.extract_founder(page_text)
                if f_name:
                    result["founder_name"] = f_name

            if all_emails:
                break

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

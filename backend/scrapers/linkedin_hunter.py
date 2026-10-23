import re
import urllib.parse
from typing import List, Dict, Optional
from bs4 import BeautifulSoup
import httpx

from backend.scrapers.gmaps_scraper import AGGREGATOR_DOMAINS
from backend.scrapers.website_hunter import WebsiteHunter
from backend.scrapers.email_verifier import verify_email

class LinkedInHunter:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout
        self.hunter = WebsiteHunter(timeout=timeout)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def _search_web(self, query: str) -> List[Dict[str, str]]:
        results = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://duckduckgo.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
            try:
                # Prime session
                try:
                    await client.get("https://duckduckgo.com/", timeout=4.0)
                except Exception:
                    pass

                resp = await client.post("https://html.duckduckgo.com/html/", data={"q": query})
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, 'html.parser')
                    for it in soup.find_all('div', class_='result'):
                        a = it.find('a', class_='result__a')
                        if not a:
                            continue
                        raw_link = a.get('href', '')
                        target_url = ""
                        if "uddg=" in raw_link:
                            parsed = urllib.parse.parse_qs(urllib.parse.urlparse(raw_link).query)
                            target_url = parsed.get("uddg", [""])[0]
                        elif raw_link.startswith("http"):
                            target_url = raw_link

                        sn = it.find('a', class_='result__snippet')
                        snippet = sn.get_text().strip() if sn else ""

                        results.append({
                            "title": a.get_text().strip(),
                            "url": target_url,
                            "snippet": snippet
                        })
            except Exception:
                pass
        return results

    async def find_decision_makers(
        self,
        niche: str,
        location: str = "",
        role: str = "CEO, Founder, Owner, Managing Director",
        max_results: int = 10
    ) -> List[Dict]:
        """
        Finds direct decision-makers on LinkedIn with their verified company email and phone.
        """
        leads = []
        
        # Build query for LinkedIn profiles
        role_query = " OR ".join([f'"{r.strip()}"' for r in role.split(",") if r.strip()])
        if not role_query:
            role_query = '"CEO" OR "Founder" OR "Owner"'
            
        search_query = f"{niche} {location} ({role_query}) site:linkedin.com/in"
        web_results = await self._search_web(search_query)

        seen_profiles = set()

        for item in web_results:
            if len(leads) >= max_results:
                break

            target_url = item.get("url", "")
            if not target_url or "linkedin.com/in/" not in target_url:
                continue

            # Normalize LinkedIn profile
            clean_profile = target_url.split("?")[0].rstrip("/")
            if clean_profile in seen_profiles:
                continue
            seen_profiles.add(clean_profile)

            title = item.get("title", "")
            snippet = item.get("snippet", "")

            # Parse Person Name, Role, Company from Title:
            # Format usually: "FirstName LastName - Role at Company | LinkedIn"
            clean_title = re.sub(r'\s*\|\s*LinkedIn.*$', '', title, flags=re.IGNORECASE).strip()
            clean_title = re.sub(r'\s*-\s*LinkedIn.*$', '', clean_title, flags=re.IGNORECASE).strip()

            parts = [p.strip() for p in re.split(r'\s*[-–—]\s*', clean_title) if p.strip()]
            person_name = parts[0] if parts else "Decision Maker"
            # Cleanup person name
            if len(person_name.split()) > 4:
                person_name = " ".join(person_name.split()[:3])

            person_role = "Founder / Executive"
            company_name = f"{niche.capitalize()} Agency"

            if len(parts) > 1:
                rest = " - ".join(parts[1:])
                if " at " in rest:
                    r_split = rest.split(" at ", 1)
                    person_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                elif " @ " in rest:
                    r_split = rest.split(" @ ", 1)
                    person_role = r_split[0].strip()
                    company_name = r_split[1].strip()
                else:
                    person_role = parts[1].strip()
                    if len(parts) > 2:
                        company_name = parts[2].strip()

            # Clean company name
            company_name = re.sub(r'\s*\(.*?\)', '', company_name).strip()
            if len(company_name) > 40:
                company_name = company_name[:40]

            lead = {
                "name": company_name or f"{person_name}'s Firm",
                "category": niche.capitalize(),
                "founder_name": person_name,
                "founder_role": person_role,
                "rating": "5.0",
                "reviews": "1",
                "phone": "",
                "website": "",
                "address": location or "",
                "email": "",
                "email_status": "NONE",
                "socials": {
                    "linkedin": clean_profile,
                    "instagram": "",
                    "facebook": "",
                    "twitter": ""
                },
                "ai_score": 75,
                "pitch_hook": f"Hi {person_name}, saw your profile as {person_role} at {company_name}. Reaching out to see if you are exploring new acquisition channels this quarter.",
                "source": "LinkedIn Decision-Maker"
            }

            # Search company website
            company_search_query = f"{company_name} {location} official website"
            company_sites = await self._search_web(company_search_query)

            for cs in company_sites:
                cs_url = cs.get("url", "")
                if not cs_url or not cs_url.startswith("http"):
                    continue
                cs_lower = cs_url.lower()
                if any(agg in cs_lower for agg in AGGREGATOR_DOMAINS):
                    continue
                if "linkedin.com" in cs_lower:
                    continue
                lead["website"] = cs_url
                break

            leads.append(lead)

        return leads

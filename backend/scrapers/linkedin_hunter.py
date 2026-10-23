import re
import random
import urllib.parse
from typing import List, Dict, Optional, Any
from bs4 import BeautifulSoup
import httpx

from backend.scrapers.gmaps_scraper import AGGREGATOR_DOMAINS
from backend.scrapers.website_hunter import WebsiteHunter
from backend.scrapers.email_verifier import (
    LeadEnricher,
    SmtpVerifier,
    discover_and_verify_corporate_email,
    verify_email
)

class DorkQueryBuilder:
    """
    Replicates LinkedIn Sales Navigator's deep query engine into 
    Boolean Google/DuckDuckGo X-Ray queries targeting indexed profile cards.
    """
    SENIORITY_PRESETS = {
        "c_level": '("CEO" OR "Chief Executive Officer" OR "CTO" OR "COO" OR "CFO" OR "CMO" OR "CRO" OR "Chief")',
        "founder": '("Founder" OR "Co-Founder" OR "Co Founder" OR "Owner" OR "Partner" OR "President")',
        "vp": '("VP" OR "Vice President" OR "SVP" OR "EVP")',
        "director": '("Director" OR "Head of" OR "Managing Director")',
        "manager": '("Manager" OR "Lead" OR "Principal")',
    }

    @classmethod
    def build(
        cls,
        niche: str,
        location: Optional[str] = None,
        role: Optional[str] = None,
        seniority: Optional[str] = None,
    ) -> str:
        parts = ['site:linkedin.com/in/']
        
        # Exclude directories
        parts.append('-intitle:"profiles" -inurl:"dir/" -inurl:"pub/dir"')

        if niche and niche.strip():
            parts.append(f'"{niche.strip()}"')

        if location and location.strip():
            locs = [f'"{l.strip()}"' for l in location.split(",") if l.strip()]
            if locs:
                parts.append(f"({' OR '.join(locs)})")

        title_clauses = []
        if seniority and seniority in cls.SENIORITY_PRESETS:
            title_clauses.append(cls.SENIORITY_PRESETS[seniority])

        if role and role.strip():
            raw_titles = [t.strip() for t in role.split(",") if t.strip()]
            if raw_titles:
                formatted = [f'"{t}"' for t in raw_titles]
                title_clauses.append(" OR ".join(formatted))

        if not title_clauses:
            title_clauses.append('("CEO" OR "Founder" OR "Owner" OR "Managing Director")')

        parts.append(f"({' OR '.join(title_clauses)})")
        return " ".join(parts)


class LinkedInHunter:
    def __init__(self, timeout: float = 12.0):
        self.timeout = timeout
        self.hunter = WebsiteHunter(timeout=timeout)
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
        ]

    @staticmethod
    def parse_linkedin_title(raw_title: str) -> tuple[str, str, str]:
        """
        Parses title formats:
        - John Doe - Founder & CEO - Acme Corp | LinkedIn
        - Jane Smith – VP of Sales – Stripe | LinkedIn
        - Alice Cooper - Software Engineer at OpenAI | LinkedIn
        """
        cleaned = re.sub(r"(?i)\s*[-–|]\s*linkedin.*$", "", raw_title.strip())
        parts = [p.strip() for p in re.split(r"[-–|]", cleaned) if p.strip()]

        full_name = parts[0] if parts else "Executive Lead"
        job_title = ""
        company = ""

        if len(parts) >= 3:
            job_title = parts[1]
            company = parts[2]
        elif len(parts) == 2:
            second_part = parts[1]
            if " at " in second_part:
                jt, comp = second_part.split(" at ", 1)
                job_title = jt.strip()
                company = comp.strip()
            elif " @ " in second_part:
                jt, comp = second_part.split(" @ ", 1)
                job_title = jt.strip()
                company = comp.strip()
            else:
                job_title = second_part
        elif " at " in full_name:
            fn, rest = full_name.split(" at ", 1)
            full_name = fn.strip()
            company = rest.strip()

        # Sanitize name if contaminated with title/slug
        name_words = full_name.split()
        if len(name_words) > 4:
            full_name = " ".join(name_words[:3])

        return full_name, job_title or "Executive / Founder", company

    async def _search_web(self, query: str) -> List[Dict[str, str]]:
        results = []
        headers = {
            "User-Agent": random.choice(self.user_agents),
            "Referer": "https://duckduckgo.com/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout, follow_redirects=True) as client:
            try:
                # Prime session
                try:
                    await client.get("https://duckduckgo.com/", timeout=3.0)
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
        seniority: Optional[str] = None,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Deep discovery engine:
        1. Google/DDG X-Ray query targeting executive LinkedIn profiles.
        2. Parses executive names & roles.
        3. Identifies corporate website & domain.
        4. Apollo-style Email Permutation Matrix & DNS MX provider lookup.
        5. Live SMTP Mailbox check with Catch-All detection.
        """
        leads = []
        
        # Build search query
        clean_role = role if role else "CEO, Founder, Owner"
        search_query = f"{niche} {location} ({clean_role}) site:linkedin.com/in"
        web_results = await self._search_web(search_query)

        seen_profiles = set()

        for item in web_results:
            if len(leads) >= max_results:
                break

            target_url = item.get("url", "")
            if not target_url or "linkedin.com/in/" not in target_url:
                continue

            clean_profile = target_url.split("?")[0].rstrip("/")
            if clean_profile in seen_profiles:
                continue
            seen_profiles.add(clean_profile)

            title = item.get("title", "")
            snippet = item.get("snippet", "")

            person_name, person_role, company_name = self.parse_linkedin_title(title)
            if not company_name:
                company_name = f"{niche.capitalize()} Agency"

            lead = {
                "name": company_name,
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
                "mx_provider": "",
                "email_permutations": [],
                "socials": {
                    "linkedin": clean_profile,
                    "instagram": "",
                    "facebook": "",
                    "twitter": ""
                },
                "ai_score": 80,
                "pitch_hook": f"Hi {person_name}, saw your profile as {person_role} at {company_name}. Reaching out to see if you are exploring new client acquisition channels this quarter.",
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

            # If website discovered, perform corporate email permutations & DNS MX lookup!
            if lead["website"]:
                domain = LeadEnricher.clean_domain(lead["website"])
                try:
                    enrich_data = await discover_and_verify_corporate_email(person_name, domain)
                    if enrich_data.get("email"):
                        lead["email"] = enrich_data["email"]
                        lead["email_status"] = enrich_data["email_status"]
                        lead["mx_provider"] = enrich_data.get("provider", "")
                        lead["email_permutations"] = enrich_data.get("permutations", [])
                except Exception:
                    pass

            leads.append(lead)

        return leads

import os
import re
import json
from typing import Dict, Any

class AIEnricher:
    def __init__(self, gemini_api_key: str = ""):
        self.api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.client = None
        if self.api_key:
            try:
                import google.generativeai as genai
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel('gemini-1.5-flash')
            except Exception:
                self.client = None

    async def parse_prompt(self, user_prompt: str) -> Dict[str, Any]:
        """
        Translates a natural language user prompt into structured search parameters.
        """
        user_prompt = user_prompt.strip()
        
        # If Gemini is available, use LLM
        if self.client:
            try:
                sys_inst = (
                    "Extract search parameters from this sales lead generation prompt. "
                    "Return ONLY JSON with keys: query (string for Google search), "
                    "niche (string), location (string), service_to_pitch (string)."
                )
                resp = await self.client.generate_content_async(f"{sys_inst}\n\nPrompt: {user_prompt}")
                text = resp.text.replace('```json', '').replace('```', '').strip()
                return json.loads(text)
            except Exception:
                pass

        # Robust Heuristic Fallback (100% Free, No API required)
        # Match "in <city/state/country>"
        loc_match = re.search(r'\bin\s+([A-Za-z\s,]+?)(?:\s+who|\s+that|\s+with|\s+needing|$)', user_prompt, re.IGNORECASE)
        location = loc_match.group(1).strip() if loc_match else "United States"

        # Match niche before "in"
        niche_match = re.search(r'^(?:find\s+|get\s+|search\s+)?(.*?)(?:\s+in\s+|$)', user_prompt, re.IGNORECASE)
        niche = niche_match.group(1).strip() if niche_match else user_prompt

        search_query = f"{niche} in {location}".strip()

        return {
            "query": search_query,
            "niche": niche,
            "location": location,
            "service_to_pitch": "Client Acquisition & Automation"
        }

    def score_lead(self, lead: Dict) -> int:
        """
        Calculates Lead Quality Score from 0 to 100.
        """
        score = 20 # base score for being found
        if lead.get("website"):
            score += 20
        if lead.get("email"):
            if lead.get("email_status") in ["VERIFIED", "VERIFIED_MX"]:
                score += 30
            else:
                score += 15
        if lead.get("phone"):
            score += 15
        socials = lead.get("socials", {})
        if any(socials.values()):
            score += 15

        return min(100, score)

    def generate_pitch_hook(self, lead: Dict, service_to_pitch: str = "") -> str:
        """
        Generates a 1-to-2 sentence personalized cold email hook.
        """
        name = lead.get("founder_name") or "there"
        company = lead.get("name") or "your company"
        reviews = lead.get("reviews", "0")
        rating = lead.get("rating", "N/A")
        
        if int(reviews) if reviews.isdigit() else 0 > 20:
            hook = f"Hi {name}, saw {company} has an impressive {rating} star rating ({reviews} reviews). Reaching out because businesses at your level usually look to scale client acquisition without adding more manual follow-ups."
        elif lead.get("website"):
            hook = f"Hi {name}, was just checking out {company}'s website and noticed a few quick opportunities to plug revenue leaks and book more appointments directly from your traffic."
        else:
            hook = f"Hi {name}, noticed {company}'s listing in your area and wanted to share a rapid strategy to help you dominate local search and turn direct dials into closed deals."
            
        return hook

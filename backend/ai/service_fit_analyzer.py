from typing import Dict, Any

class ServiceFitAnalyzer:
    """
    Analyzes verified leads to determine client suitability:
    - Exactly what services they can buy (Web Design, Meta Ads, WhatsApp Bot, GMB SEO, B2B Outreach)
    - Buyer Readiness Score (High, Medium, Low)
    - Actionable value pitch hook addressing their exact business gap.
    """

    @staticmethod
    def analyze(lead: Dict[str, Any]) -> Dict[str, Any]:
        phone = lead.get("phone", "")
        website = lead.get("website", "")
        socials = lead.get("socials", {}) or {}
        founder_name = lead.get("founder_name", "")
        reviews = int(lead.get("reviews", 0) or 0) if str(lead.get("reviews", "0")).isdigit() else 0
        rating = float(lead.get("rating", 0) or 0) if str(lead.get("rating", "0")).replace(".", "", 1).isdigit() else 0.0

        has_fb = bool(socials.get("facebook"))
        has_ig = bool(socials.get("instagram"))
        has_li = bool(socials.get("linkedin"))
        has_website = bool(website and website.startswith("http"))
        has_phone = bool(phone)
        has_owner = bool(founder_name and founder_name not in ["Key Decision Maker", "Executive Lead", "Verified Profile"])

        tags = []
        primary_service = ""
        service_gap = ""
        readiness_level = "Medium"
        readiness_score = 50

        # Case 1: Active Local Business WITHOUT a Website (Top Web Dev & SEO Target)
        if has_phone and not has_website:
            primary_service = "Web Design & Conversion Funnel"
            service_gap = "Missing Website: Losing 70% of high-intent search traffic to competitors."
            readiness_level = "High"
            readiness_score = 92
            tags.append("Needs Website")
            tags.append("Local SEO")

        # Case 2: Has Website but Missing Social Media Channels (Meta Ads & Social Growth Target)
        elif has_website and (not has_fb and not has_ig):
            primary_service = "Meta Ads & Social Media Lead Gen"
            service_gap = "Has Website but No Social Footprint: High opportunity to run targeted Facebook & Instagram ads."
            readiness_level = "High"
            readiness_score = 88
            tags.append("Needs Social Presence")
            tags.append("Meta Ads")

        # Case 3: Verified C-Level Executive / Decision-Maker
        elif has_owner and has_website:
            primary_service = "B2B Sales Pipeline & Client Acquisition"
            service_gap = "Executive Identified: Direct line to CEO/Owner for high-ticket agency services."
            readiness_level = "High"
            readiness_score = 95
            tags.append("Decision-Maker Found")
            tags.append("High-Ticket B2B")

        # Case 4: General Established Business with Website & Phone
        elif has_website and has_phone:
            primary_service = "WhatsApp AI Bot & CRM Automation"
            service_gap = "Established Online: Needs 24/7 WhatsApp auto-reply bot to convert incoming inquiries into bookings."
            readiness_level = "Medium"
            readiness_score = 75
            tags.append("WhatsApp Automation")

        # Case 5: Basic listing
        else:
            primary_service = "Google Business Profile Optimization"
            service_gap = "Incomplete Online Profile: Needs GMB verification & local citation cleanup."
            readiness_level = "Medium"
            readiness_score = 60
            tags.append("GMB Optimization")

        # Reputation Opportunity
        if reviews < 15 and has_phone:
            tags.append("Needs 5-Star Reviews")

        return {
            "primary_service": primary_service,
            "service_gap": service_gap,
            "readiness_level": readiness_level,
            "readiness_score": readiness_score,
            "service_tags": tags
        }

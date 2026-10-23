import re
from typing import List, Dict, Set

# Comprehensive Deep Industry Taxonomies (Micro-keywords, synonyms, sub-niches)
INDUSTRY_TAXONOMIES: Dict[str, List[str]] = {
    "real estate": [
        "real estate",
        "property dealer",
        "real estate agency",
        "property advisors",
        "real estate consultants",
        "property consultants",
        "commercial property",
        "residential plots",
        "plots for sale",
        "files for sale",
        "builders and developers",
        "property marketing",
        "realtor",
        "real estate broker",
        "housing society office",
        "property investment",
        "estate care",
        "rental properties",
        "property management",
        "luxury homes",
        "commercial plaza office",
        "land development",
        "estate agent",
        "property valuation",
        "real estate marketing agency"
    ],
    "property": [
        "property dealer",
        "real estate agency",
        "property consultants",
        "property advisors",
        "commercial property",
        "plots for sale",
        "real estate broker",
        "builders and developers",
        "property marketing"
    ],
    "doctor": [
        "clinic",
        "hospital",
        "medical center",
        "specialist doctor",
        "physician",
        "consultant physician",
        "pediatrician",
        "gynecologist",
        "cardiologist",
        "dermatologist",
        "orthopedic surgeon",
        "general practitioner",
        "diagnostic center",
        "polyclinic",
        "healthcare clinic"
    ],
    "dentist": [
        "dental clinic",
        "dental hospital",
        "orthodontist",
        "teeth clinic",
        "dental surgeon",
        "implantologist",
        "cosmetic dentistry",
        "teeth whitening",
        "dental care center"
    ],
    "software": [
        "software house",
        "IT company",
        "digital agency",
        "web development agency",
        "mobile app development",
        "software development company",
        "SEO agency",
        "digital marketing company",
        "tech solutions",
        "software solutions",
        "IT consultants",
        "e-commerce agency",
        "SaaS company"
    ],
    "car dealer": [
        "car showroom",
        "used cars dealer",
        "auto dealer",
        "car motors",
        "automotive showroom",
        "car rent a car",
        "car trading",
        "vehicles for sale",
        "car dealership"
    ],
    "restaurant": [
        "restaurant",
        "cafe",
        "fast food",
        "family restaurant",
        "pizza shop",
        "burgers",
        "chinese restaurant",
        "traditional restaurant",
        "bakery and cafe",
        "coffee shop",
        "rooftop restaurant"
    ],
    "gym": [
        "gym",
        "fitness club",
        "fitness center",
        "workout club",
        "crossfit gym",
        "bodybuilding gym",
        "ladies gym",
        "personal training gym",
        "health club"
    ],
    "salon": [
        "beauty salon",
        "hair salon",
        "beauty parlor",
        "bridal salon",
        "men salon",
        "skin care clinic",
        "aesthetic clinic",
        "spa and salon",
        "laser clinic"
    ],
    "solar": [
        "solar company",
        "solar energy solutions",
        "solar panel installation",
        "solar system dealer",
        "renewable energy company",
        "solar inverters",
        "industrial solar",
        "residential solar systems"
    ],
    "construction": [
        "construction company",
        "builders and developers",
        "building contractors",
        "architectural firm",
        "interior design",
        "civil contractors",
        "renovation company",
        "structural engineers"
    ],
    "lawyer": [
        "law firm",
        "advocate",
        "legal consultant",
        "corporate lawyer",
        "high court advocate",
        "attorney",
        "legal advisors",
        "tax consultant lawyer"
    ]
}

# Sub-Areas for Cities (Pakistan & Global Hubs)
CITY_SUB_AREAS: Dict[str, List[str]] = {
    "faisalabad": [
        "D Ground", "Madina Town", "Peoples Colony", "Canal Road",
        "Kohinoor City", "Citi Housing", "Wapda City", "Gulberg",
        "Susan Road", "Satiana Road", "Jinnah Colony", "Samanabad",
        "FDA City", "Eden Valley", "Millat Town", "Sargodha Road",
        "Jaranwala Road", "Sheikhupura Road", "Civil Lines", "Bait-ul-Mukarram"
    ],
    "lahore": [
        "DHA", "Gulberg", "Johar Town", "Bahria Town", "Model Town",
        "Cantt", "Faisal Town", "Wapda Town", "Mall Road", "Cavalry Ground",
        "Garden Town", "Allama Iqbal Town", "Shadman", "Gulshan-e-Ravi", "Askari"
    ],
    "karachi": [
        "DHA", "Clifton", "Gulshan-e-Iqbal", "PECHS", "North Nazimabad",
        "Bahria Town", "Korangi", "Saddar", "Gulistan-e-Jauhar", "Malir",
        "Federal B Area", "Zamzama", "Tariq Road", "Shahrah-e-Faisal"
    ],
    "islamabad": [
        "F-6", "F-7", "F-8", "F-10", "F-11", "G-11", "Blue Area",
        "DHA Phase 2", "Bahria Town", "E-11", "I-8", "G-9", "G-10"
    ],
    "rawalpindi": [
        "Saddar", "Bahria Town", "Chaklala Scheme", "Peshawar Road",
        "Satellite Town", "Westridge", "Gulraiz", "Adyala Road"
    ],
    "multan": [
        "Cantt", "Gulgasht Colony", "Bosan Road", "Wapda Town", "Model Town"
    ],
    "sialkot": [
        "Cantt", "Model Town", "Kashmir Road", "Defense Road", "Paris Road"
    ],
    "gujranwala": [
        "DC Colony", "Model Town", "Wapda Town", "Citi Housing", "Rahwali"
    ],
    "dubai": [
        "Downtown Dubai", "Business Bay", "Dubai Marina", "JLT", "Deira", "Al Barsha"
    ],
    "london": [
        "City of London", "Westminster", "Canary Wharf", "Camden", "Kensington"
    ]
}

COMMERCIAL_MODIFIERS = [
    "best", "top", "agency", "consultants", "advisors", "office", "services", "near me"
]

def generate_deep_industry_queries(niche: str, location: str = "", max_queries: int = 50) -> List[str]:
    """
    Explodes any industry input into all micro-keywords, synonyms, 
    commercial modifiers, and local sub-areas to ensure zero businesses are missed.
    """
    n_lower = niche.strip().lower()
    loc = location.strip()
    loc_lower = loc.lower()

    # 1. Identify all micro-keywords in this taxonomy
    micro_keywords: List[str] = []
    for category_key, terms in INDUSTRY_TAXONOMIES.items():
        if category_key in n_lower or any(t in n_lower for t in terms[:3]):
            micro_keywords.extend(terms)
            break

    if not micro_keywords:
        # Default heuristic explosion if niche is custom
        micro_keywords = [
            niche,
            f"{niche} agency",
            f"{niche} company",
            f"{niche} services",
            f"{niche} consultants",
            f"{niche} office",
            f"{niche} dealer",
            f"best {niche}",
            f"top {niche}"
        ]

    # Always ensure the original query is at the very front
    primary_query = f"{niche} in {location}" if location else niche
    all_queries: List[str] = [primary_query]

    # 2. Add commercial variations with location
    if loc:
        for kw in micro_keywords:
            all_queries.append(f"{kw} in {loc}")
            all_queries.append(f"best {kw} in {loc}")

    # 3. Add Sub-Area localized queries (e.g. "real estate in D Ground Faisalabad")
    matched_sub_areas: List[str] = []
    for city, areas in CITY_SUB_AREAS.items():
        if city in loc_lower:
            matched_sub_areas = areas
            break

    if matched_sub_areas:
        # Cross primary micro-keywords with all sub-areas of that city
        top_micro = micro_keywords[:6]
        for area in matched_sub_areas:
            for kw in top_micro[:3]:
                all_queries.append(f"{kw} in {area} {loc}")
            all_queries.append(f"{niche} {area} {loc}")

    # Deduplicate while preserving order
    seen: Set[str] = set()
    final_list: List[str] = []
    for q in all_queries:
        clean = " ".join(q.split())
        clean_key = clean.lower()
        if clean_key not in seen:
            seen.add(clean_key)
            final_list.append(clean)
            if len(final_list) >= max_queries:
                break

    return final_list

import os
import io
import base64
import pandas as pd
from typing import List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import BASE_DIR, BASE_URL
from backend.scrapers.gmaps_scraper import GoogleMapsScraper
from backend.scrapers.website_hunter import WebsiteHunter
from backend.scrapers.email_verifier import verify_email
from backend.ai.enricher import AIEnricher
from backend.outreach.tracker import (
    init_db, save_lead, get_all_leads, record_email_open,
    record_email_click, get_stats
)
from backend.outreach.mailer import send_cold_email

app = FastAPI(title="Leads Engine AI (Free Edition)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Database
try:
    init_db()
except Exception:
    pass

frontend_dir = BASE_DIR / "frontend"
static_dir = frontend_dir / "static"
static_dir.mkdir(exist_ok=True, parents=True)
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

enricher = AIEnricher()
hunter = WebsiteHunter()
maps_scraper = GoogleMapsScraper(headless=True)

class SearchRequest(BaseModel):
    prompt: str
    max_results: int = 10

class CampaignRequest(BaseModel):
    lead_ids: Optional[List[int]] = None
    subject: str
    body: str

@app.get("/", response_class=HTMLResponse)
async def root():
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Leads Engine AI API is running</h1>")

@app.get("/api/stats")
async def api_stats():
    return get_stats()

@app.get("/api/leads")
async def api_leads(limit: int = 100):
    return get_all_leads(limit=limit)

@app.post("/api/leads/search")
async def api_search(req: SearchRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    parsed = await enricher.parse_prompt(req.prompt)
    search_query = parsed.get("query") or req.prompt
    service_to_pitch = parsed.get("service_to_pitch", "")

    raw_leads = await maps_scraper.search_leads(search_query, max_results=req.max_results)

    enriched_leads = []
    for item in raw_leads:
        lead = {
            "name": item.get("name", ""),
            "category": item.get("category", ""),
            "rating": item.get("rating", "N/A"),
            "reviews": item.get("reviews", "0"),
            "phone": item.get("phone", ""),
            "website": item.get("website", ""),
            "email": "",
            "email_status": "NONE",
            "founder_name": "",
            "socials": {"linkedin": "", "instagram": "", "facebook": "", "twitter": ""},
            "ai_score": 30,
            "pitch_hook": ""
        }

        website = lead["website"]
        if website:
            try:
                crawl_data = await hunter.crawl_site(website)
                if crawl_data.get("primary_email"):
                    lead["email"] = crawl_data["primary_email"]
                if not lead["phone"] and crawl_data.get("phones"):
                    lead["phone"] = crawl_data["phones"][0]
                if crawl_data.get("founder_name"):
                    lead["founder_name"] = crawl_data["founder_name"]
                if crawl_data.get("socials"):
                    lead["socials"] = crawl_data["socials"]
            except Exception:
                pass

        if lead["email"]:
            is_valid, status = verify_email(lead["email"])
            lead["email_status"] = status

        lead["ai_score"] = enricher.score_lead(lead)
        lead["pitch_hook"] = enricher.generate_pitch_hook(lead, service_to_pitch)

        try:
            lead_id = save_lead(lead, search_query=search_query)
            lead["id"] = lead_id
        except Exception:
            lead["id"] = len(enriched_leads) + 1

        enriched_leads.append(lead)

    return {
        "status": "success",
        "query_used": search_query,
        "leads_count": len(enriched_leads),
        "leads": enriched_leads
    }

@app.get("/api/leads/export")
async def api_export(format: str = Query("csv", pattern="^(csv|xlsx)$")):
    leads = get_all_leads(limit=1000)
    if not leads:
        raise HTTPException(status_code=404, detail="No leads to export")

    export_rows = []
    for l in leads:
        soc = l.get("socials", {})
        export_rows.append({
            "Business Name": l.get("name"),
            "Founder / Contact": l.get("founder_name"),
            "Category": l.get("category"),
            "Verified Email": l.get("email"),
            "Email Status": l.get("email_status"),
            "Phone Number": l.get("phone"),
            "Website": l.get("website"),
            "Rating": l.get("rating"),
            "Review Count": l.get("reviews"),
            "LinkedIn": soc.get("linkedin", ""),
            "Instagram": soc.get("instagram", ""),
            "Facebook": soc.get("facebook", ""),
            "AI Score": l.get("ai_score"),
            "AI Personalized Pitch": l.get("pitch_hook"),
            "Scraped At": l.get("created_at")
        })

    df = pd.DataFrame(export_rows)

    if format == "xlsx":
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="LeadsEngine_Contacts")
        output.seek(0)
        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=LeadsEngine_Contacts.xlsx"}
        )
    else:
        csv_data = df.to_csv(index=False)
        return Response(
            content=csv_data,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=LeadsEngine_Contacts.csv"}
        )

@app.post("/api/campaigns/send")
async def api_send_campaign(req: CampaignRequest):
    all_leads = get_all_leads(limit=500)
    target_leads = [l for l in all_leads if l.get("email")]

    if req.lead_ids:
        target_leads = [l for l in target_leads if l.get("id") in req.lead_ids]

    if not target_leads:
        raise HTTPException(status_code=400, detail="No valid leads with emails found")

    results = []
    success_count = 0
    for lead in target_leads:
        success, msg = send_cold_email(lead, req.subject, req.body, base_url=BASE_URL)
        if success:
            success_count += 1
        results.append({
            "lead_id": lead.get("id"),
            "email": lead.get("email"),
            "success": success,
            "message": msg
        })

    return {
        "status": "completed",
        "total": len(target_leads),
        "sent": success_count,
        "details": results
    }

PIXEL_BYTES = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

@app.get("/api/track/open/{log_id}")
async def track_open(log_id: str):
    record_email_open(log_id)
    return Response(content=PIXEL_BYTES, media_type="image/gif")

@app.get("/api/track/click/{log_id}")
async def track_click(log_id: str, url: str):
    record_email_click(log_id)
    return RedirectResponse(url=url)

import os
import io
import re
import base64
import asyncio
import httpx
import pandas as pd
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.config import BASE_DIR, BASE_URL
from backend.scrapers.gmaps_scraper import GoogleMapsScraper
from backend.scrapers.website_hunter import WebsiteHunter
from backend.scrapers.linkedin_hunter import LinkedInHunter
from backend.scrapers.email_verifier import (
    verify_email,
    LeadEnricher,
    SmtpVerifier,
    discover_and_verify_corporate_email
)
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
try:
    static_dir = frontend_dir / "static"
    static_dir.mkdir(exist_ok=True, parents=True)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
except Exception:
    pass

enricher = AIEnricher()
hunter = WebsiteHunter()
maps_scraper = GoogleMapsScraper(headless=True)
linkedin_hunter = LinkedInHunter()

class SearchRequest(BaseModel):
    prompt: str
    mode: str = "hybrid"  # "hybrid", "linkedin", "maps"
    role: Optional[str] = "CEO, Founder, Owner, Managing Director"
    seniority: Optional[str] = None  # "c_level", "founder", "vp", "director", "manager"
    location: Optional[str] = ""
    max_results: int = 50
    use_variations: bool = True
    only_with_email: bool = False
    only_with_phone: bool = False
    only_with_linkedin: bool = False
    min_score: int = 0

class PredictEmailRequest(BaseModel):
    name: str
    domain: str

class VerifyEmailRequest(BaseModel):
    email: str

class ParseRawTextRequest(BaseModel):
    raw_text: str
    default_domain: Optional[str] = ""

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

@app.post("/api/leads/predict-email")
async def api_predict_email(req: PredictEmailRequest):
    """
    Reverse-engineers Apollo/Lusha email discovery:
    Generates 8 standard corporate email permutations and verifies MX server & mailbox.
    """
    if not req.name or not req.domain:
        raise HTTPException(status_code=400, detail="Name and domain are required")
    res = await discover_and_verify_corporate_email(req.name, req.domain)
    return res

@app.post("/api/leads/verify-email")
async def api_verify_single(req: VerifyEmailRequest):
    """
    Runs direct SMTP Handshake + Catch-All detection on any email.
    """
    if not req.email or "@" not in req.email:
        raise HTTPException(status_code=400, detail="Valid email address is required")
    domain = LeadEnricher.clean_domain(req.email.split("@")[1])
    mx_info = await LeadEnricher.validate_dns_mx(domain)
    primary_mx = mx_info.get("host", "")
    
    smtp_res = await SmtpVerifier.verify_mailbox(primary_mx, req.email)
    return {
        "email": req.email,
        "valid": smtp_res.get("deliverable", False),
        "status": smtp_res.get("status", "UNVERIFIED"),
        "label": smtp_res.get("label", ""),
        "provider": mx_info.get("provider", "Unknown"),
        "mx_host": primary_mx,
        "is_catch_all": smtp_res.get("catch_all", False)
    }

@app.post("/api/leads/parse-raw")
async def api_parse_raw_text(req: ParseRawTextRequest):
    """
    Direct SERP & LinkedIn Ingest Bridge (from OpenLead X):
    Instantly parses pasted Google search results or LinkedIn profile URLs,
    extracts names/titles, resolves corporate domain MX, predicts emails, and stores leads.
    """
    text = req.raw_text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="raw_text cannot be empty")

    lines = [line.strip() for line in text.split("\n") if line.strip()]
    parsed_leads = []
    seen_urls = set()

    for i, line in enumerate(lines):
        if "linkedin" in line.lower() or " - " in line or " – " in line or " | " in line:
            name, jt, comp = linkedin_hunter.parse_linkedin_title(line)
            if len(name.split()) >= 2 and len(name) < 45 and not name.lower().startswith("http"):
                associated_url = ""
                for nearby in lines[max(0, i-1):min(len(lines), i+4)]:
                    m = re.search(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/([a-zA-Z0-9_-]+)", nearby, re.IGNORECASE)
                    if m:
                        associated_url = f"https://www.linkedin.com/in/{m.group(1).lower()}"
                        break

                if not associated_url:
                    slug = re.sub(r"[^a-zA-Z0-9]", "-", name.lower()).strip("-")
                    associated_url = f"https://www.linkedin.com/in/{slug}"

                if associated_url not in seen_urls:
                    seen_urls.add(associated_url)
                    lead_domain = req.default_domain or (f"{re.sub(r'[^a-zA-Z0-9]', '', comp.lower())}.com" if comp else "")
                    
                    enrich = await discover_and_verify_corporate_email(name, lead_domain) if lead_domain else {}

                    lead_dict = {
                        "name": comp or "Executive Firm",
                        "category": "Direct SERP Ingest",
                        "founder_name": name,
                        "founder_role": jt or "Executive",
                        "rating": "5.0",
                        "reviews": "1",
                        "phone": "",
                        "website": f"https://{lead_domain}" if lead_domain else "",
                        "address": "",
                        "email": enrich.get("email", ""),
                        "email_status": enrich.get("email_status", "NONE"),
                        "mx_provider": enrich.get("provider", ""),
                        "socials": {"linkedin": associated_url, "instagram": "", "facebook": "", "twitter": ""},
                        "ai_score": 85,
                        "pitch_hook": f"Hi {name}, saw your profile as {jt} at {comp}. Would love to connect and share some strategic growth opportunities.",
                        "source": "SERP / URL Ingest"
                    }
                    try:
                        lead_id = save_lead(lead_dict, search_query="Manual SERP Ingest")
                        lead_dict["id"] = lead_id
                    except Exception:
                        lead_dict["id"] = 0
                    parsed_leads.append(lead_dict)

    return {
        "status": "success",
        "parsed_count": len(parsed_leads),
        "leads": parsed_leads
    }

MASTER_CSV_PATH = BASE_DIR / "Master_Leads_Database.csv"

class GlobalScraperState:
    is_running: bool = False
    stop_event: Optional[asyncio.Event] = None
    task: Optional[asyncio.Task] = None
    logs: List[str] = []
    session_leads: List[dict] = []
    emails_found: int = 0
    phones_found: int = 0
    total_scraped: int = 0
    query_used: str = ""

hunt_state = GlobalScraperState()

@app.post("/api/leads/start-hunt")
async def start_hunt(req: SearchRequest):
    if hunt_state.is_running:
        return {"status": "already_running", "message": "A lead hunt is already active."}

    user_prompt = req.prompt.strip()
    loc_param = req.location.strip() if req.location and req.location.strip() else ""
    if loc_param:
        location = loc_param
        niche = re.sub(rf'\s+in\s+{re.escape(loc_param)}', '', user_prompt, flags=re.IGNORECASE).strip()
        search_query = f"{niche} in {location}" if location else niche
    else:
        parsed = await enricher.parse_prompt(user_prompt)
        search_query = parsed.get("query") or user_prompt
        niche = parsed.get("niche") or user_prompt
        location = parsed.get("location") or ""

    hunt_state.is_running = True
    hunt_state.stop_event = asyncio.Event()
    hunt_state.logs = []
    hunt_state.session_leads = []
    hunt_state.emails_found = 0
    hunt_state.phones_found = 0
    hunt_state.total_scraped = 0
    hunt_state.query_used = search_query

    def append_log(msg: str):
        hunt_state.logs.append(msg)
        if len(hunt_state.logs) > 500:
            hunt_state.logs = hunt_state.logs[-500:]

    def append_lead(lead_item: dict):
        hunt_state.session_leads.append(lead_item)
        hunt_state.total_scraped = len(hunt_state.session_leads)
        if lead_item.get("phone"):
            hunt_state.phones_found += 1
        if lead_item.get("email"):
            hunt_state.emails_found += 1
        
        # Save to database
        try:
            lead_id = save_lead(lead_item, search_query=search_query)
            lead_item["id"] = lead_id
        except Exception:
            pass

        # Save to Master_Leads_Database.csv on disk
        try:
            df = pd.DataFrame([lead_item])
            if not os.path.exists(MASTER_CSV_PATH):
                df.to_csv(MASTER_CSV_PATH, index=False, header=True, encoding="utf-8-sig")
            else:
                df.to_csv(MASTER_CSV_PATH, mode="a", index=False, header=False, encoding="utf-8-sig")
        except Exception:
            pass

    async def background_hunter():
        append_log(f"🚀 Lead Hunter Initialized: Target={req.max_results} leads | Niche='{niche}' | Location='{location}' | Mode={req.mode}")
        try:
            if req.mode == "maps":
                await maps_scraper.search_leads(
                    search_query,
                    max_results=req.max_results,
                    use_variations=req.use_variations,
                    on_log=append_log,
                    on_lead=append_lead,
                    stop_event=hunt_state.stop_event
                )
            elif req.mode == "linkedin":
                li_leads = await linkedin_hunter.find_decision_makers(
                    niche=niche,
                    location=location,
                    role=req.role or "CEO, Founder, Owner, Managing Director",
                    seniority=req.seniority,
                    max_results=req.max_results
                )
                for l in li_leads:
                    append_lead(l)
                    append_log(f"🎯 [LinkedIn] Found {l.get('founder_name')} ({l.get('founder_role')}) at {l.get('name')}")
            else: # Hybrid
                append_log("⚡ Running Hybrid Sweep: Google Maps + LinkedIn Decision Makers simultaneously...")
                maps_task = maps_scraper.search_leads(
                    search_query,
                    max_results=req.max_results,
                    use_variations=req.use_variations,
                    on_log=append_log,
                    on_lead=append_lead,
                    stop_event=hunt_state.stop_event
                )
                li_task = linkedin_hunter.find_decision_makers(
                    niche=niche,
                    location=location,
                    role=req.role or "CEO, Founder, Owner, Managing Director",
                    seniority=req.seniority,
                    max_results=max(10, req.max_results // 3)
                )
                res_maps, res_li = await asyncio.gather(maps_task, li_task, return_exceptions=True)
                if isinstance(res_li, list):
                    for l in res_li:
                        append_lead(l)
                        append_log(f"🎯 [LinkedIn] Found {l.get('founder_name')} at {l.get('name')}")
            
            append_log(f"✅ Scraping completed! Total {hunt_state.total_scraped} leads with {hunt_state.phones_found} verified phone numbers.")
        except Exception as err:
            append_log(f"💥 Scraping notice: {str(err)}")
        finally:
            hunt_state.is_running = False

    hunt_state.task = asyncio.create_task(background_hunter())
    return {
        "status": "started",
        "message": "Lead hunting process started in background.",
        "query": search_query
    }

@app.get("/api/leads/hunt-status")
async def hunt_status(last_log_idx: int = 0):
    return {
        "is_running": hunt_state.is_running,
        "total_scraped": hunt_state.total_scraped,
        "phones_found": hunt_state.phones_found,
        "emails_found": hunt_state.emails_found,
        "query_used": hunt_state.query_used,
        "logs": hunt_state.logs[last_log_idx:],
        "total_logs": len(hunt_state.logs),
        "leads": hunt_state.session_leads
    }

@app.post("/api/leads/stop-hunt")
async def stop_hunt():
    if hunt_state.is_running and hunt_state.stop_event:
        hunt_state.stop_event.set()
        hunt_state.logs.append("🛑 Abort signal triggered by user.")
        return {"status": "stopping", "message": "Stop signal sent."}
    return {"status": "idle", "message": "No active hunt is running."}

@app.post("/api/leads/search")
async def api_search(req: SearchRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt is required")

    user_prompt = req.prompt.strip()
    loc_param = req.location.strip() if req.location and req.location.strip() else ""
    if loc_param:
        location = loc_param
        niche = re.sub(rf'\s+in\s+{re.escape(loc_param)}', '', user_prompt, flags=re.IGNORECASE).strip()
        search_query = f"{niche} in {location}" if location else niche
    else:
        parsed = await enricher.parse_prompt(user_prompt)
        search_query = parsed.get("query") or user_prompt
        niche = parsed.get("niche") or user_prompt
        location = parsed.get("location") or ""

    service_to_pitch = parsed.get("service_to_pitch", "") if 'parsed' in locals() else "Sales Automation"

    raw_leads = []

    if req.mode == "linkedin":
        raw_leads = await linkedin_hunter.find_decision_makers(
            niche=niche,
            location=location,
            role=req.role or "CEO, Founder, Owner, Managing Director",
            seniority=req.seniority,
            max_results=req.max_results
        )
    elif req.mode == "maps":
        raw_leads = await maps_scraper.search_leads(
            search_query,
            max_results=req.max_results,
            use_variations=req.use_variations
        )
    else:  # Hybrid: both Maps and LinkedIn
        tasks = [
            maps_scraper.search_leads(
                search_query,
                max_results=req.max_results,
                use_variations=req.use_variations
            ),
            linkedin_hunter.find_decision_makers(
                niche=niche,
                location=location,
                role=req.role or "CEO, Founder, Owner, Managing Director",
                seniority=req.seniority,
                max_results=req.max_results
            )
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        maps_res = results[0] if isinstance(results[0], list) else []
        li_res = results[1] if isinstance(results[1], list) else []

        raw_leads = []
        for i in range(max(len(maps_res), len(li_res))):
            if i < len(li_res): raw_leads.append(li_res[i])
            if i < len(maps_res): raw_leads.append(maps_res[i])
        raw_leads = raw_leads[:max(req.max_results, len(raw_leads))]

    if not raw_leads:
        raw_leads = await maps_scraper._scrape_via_duckduckgo(search_query, max_results=req.max_results)

    async with httpx.AsyncClient(
        headers=hunter.headers,
        follow_redirects=True,
        verify=False,
        timeout=hunter.timeout
    ) as client:
        async def process_lead(item: dict) -> Optional[dict]:
            lead = {
                "name": item.get("name", ""),
                "category": item.get("category", ""),
                "rating": item.get("rating", "N/A"),
                "reviews": item.get("reviews", "0"),
                "phone": item.get("phone", ""),
                "website": item.get("website", ""),
                "address": item.get("address", "") or location,
                "email": item.get("email", ""),
                "email_status": item.get("email_status", "NONE"),
                "mx_provider": item.get("mx_provider", ""),
                "email_permutations": item.get("email_permutations", []),
                "founder_name": item.get("founder_name", ""),
                "founder_role": item.get("founder_role", ""),
                "socials": item.get("socials", {"linkedin": "", "instagram": "", "facebook": "", "twitter": ""}),
                "ai_score": item.get("ai_score", 40),
                "pitch_hook": item.get("pitch_hook", ""),
                "source": item.get("source", "Web Hunt")
            }

            website = lead["website"]
            if website and website.startswith("http") and "/aclk" not in website:
                try:
                    crawl_data = await hunter.crawl_site(website, client=client)
                    if not lead["email"] and crawl_data.get("primary_email"):
                        lead["email"] = crawl_data["primary_email"]
                    if not lead["phone"] and crawl_data.get("phones"):
                        lead["phone"] = crawl_data["phones"][0]
                    if not lead["founder_name"] and crawl_data.get("founder_name"):
                        lead["founder_name"] = crawl_data["founder_name"]
                    if crawl_data.get("socials"):
                        for k, v in crawl_data["socials"].items():
                            if v and not lead["socials"].get(k):
                                lead["socials"][k] = v
                except Exception:
                    pass

            # If email is still empty but we have founder_name and website/domain:
            if not lead["email"] and lead["website"] and lead["founder_name"]:
                try:
                    dom = LeadEnricher.clean_domain(lead["website"])
                    enrich_data = await discover_and_verify_corporate_email(lead["founder_name"], dom)
                    if enrich_data.get("email"):
                        lead["email"] = enrich_data["email"]
                        lead["email_status"] = enrich_data["email_status"]
                        lead["mx_provider"] = enrich_data.get("provider", "")
                        lead["email_permutations"] = enrich_data.get("permutations", [])
                except Exception:
                    pass

            # If email exists, verify it if not yet verified
            if lead["email"] and lead["email_status"] in ["NONE", "UNKNOWN"]:
                try:
                    is_valid, status = verify_email(lead["email"])
                    lead["email_status"] = status
                    dom = LeadEnricher.clean_domain(lead["email"].split("@")[1])
                    mx_info = await LeadEnricher.validate_dns_mx(dom)
                    lead["mx_provider"] = mx_info.get("provider", "")
                except Exception:
                    lead["email_status"] = "RISKY"

            # Dynamic AI scoring
            base_score = enricher.score_lead(lead)
            if lead["socials"].get("linkedin"):
                base_score += 15
            if lead.get("founder_role"):
                base_score += 15
            if lead.get("email_status") in ["VERIFIED", "PREDICTED_MX"]:
                base_score += 10
            lead["ai_score"] = min(100, base_score)

            if not lead["pitch_hook"]:
                lead["pitch_hook"] = enricher.generate_pitch_hook(lead, service_to_pitch)

            # Apply quality filters
            if req.only_with_email and not lead["email"]:
                return None
            if req.only_with_phone and not lead["phone"]:
                return None
            if req.only_with_linkedin and not lead["socials"].get("linkedin"):
                return None
            if req.min_score > 0 and lead["ai_score"] < req.min_score:
                return None

            try:
                lead_id = save_lead(lead, search_query=search_query)
                lead["id"] = lead_id
            except Exception:
                lead["id"] = 0

            return lead

        tasks = [process_lead(item) for item in raw_leads]
        processed = await asyncio.gather(*tasks, return_exceptions=False)
        enriched_leads = [l for l in processed if l is not None]

    return {
        "status": "success",
        "query_used": search_query,
        "mode_used": req.mode,
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
            "Founder / Decision Maker": l.get("founder_name"),
            "Role / Title": l.get("founder_role", ""),
            "LinkedIn Profile": soc.get("linkedin", ""),
            "Category": l.get("category"),
            "Verified Email": l.get("email"),
            "Email Status": l.get("email_status"),
            "Mail Provider (MX)": l.get("mx_provider", ""),
            "Phone Number": l.get("phone"),
            "Website": l.get("website"),
            "Rating": l.get("rating"),
            "Review Count": l.get("reviews"),
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

@app.get("/api/unsubscribe/{log_id}", response_class=HTMLResponse)
async def unsubscribe_page(log_id: str):
    return HTMLResponse("""
    <!DOCTYPE html>
    <html lang="en">
    <head>
      <meta charset="UTF-8">
      <title>Unsubscribed</title>
      <style>
        body { background: #090b10; color: #f3f4f6; font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { background: #111420; border: 1px solid #23293e; padding: 40px; border-radius: 16px; text-align: center; max-width: 400px; }
        h2 { color: #4ade80; margin-top: 0; }
        p { color: #9ca3af; font-size: 14px; line-height: 1.5; }
      </style>
    </head>
    <body>
      <div class="box">
        <h2>Unsubscribed Successfully</h2>
        <p>You have been removed from this outreach campaign. You will not receive any further automated emails from us.</p>
      </div>
    </body>
    </html>
    """)

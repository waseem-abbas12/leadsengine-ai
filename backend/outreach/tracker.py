import sqlite3
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from backend.config import DB_PATH

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        category TEXT,
        rating TEXT,
        reviews TEXT,
        phone TEXT,
        website TEXT,
        email TEXT,
        email_status TEXT,
        founder_name TEXT,
        socials TEXT,
        ai_score INTEGER,
        pitch_hook TEXT,
        search_query TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS email_logs (
        id TEXT PRIMARY KEY,
        lead_id INTEGER,
        recipient_email TEXT,
        subject TEXT,
        status TEXT,
        sent_at TIMESTAMP,
        opened_at TIMESTAMP,
        clicked_at TIMESTAMP,
        open_count INTEGER DEFAULT 0,
        click_count INTEGER DEFAULT 0,
        FOREIGN KEY (lead_id) REFERENCES leads (id)
    )
    """)

    conn.commit()
    conn.close()

def save_lead(lead: Dict[str, Any], search_query: str = "") -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO leads (
        name, category, rating, reviews, phone, website,
        email, email_status, founder_name, socials, ai_score, pitch_hook, search_query
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        lead.get("name", ""),
        lead.get("category", ""),
        lead.get("rating", "N/A"),
        lead.get("reviews", "0"),
        lead.get("phone", ""),
        lead.get("website", ""),
        lead.get("email", ""),
        lead.get("email_status", "UNKNOWN"),
        lead.get("founder_name", ""),
        json.dumps(lead.get("socials", {})),
        lead.get("ai_score", 50),
        lead.get("pitch_hook", ""),
        search_query
    ))
    lead_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return lead_id

def get_all_leads(limit: int = 100) -> List[Dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM leads ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    leads = []
    for r in rows:
        d = dict(r)
        try:
            d["socials"] = json.loads(d["socials"])
        except Exception:
            d["socials"] = {}
        leads.append(d)
    conn.close()
    return leads

def record_email_sent(log_id: str, lead_id: int, recipient_email: str, subject: str, status: str = "SENT"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO email_logs (id, lead_id, recipient_email, subject, status, sent_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (log_id, lead_id, recipient_email, subject, status, datetime.utcnow()))
    conn.commit()
    conn.close()

def record_email_open(log_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE email_logs
    SET opened_at = COALESCE(opened_at, ?), open_count = open_count + 1, status = 'OPENED'
    WHERE id = ?
    """, (datetime.utcnow(), log_id))
    conn.commit()
    conn.close()

def record_email_click(log_id: str):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE email_logs
    SET clicked_at = COALESCE(clicked_at, ?), click_count = click_count + 1, status = 'CLICKED'
    WHERE id = ?
    """, (datetime.utcnow(), log_id))
    conn.commit()
    conn.close()

def get_stats() -> Dict[str, Any]:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM leads")
    total_leads = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM leads WHERE email != '' AND email IS NOT NULL")
    emails_found = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM email_logs")
    emails_sent = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM email_logs WHERE open_count > 0")
    emails_opened = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM email_logs WHERE click_count > 0")
    emails_clicked = cursor.fetchone()[0]

    conn.close()

    open_rate = round((emails_opened / emails_sent * 100), 1) if emails_sent > 0 else 0.0
    click_rate = round((emails_clicked / emails_sent * 100), 1) if emails_sent > 0 else 0.0

    return {
        "total_leads": total_leads,
        "emails_found": emails_found,
        "emails_sent": emails_sent,
        "emails_opened": emails_opened,
        "emails_clicked": emails_clicked,
        "open_rate": open_rate,
        "click_rate": click_rate
    }

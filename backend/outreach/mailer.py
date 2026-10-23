import re
import uuid
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote
from typing import Dict, Any, Tuple
from backend.config import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SENDER_NAME, BASE_URL
from backend.outreach.tracker import record_email_sent

def render_template(template: str, lead: Dict[str, Any]) -> str:
    name = lead.get("founder_name") or lead.get("name", "there")
    company = lead.get("name", "your company")
    phone = lead.get("phone", "")
    website = lead.get("website", "")
    pitch_hook = lead.get("pitch_hook", "")

    content = template
    content = content.replace("{{name}}", name)
    content = content.replace("{{company}}", company)
    content = content.replace("{{phone}}", phone)
    content = content.replace("{{website}}", website)
    content = content.replace("{{pitch_hook}}", pitch_hook)
    return content

def wrap_links_for_tracking(html_body: str, log_id: str, base_url: str) -> str:
    def replacer(match):
        original_url = match.group(1)
        # Skip mailto or anchors
        if original_url.startswith("mailto:") or original_url.startswith("#"):
            return match.group(0)
        redirect_url = f"{base_url}/api/track/click/{log_id}?url={quote(original_url)}"
        return f'href="{redirect_url}"'

    return re.sub(r'href=["\'](http[^"\']+)["\']', replacer, html_body)

def send_cold_email(
    lead: Dict[str, Any],
    subject_template: str,
    body_template: str,
    base_url: str = BASE_URL
) -> Tuple[bool, str]:
    """
    Sends cold email with 3-Layer tracking:
    - Layer 1: Deliverability check
    - Layer 2: 1x1 Open tracking pixel
    - Layer 3: Click redirection wrapper
    """
    recipient_email = lead.get("email")
    if not recipient_email:
        return False, "Recipient email is missing"

    log_id = str(uuid.uuid4())
    subject = render_template(subject_template, lead)
    rendered_body = render_template(body_template, lead)

    # 1. Convert plain text newlines to html if needed
    if "<p>" not in rendered_body and "<br" not in rendered_body:
        rendered_body = rendered_body.replace("\n", "<br>")

    # 2. Layer 3: Wrap links for click tracking
    wrapped_body = wrap_links_for_tracking(rendered_body, log_id, base_url)

    # 3. Layer 2: Injected 1x1 transparent tracking pixel + Unsubscribe footer
    pixel_url = f"{base_url}/api/track/open/{log_id}"
    tracking_pixel = f'<img src="{pixel_url}" width="1" height="1" style="display:none !important;" alt="" />'
    unsubscribe_url = f"{base_url}/api/unsubscribe/{log_id}"
    unsubscribe_footer = f'<br><br><span style="font-size:11px;color:#888;">If you prefer not to receive future emails from us, please <a href="{unsubscribe_url}" style="color:#666;text-decoration:underline;">click here to unsubscribe</a>.</span>'
    final_html = f"{wrapped_body}{unsubscribe_footer}<br><br>{tracking_pixel}"

    # Check if SMTP credentials exist
    if not SMTP_USER or not SMTP_PASSWORD:
        # SIMULATION / PREVIEW MODE (Logs email sent so user can test tracking and UI without breaking)
        record_email_sent(log_id, lead.get("id", 0), recipient_email, subject, status="SIMULATED")
        return True, f"Simulated Send (SMTP not configured). Tracking ID: {log_id[:8]}"

    # REAL SMTP SEND
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{SENDER_NAME} <{SMTP_USER}>"
        msg["To"] = recipient_email

        part = MIMEText(final_html, "html")
        msg.attach(part)

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, [recipient_email], msg.as_string())

        record_email_sent(log_id, lead.get("id", 0), recipient_email, subject, status="SENT")
        return True, f"Email successfully sent to {recipient_email}"
    except Exception as e:
        record_email_sent(log_id, lead.get("id", 0), recipient_email, subject, status="FAILED")
        return False, f"SMTP Error: {str(e)}"

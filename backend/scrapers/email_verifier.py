import re
import socket
import smtplib
import dns.resolver
from typing import Tuple, Dict

# Cache MX records to speed up verifications
MX_CACHE: Dict[str, str] = {}

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

def is_valid_syntax(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email))

def get_mx_record(domain: str) -> str:
    if domain in MX_CACHE:
        return MX_CACHE[domain]
    try:
        answers = dns.resolver.resolve(domain, 'MX')
        # pick highest priority (lowest preference number)
        best_mx = sorted(answers, key=lambda r: r.preference)[0].exchange.to_text().rstrip('.')
        MX_CACHE[domain] = best_mx
        return best_mx
    except Exception:
        MX_CACHE[domain] = ""
        return ""

def verify_email(email: str, timeout: int = 5) -> Tuple[bool, str]:
    """
    100% Free SMTP Handshake verification without sending email.
    Returns: (is_valid, status_label)
    status_label: 'VERIFIED', 'RISKY', 'INVALID'
    """
    email = email.strip().lower()
    if not is_valid_syntax(email):
        return False, "INVALID_SYNTAX"
    
    # Exclude common dummy/image emails
    dummy_patterns = ["example.com", "domain.com", "sentry.io", "wixpress.com", ".png", ".jpg", ".webp", "schema.org"]
    if any(p in email for p in dummy_patterns):
        return False, "INVALID_DUMMY"

    domain = email.split('@')[1]
    mx_host = get_mx_record(domain)
    if not mx_host:
        return False, "NO_MX_RECORDS"

    # Some providers (like yahoo/outlook) block handshake testing or accept all.
    # We do a respectful HELO and MAIL FROM / RCPT TO handshake.
    try:
        server = smtplib.SMTP(timeout=timeout)
        server.connect(mx_host, 25)
        server.helo("leadsengine.ai")
        server.mail("verify@leadsengine.ai")
        code, _ = server.rcpt(email)
        server.quit()
        
        if code == 250:
            return True, "VERIFIED"
        elif code == 550:
            return False, "INVALID_MAILBOX"
        else:
            # 450, 451, 452: Greylisted or transient -> Risky but potentially valid
            return True, "RISKY"
    except (socket.timeout, socket.error, smtplib.SMTPException):
        # Fallback: MX exists, so domain definitely receives emails
        return True, "VERIFIED_MX"

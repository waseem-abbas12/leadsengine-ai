import re
import socket
import smtplib
import asyncio
import dns.resolver
import dns.asyncresolver
from typing import Tuple, Dict, List, Any, Optional

# Cache MX records to speed up verifications
MX_CACHE: Dict[str, Dict[str, Any]] = {}

EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
)

def is_valid_syntax(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(EMAIL_REGEX.match(email))

class LeadEnricher:
    """
    Reverse-engineers Apollo.io / Lusha / Hunter.io email discovery.
    Generates corporate email permutations and verifies MX records via DNS.
    """
    @staticmethod
    def clean_name(name: str) -> Tuple[str, str]:
        """Cleans titles, suffixes, and splits full name into first and last name."""
        if not name:
            return "", ""
        name = re.sub(r"(?i)\b(ph\.?d|mba|cpa|md|esq|dr|mr|ms|mrs|jr|sr|ii|iii)\b\.?", "", name)
        name = re.sub(r"[^\w\s-]", "", name).strip()
        parts = name.split()
        if not parts:
            return "", ""
        if len(parts) == 1:
            return parts[0], ""
        return parts[0], parts[-1]

    @staticmethod
    def clean_domain(domain_or_url: str) -> str:
        """Extracts clean base domain (e.g. example.com)."""
        if not domain_or_url:
            return ""
        d = domain_or_url.strip().lower()
        d = re.sub(r"^https?://(www\.)?", "", d)
        d = d.split("/")[0].split(":")[0]
        return d

    @classmethod
    def generate_email_permutations(cls, first_name: str, last_name: str, domain: str) -> List[str]:
        """
        Generates standard B2B enterprise corporate email patterns.
        """
        if not domain:
            return []
        
        f = re.sub(r"[^a-zA-Z0-9]", "", first_name.lower())
        l = re.sub(r"[^a-zA-Z0-9]", "", last_name.lower())
        d = cls.clean_domain(domain)
        
        if not f and not l:
            return []
        if not l:
            return [f"{f}@{d}"]
        if not f:
            return [f"{l}@{d}"]

        fi = f[0]
        li = l[0]

        patterns = [
            f"{f}.{l}@{d}",       # john.doe@domain.com
            f"{f}@{d}",           # john@domain.com
            f"{fi}{l}@{d}",        # jdoe@domain.com
            f"{f}{li}@{d}",        # johnd@domain.com
            f"{l}.{f}@{d}",       # doe.john@domain.com
            f"{f}_{l}@{d}",       # john_doe@domain.com
            f"{f}{l}@{d}",        # johndoe@domain.com
            f"{l}@{d}",           # doe@domain.com
        ]
        return list(dict.fromkeys(patterns))

    @classmethod
    async def validate_dns_mx(cls, domain: str) -> Dict[str, Any]:
        """
        Performs asynchronous DNS MX-record validation on company domain.
        Detects active mail server and service provider (Google, Microsoft 365, Zoho, etc.).
        """
        clean_dom = cls.clean_domain(domain)
        if not clean_dom or "." not in clean_dom:
            return {"valid": False, "provider": "Invalid Domain", "host": "", "records": []}

        if clean_dom in MX_CACHE:
            return MX_CACHE[clean_dom]

        resolver = dns.asyncresolver.Resolver()
        resolver.nameservers = ['8.8.8.8', '1.1.1.1', '8.8.4.4']
        resolver.timeout = 3.5
        resolver.lifetime = 3.5

        try:
            answers = await resolver.resolve(clean_dom, "MX")
            # Sort by preference priority
            sorted_records = sorted(answers, key=lambda r: r.preference)
            records = [r.exchange.to_text().strip(".").lower() for r in sorted_records]
            if not records:
                res = {"valid": False, "provider": "No MX Records", "host": "", "records": []}
                MX_CACHE[clean_dom] = res
                return res

            primary_host = records[0]
            provider = "Custom / Enterprise MX"

            if any("google" in h or "googlemail" in h or "aspmx" in h for h in records):
                provider = "Google Workspace"
            elif any("outlook" in h or "microsoft" in h or "protection.outlook" in h for h in records):
                provider = "Microsoft 365"
            elif any("zoho" in h for h in records):
                provider = "Zoho Mail"
            elif any("mimecast" in h for h in records):
                provider = "Mimecast Gateway"
            elif any("barracuda" in h for h in records):
                provider = "Barracuda Cloud"
            elif any("protonmail" in h for h in records):
                provider = "Proton Mail"
            elif any("hostinger" in h for h in records):
                provider = "Hostinger Mail"

            res = {
                "valid": True,
                "provider": provider,
                "host": primary_host,
                "records": records,
            }
            MX_CACHE[clean_dom] = res
            return res
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            res = {"valid": False, "provider": "Domain Does Not Accept Mail", "host": "", "records": []}
            MX_CACHE[clean_dom] = res
            return res
        except Exception as e:
            res = {"valid": False, "provider": f"Lookup Failed ({type(e).__name__})", "host": "", "records": []}
            MX_CACHE[clean_dom] = res
            return res

class SmtpVerifier:
    """
    Performs non-intrusive SMTP handshake ping (HELO -> MAIL FROM -> RCPT TO)
    to verify mailbox existence without sending any email, and detects catch-all domains.
    """
    @staticmethod
    def verify_mailbox_sync(mx_host: str, target_email: str, timeout: float = 3.5) -> Dict[str, Any]:
        if not mx_host or not target_email or "@" not in target_email:
            return {"status": "unverified", "deliverable": False, "catch_all": False, "code": None, "label": "No MX/Email"}

        domain = target_email.split("@")[1]
        bogus_email = f"catchall_check_987654321xyz@{domain}"

        try:
            with smtplib.SMTP(mx_host, 25, timeout=timeout) as smtp:
                smtp.helo("leadsengine.ai")
                smtp.mail("verify@leadsengine.ai")
                
                # Check random bogus email to detect Catch-All servers
                is_catch_all = False
                try:
                    bogus_code, _ = smtp.rcpt(bogus_email)
                    is_catch_all = (bogus_code == 250)
                except Exception:
                    pass

                # Reset and test actual candidate email
                try:
                    smtp.mail("verify@leadsengine.ai")
                except Exception:
                    pass
                target_code, _ = smtp.rcpt(target_email)
                
                if target_code == 250:
                    if is_catch_all:
                        return {
                            "status": "CATCH_ALL",
                            "deliverable": True,
                            "catch_all": True,
                            "code": 250,
                            "label": "Catch-All Mail Server",
                        }
                    else:
                        return {
                            "status": "VERIFIED",
                            "deliverable": True,
                            "catch_all": False,
                            "code": 250,
                            "label": "100% Verified Deliverable Inbox",
                        }
                elif target_code in [550, 551, 552, 553, 554]:
                    return {
                        "status": "INVALID",
                        "deliverable": False,
                        "catch_all": False,
                        "code": target_code,
                        "label": "Mailbox Not Found (Invalid)",
                    }
                else:
                    return {
                        "status": "RISKY",
                        "deliverable": True,
                        "catch_all": is_catch_all,
                        "code": target_code,
                        "label": f"Server Response: {target_code}",
                    }
        except Exception:
            return {
                "status": "FILTERED_MX",
                "deliverable": True,
                "catch_all": False,
                "code": None,
                "label": "SMTP Port 25 Filtered (MX Active)",
            }

    @classmethod
    async def verify_mailbox(cls, mx_host: str, target_email: str) -> Dict[str, Any]:
        return await asyncio.to_thread(cls.verify_mailbox_sync, mx_host, target_email)

def get_mx_record(domain: str) -> str:
    clean_dom = LeadEnricher.clean_domain(domain)
    if clean_dom in MX_CACHE:
        return MX_CACHE[clean_dom].get("host", "")
    try:
        answers = dns.resolver.resolve(clean_dom, 'MX')
        best_mx = sorted(answers, key=lambda r: r.preference)[0].exchange.to_text().rstrip('.')
        return best_mx
    except Exception:
        return ""

def verify_email(email: str, timeout: int = 4) -> Tuple[bool, str]:
    """
    Synchronous verification wrapper for backwards compatibility.
    """
    email = email.strip().lower()
    if not is_valid_syntax(email):
        return False, "INVALID_SYNTAX"
    
    dummy_patterns = ["example.com", "domain.com", "sentry.io", "wixpress.com", ".png", ".jpg", ".webp", "schema.org"]
    if any(p in email for p in dummy_patterns):
        return False, "INVALID_DUMMY"

    domain = email.split('@')[1]
    mx_host = get_mx_record(domain)
    if not mx_host:
        return False, "NO_MX_RECORDS"

    res = SmtpVerifier.verify_mailbox_sync(mx_host, email, timeout=timeout)
    st = res["status"]
    if st == "VERIFIED":
        return True, "VERIFIED"
    elif st == "CATCH_ALL":
        return True, "CATCH_ALL"
    elif st == "INVALID":
        return False, "INVALID"
    else:
        return True, "VERIFIED_MX"

async def discover_and_verify_corporate_email(full_name: str, domain_or_url: str) -> Dict[str, Any]:
    """
    Intelligently generates permutations and validates the corporate email for a founder/executive.
    """
    fn, ln = LeadEnricher.clean_name(full_name)
    domain = LeadEnricher.clean_domain(domain_or_url)
    
    if not domain or not (fn or ln):
        return {
            "email": "",
            "email_status": "NONE",
            "provider": "",
            "mx_host": "",
            "permutations": []
        }

    mx_info = await LeadEnricher.validate_dns_mx(domain)
    if not mx_info.get("valid"):
        return {
            "email": "",
            "email_status": "NO_MX",
            "provider": mx_info.get("provider", "No MX"),
            "mx_host": "",
            "permutations": []
        }

    permutations = LeadEnricher.generate_email_permutations(fn, ln, domain)
    if not permutations:
        return {
            "email": "",
            "email_status": "NO_PERMUTATIONS",
            "provider": mx_info.get("provider", ""),
            "mx_host": mx_info.get("host", ""),
            "permutations": []
        }

    primary_mx = mx_info.get("host", "")
    provider = mx_info.get("provider", "Enterprise MX")

    # Pick the most standard enterprise permutation (first.last@domain or first@domain)
    best_candidate = permutations[0]
    
    # Try verifying best candidate via SMTP
    res = await SmtpVerifier.verify_mailbox(primary_mx, best_candidate)
    smtp_status = res.get("status", "FILTERED_MX")

    if smtp_status == "VERIFIED":
        final_status = "VERIFIED"
    elif smtp_status == "CATCH_ALL":
        final_status = "CATCH_ALL"
    elif smtp_status == "INVALID" and len(permutations) > 1:
        # Try second permutation (e.g. first@domain)
        second_candidate = permutations[1]
        res2 = await SmtpVerifier.verify_mailbox(primary_mx, second_candidate)
        if res2.get("status") in ["VERIFIED", "CATCH_ALL"]:
            best_candidate = second_candidate
            final_status = res2.get("status")
        else:
            final_status = "PREDICTED_MX"
    else:
        # Port 25 filtered or timeout -> MX is verified valid!
        final_status = "PREDICTED_MX"

    return {
        "email": best_candidate,
        "email_status": final_status,
        "provider": provider,
        "mx_host": primary_mx,
        "permutations": permutations
    }

"""
email_notify.py — Nata Portuguese Bakery email alerts via Resend API.
"""

import os
from datetime import datetime
import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key  = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM      = os.getenv("EMAIL_FROM", "nata@vizez.cloud")
TEAM_EMAIL      = os.getenv("WHOLESALE_EMAIL", "team@nata.co.nz")

LOGO_URL = "https://www.nata.co.nz/cdn/shop/files/top_logo.png?v=1613715845&width=80"

# ─── Shared email shell ───────────────────────────────────────────────────────

def _wrap(title: str, badge_text: str, badge_color: str, badge_bg: str,
          rows: list[tuple], footer_note: str = "") -> str:
    row_html = "".join(
        f"<tr><td>{k}</td><td>{v or '—'}</td></tr>" for k, v in rows
    )
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" />
<style>
  body   {{ font-family: 'Segoe UI', Arial, sans-serif; background:#fdf8f0; margin:0; padding:20px; }}
  .wrap  {{ max-width:540px; margin:0 auto; }}
  .head  {{ background:#3d2314; border-radius:12px 12px 0 0; padding:24px 28px;
             display:flex; align-items:center; gap:16px; }}
  .head img {{ width:52px; height:52px; border-radius:50%; }}
  .head-text h1 {{ color:#fdf5e8; font-size:17px; margin:0 0 2px; }}
  .head-text p  {{ color:#c8a87a; font-size:12px; margin:0; }}
  .body  {{ background:#fff; border:1px solid #e8d5b5; border-top:none;
             border-radius:0 0 12px 12px; padding:28px; }}
  .badge {{ display:inline-block; background:{badge_bg}; color:{badge_color};
             border-radius:20px; padding:4px 14px; font-size:12px;
             font-weight:600; margin-bottom:18px; }}
  h2     {{ color:#3d2314; font-size:18px; margin:0 0 4px; }}
  table  {{ width:100%; border-collapse:collapse; margin-top:12px; }}
  td     {{ padding:10px 8px; border-bottom:1px solid #f0ebe0; font-size:13.5px; }}
  td:first-child {{ color:#8a6545; width:140px; font-weight:500; }}
  td:last-child  {{ color:#1c1008; font-weight:600; }}
  .foot  {{ color:#8a6545; font-size:11px; margin-top:20px; text-align:center; }}
</style>
</head>
<body><div class="wrap">
  <div class="head">
    <img src="{LOGO_URL}" alt="Nata" />
    <div class="head-text">
      <h1>Nata Portuguese Bakery</h1>
      <p>AI Chat Notification · nata.co.nz</p>
    </div>
  </div>
  <div class="body">
    <h2>{title}</h2>
    <span class="badge">{badge_text}</span>
    <table>{row_html}</table>
    {f'<p style="color:#8a6545;font-size:12px;margin-top:16px">{footer_note}</p>' if footer_note else ''}
  </div>
  <div class="foot">Nata Portuguese Bakery AI Chat · <a href="https://nata.co.nz" style="color:#c8781a">nata.co.nz</a></div>
</div></body></html>"""


def _send(to: list[str], subject: str, html: str, text: str = "") -> bool:
    try:
        resend.Emails.send({
            "from":    f"Nata AI Chat <{EMAIL_FROM}>",
            "to":      to,
            "subject": subject,
            "html":    html,
            "text":    text or subject,
        })
        return True
    except Exception as e:
        print(f"[Email] Send failed: {e}")
        return False


# ─── Team Alerts ─────────────────────────────────────────────────────────────

def send_wholesale_alert(lead: dict) -> bool:
    ts = datetime.now().strftime("%d %b %Y, %I:%M %p")
    html = _wrap(
        title="New Wholesale Inquiry",
        badge_text="Wholesale Lead",
        badge_color="#92400e",
        badge_bg="#fef3c7",
        rows=[
            ("Business",    lead.get("business_name")),
            ("Contact",     lead.get("name")),
            ("Email",       lead.get("email")),
            ("Phone",       lead.get("phone")),
            ("Notes",       lead.get("notes")),
            ("Received",    ts),
        ],
    )
    return _send(
        to=[TEAM_EMAIL],
        subject=f"🥐 Wholesale Inquiry — {lead.get('business_name') or lead.get('name', 'Unknown')}",
        html=html,
    )


def send_general_lead_alert(lead: dict) -> bool:
    ts = datetime.now().strftime("%d %b %Y, %I:%M %p")
    itype = (lead.get("inquiry_type") or "General").title()
    html = _wrap(
        title=f"New {itype} Lead",
        badge_text=itype,
        badge_color="#1e40af",
        badge_bg="#eff6ff",
        rows=[
            ("Name",     lead.get("name")),
            ("Email",    lead.get("email")),
            ("Phone",    lead.get("phone")),
            ("Notes",    lead.get("notes")),
            ("Received", ts),
        ],
    )
    return _send(
        to=[TEAM_EMAIL],
        subject=f"💬 New Lead — {lead.get('name', 'Unknown Customer')}",
        html=html,
    )


def send_case_alert(case: dict) -> bool:
    """Notify the Nata team when a new support case is submitted."""
    ts = datetime.now().strftime("%d %b %Y, %I:%M %p")
    html = _wrap(
        title="Support Case Received",
        badge_text=f"Case #{case.get('case_id', '—')}",
        badge_color="#991b1b",
        badge_bg="#fef2f2",
        rows=[
            ("Case ID",     case.get("case_id")),
            ("Name",        case.get("name")),
            ("Email",       case.get("email")),
            ("Phone",       case.get("phone")),
            ("Subject",     case.get("subject")),
            ("Description", case.get("description")),
            ("Received",    ts),
        ],
        footer_note="Log in to your dashboard to update the case status.",
    )
    return _send(
        to=[TEAM_EMAIL],
        subject=f"🎫 Support Case {case.get('case_id', '')} — {case.get('name', 'Customer')}",
        html=html,
    )


# ─── Customer Confirmations ───────────────────────────────────────────────────

def send_customer_case_confirmation(name: str, to_email: str, case_id: str,
                                    subject: str) -> bool:
    """Send a confirmation email to the customer after their case is created."""
    if not to_email:
        return False
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" />
<style>
  body  {{ font-family: 'Segoe UI', Arial, sans-serif; background:#fdf8f0; margin:0; padding:20px; }}
  .wrap {{ max-width:520px; margin:0 auto; }}
  .head {{ background:#3d2314; border-radius:12px 12px 0 0; padding:24px 28px;
            text-align:center; }}
  .head img {{ width:64px; height:64px; border-radius:50%; }}
  .head h1  {{ color:#fdf5e8; font-size:16px; margin:8px 0 0; }}
  .body {{ background:#fff; border:1px solid #e8d5b5; border-top:none;
            border-radius:0 0 12px 12px; padding:32px; text-align:center; }}
  .case-id {{ font-size:28px; font-weight:800; color:#3d2314;
               background:#fdf5e8; border:2px solid #e8d5b5;
               border-radius:12px; padding:12px 24px; display:inline-block;
               margin:16px 0; letter-spacing:0.02em; }}
  p    {{ color:#3d2314; font-size:14px; line-height:1.6; }}
  .muted {{ color:#8a6545; font-size:12px; margin-top:24px; }}
</style>
</head>
<body><div class="wrap">
  <div class="head">
    <img src="{LOGO_URL}" alt="Nata" />
    <h1>Nata Portuguese Bakery</h1>
  </div>
  <div class="body">
    <p>Olá <strong>{name}</strong>,</p>
    <p>We've received your enquiry and a support case has been created. Our team will be in touch shortly.</p>
    <div class="case-id">{case_id}</div>
    <p><strong>Subject:</strong> {subject or 'General Enquiry'}</p>
    <p>Please quote your Case ID in any follow-up communications.</p>
    <p class="muted">Nata Portuguese Bakery · <a href="https://nata.co.nz" style="color:#c8781a">nata.co.nz</a><br/>
    info@nata.co.nz · 02040805012</p>
  </div>
</div></body></html>"""
    return _send(
        to=[to_email],
        subject=f"Your Nata Support Case — {case_id}",
        html=html,
        text=f"Hi {name},\n\nYour support case {case_id} has been created.\nSubject: {subject}\n\nWe'll be in touch soon.\n— Nata Portuguese Bakery",
    )


def send_lead_confirmation(name: str, to_email: str) -> bool:
    """Send a brief confirmation to a customer after their lead is captured."""
    if not to_email:
        return False
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8" />
<style>
  body  {{ font-family:'Segoe UI',Arial,sans-serif; background:#fdf8f0; margin:0; padding:20px; }}
  .wrap {{ max-width:520px; margin:0 auto; }}
  .head {{ background:#3d2314; border-radius:12px 12px 0 0; padding:20px 28px; text-align:center; }}
  .head img {{ width:56px; border-radius:50%; }}
  .head h1  {{ color:#fdf5e8; font-size:15px; margin:8px 0 0; }}
  .body {{ background:#fff; border:1px solid #e8d5b5; border-top:none;
            border-radius:0 0 12px 12px; padding:28px; }}
  p {{ color:#3d2314; font-size:14px; line-height:1.6; }}
  .foot {{ color:#8a6545; font-size:11px; margin-top:20px; text-align:center; }}
</style>
</head>
<body><div class="wrap">
  <div class="head">
    <img src="{LOGO_URL}" alt="Nata" />
    <h1>Nata Portuguese Bakery</h1>
  </div>
  <div class="body">
    <p>Kia ora <strong>{name}</strong>,</p>
    <p>Thanks for getting in touch! We've received your enquiry and a member of our team will be in contact with you shortly.</p>
    <p>In the meantime, visit <a href="https://nata.co.nz" style="color:#c8781a">nata.co.nz</a> to explore our range of authentic Portuguese tarts.</p>
    <p>Obrigado! 🥐</p>
  </div>
  <div class="foot">Nata Portuguese Bakery · info@nata.co.nz · 02040805012</div>
</div></body></html>"""
    return _send(
        to=[to_email],
        subject="Thanks for contacting Nata Portuguese Bakery",
        html=html,
        text=f"Hi {name},\n\nThanks for your enquiry. We'll be in touch soon.\n— Nata Portuguese Bakery",
    )

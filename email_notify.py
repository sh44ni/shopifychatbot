"""
email_notify.py — Wholesale email alerts via Resend API.
"""

import os
from datetime import datetime
import resend
from dotenv import load_dotenv

load_dotenv()

resend.api_key = os.getenv("RESEND_API_KEY", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", "shopify@vizez.cloud")
WHOLESALE_EMAIL = os.getenv("WHOLESALE_EMAIL", "team@yourdomain.com")


def send_wholesale_alert(lead: dict) -> bool:
    """
    Send a wholesale inquiry notification email via Resend.
    Returns True on success, False on failure.
    """
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8" />
      <style>
        body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 20px; }}
        .card {{ background: #fff; border-radius: 8px; padding: 32px; max-width: 520px;
                 margin: 0 auto; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        h2 {{ color: #1a1a2e; margin-top: 0; }}
        .badge {{ display: inline-block; background: #f0fdf4; color: #16a34a;
                  border: 1px solid #bbf7d0; border-radius: 20px; padding: 4px 12px;
                  font-size: 13px; font-weight: 600; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
        td:first-child {{ color: #666; width: 140px; font-weight: 500; }}
        td:last-child {{ color: #1a1a1a; font-weight: 600; }}
        .footer {{ color: #999; font-size: 12px; margin-top: 24px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>🛍️ New Wholesale Inquiry</h2>
        <span class="badge">Wholesale Lead</span>
        <table>
          <tr><td>Business</td><td>{lead.get('business_name') or '—'}</td></tr>
          <tr><td>Contact Name</td><td>{lead.get('name') or '—'}</td></tr>
          <tr><td>Email</td><td>{lead.get('email') or '—'}</td></tr>
          <tr><td>Phone</td><td>{lead.get('phone') or '—'}</td></tr>
          <tr><td>Session ID</td><td><code style="font-size:12px">{lead.get('session_id') or '—'}</code></td></tr>
          <tr><td>Notes</td><td>{lead.get('notes') or '—'}</td></tr>
          <tr><td>Received At</td><td>{timestamp}</td></tr>
        </table>
        <div class="footer">Sent by your Shopify Support Chatbot · shopify.projekts.pk</div>
      </div>
    </body>
    </html>
    """

    text_body = (
        f"New Wholesale Inquiry\n"
        f"{'='*40}\n"
        f"Business:   {lead.get('business_name') or '—'}\n"
        f"Name:       {lead.get('name') or '—'}\n"
        f"Email:      {lead.get('email') or '—'}\n"
        f"Phone:      {lead.get('phone') or '—'}\n"
        f"Notes:      {lead.get('notes') or '—'}\n"
        f"Received:   {timestamp}\n"
    )

    try:
        params = {
            "from": f"Shopify Chatbot <{EMAIL_FROM}>",
            "to": [WHOLESALE_EMAIL],
            "subject": f"🛍️ Wholesale Inquiry — {lead.get('business_name') or lead.get('name', 'Unknown')}",
            "html": html_body,
            "text": text_body,
        }
        resend.Emails.send(params)
        print(f"[Email] Wholesale alert sent to {WHOLESALE_EMAIL}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send wholesale alert: {e}")
        return False


def send_general_lead_alert(lead: dict) -> bool:
    """
    Send a general lead notification (non-wholesale).
    """
    timestamp = datetime.now().strftime("%d %b %Y, %I:%M %p")

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8" />
      <style>
        body {{ font-family: Arial, sans-serif; background: #f4f4f4; margin: 0; padding: 20px; }}
        .card {{ background: #fff; border-radius: 8px; padding: 32px; max-width: 520px;
                 margin: 0 auto; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
        h2 {{ color: #1a1a2e; margin-top: 0; }}
        .badge {{ display: inline-block; background: #eff6ff; color: #2563eb;
                  border: 1px solid #bfdbfe; border-radius: 20px; padding: 4px 12px;
                  font-size: 13px; font-weight: 600; margin-bottom: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
        td {{ padding: 10px 8px; border-bottom: 1px solid #f0f0f0; font-size: 14px; }}
        td:first-child {{ color: #666; width: 140px; font-weight: 500; }}
        td:last-child {{ color: #1a1a1a; font-weight: 600; }}
        .footer {{ color: #999; font-size: 12px; margin-top: 24px; text-align: center; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>💬 New Customer Lead</h2>
        <span class="badge">{(lead.get('inquiry_type') or 'General').title()}</span>
        <table>
          <tr><td>Name</td><td>{lead.get('name') or '—'}</td></tr>
          <tr><td>Email</td><td>{lead.get('email') or '—'}</td></tr>
          <tr><td>Phone</td><td>{lead.get('phone') or '—'}</td></tr>
          <tr><td>Notes</td><td>{lead.get('notes') or '—'}</td></tr>
          <tr><td>Received At</td><td>{timestamp}</td></tr>
        </table>
        <div class="footer">Sent by your Shopify Support Chatbot · shopify.projekts.pk</div>
      </div>
    </body>
    </html>
    """

    try:
        params = {
            "from": f"Shopify Chatbot <{EMAIL_FROM}>",
            "to": [WHOLESALE_EMAIL],
            "subject": f"💬 New Lead — {lead.get('name', 'Unknown Customer')}",
            "html": html_body,
        }
        resend.Emails.send(params)
        print(f"[Email] General lead alert sent to {WHOLESALE_EMAIL}")
        return True
    except Exception as e:
        print(f"[Email] Failed to send lead alert: {e}")
        return False

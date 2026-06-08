"""
main.py — FastAPI application: chat endpoint, lead endpoint, widget serving.
"""

import json
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAI
from pydantic import BaseModel
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

load_dotenv()

import chat_history
import leads as leads_db
import shopify as shopify_api
from email_notify import send_general_lead_alert, send_wholesale_alert
from prompts import build_system_prompt

# ─── Config ──────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

WIDGET_DIR = Path(__file__).parent / "widget"

# ─── Rate Limiter ─────────────────────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[Startup] Initialising SQLite database…")
    leads_db.init_db()
    print("[Startup] Ready ✅")
    yield
    print("[Shutdown] Goodbye.")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Shopify Support Chatbot",
    description="AI-powered customer support with live Shopify data",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Models ──────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    session_id: str
    message: str


class LeadRequest(BaseModel):
    session_id: str
    name: str
    email: str = ""
    phone: str = ""
    business_name: str = ""
    inquiry_type: str = "general"
    notes: str = ""


# ─── Lead Extraction ─────────────────────────────────────────────────────────

_LEAD_PATTERN = re.compile(
    r"\[LEAD_DATA\]\s*(\{.*?\})\s*\[/LEAD_DATA\]",
    re.DOTALL,
)


def _extract_and_strip_lead(text: str) -> tuple[str, dict | None]:
    """
    Strip [LEAD_DATA]…[/LEAD_DATA] block from the bot reply.
    Returns (clean_reply, lead_dict_or_None).
    """
    match = _LEAD_PATTERN.search(text)
    if not match:
        return text, None

    clean_text = _LEAD_PATTERN.sub("", text).strip()
    try:
        lead_data = json.loads(match.group(1))
        return clean_text, lead_data
    except json.JSONDecodeError:
        return clean_text, None


async def _save_extracted_lead(session_id: str, lead_data: dict):
    """Persist the lead and fire the appropriate email alert."""
    result = leads_db.save_lead(
        session_id=session_id,
        name=lead_data.get("name", ""),
        email=lead_data.get("email", ""),
        phone=lead_data.get("phone", ""),
        business_name=lead_data.get("business_name", ""),
        inquiry_type=lead_data.get("inquiry_type", "general"),
        notes=lead_data.get("notes", ""),
    )
    if result["success"]:
        lead_data["session_id"] = session_id
        if lead_data.get("inquiry_type") == "wholesale":
            send_wholesale_alert(lead_data)
        else:
            send_general_lead_alert(lead_data)
        print(f"[Lead] Saved lead #{result['id']} for session {session_id}")
    else:
        print(f"[Lead] Failed to save: {result['error']}")


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"status": "ok", "message": "Shopify Chatbot API is running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/debug/shopify")
async def debug_shopify():
    """Debug endpoint — shows raw Shopify API response to diagnose product fetching issues."""
    import requests as req
    store_url = os.getenv("SHOPIFY_STORE_URL", "NOT SET")
    token = os.getenv("SHOPIFY_ACCESS_TOKEN", "NOT SET")
    token_preview = token[:8] + "..." if token != "NOT SET" else "NOT SET"

    url = f"https://{store_url}/admin/api/2026-04/products.json?limit=5"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    try:
        resp = req.get(url, headers=headers, timeout=10)
        return {
            "store_url": store_url,
            "token_preview": token_preview,
            "status_code": resp.status_code,
            "url_called": url,
            "response": resp.json(),
        }
    except Exception as e:
        return {
            "store_url": store_url,
            "token_preview": token_preview,
            "error": str(e),
            "url_called": url,
        }


@app.post("/chat")
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest):
    session_id = body.session_id.strip()
    user_message = body.message.strip()

    if not session_id or not user_message:
        raise HTTPException(status_code=400, detail="session_id and message are required")

    if len(user_message) > 2000:
        raise HTTPException(status_code=400, detail="Message too long (max 2000 chars)")

    # 1. Fetch live Shopify data (cached 5 min)
    products = shopify_api.fetch_products()
    locations = shopify_api.fetch_locations()

    # 2. Build system prompt
    system_prompt = build_system_prompt(products, locations)

    # 3. Get conversation history
    history = chat_history.get_history(session_id)

    # 4. Save user message to history
    chat_history.add_message(session_id, "user", user_message)

    # 5. Build messages for OpenAI
    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": user_message}
    ]

    # 6. Call OpenAI GPT-4o
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=800,
            temperature=0.7,
        )
        raw_reply = response.choices[0].message.content or ""
    except Exception as e:
        print(f"[OpenAI] Error: {e}")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")

    # 7. Extract lead data if present
    clean_reply, lead_data = _extract_and_strip_lead(raw_reply)

    # 8. Save assistant reply to history
    chat_history.add_message(session_id, "assistant", clean_reply)

    # 9. Persist lead if extracted
    if lead_data and lead_data.get("name"):
        await _save_extracted_lead(session_id, lead_data)

    return {"reply": clean_reply}


@app.post("/lead")
async def save_lead_endpoint(body: LeadRequest):
    """Manually save a lead (e.g. from a separate form submission)."""
    result = leads_db.save_lead(
        session_id=body.session_id,
        name=body.name,
        email=body.email,
        phone=body.phone,
        business_name=body.business_name,
        inquiry_type=body.inquiry_type,
        notes=body.notes,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    # Fire email alert
    lead_dict = body.model_dump()
    if body.inquiry_type == "wholesale":
        send_wholesale_alert(lead_dict)
    else:
        send_general_lead_alert(lead_dict)

    return {"success": True, "lead_id": result["id"]}


@app.get("/leads")
async def list_leads(limit: int = 50):
    """Admin endpoint — returns recent leads."""
    return {"leads": leads_db.get_leads(limit=limit)}


@app.get("/widget.js")
async def serve_widget_js():
    path = WIDGET_DIR / "widget.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="widget.js not found")
    return FileResponse(path, media_type="application/javascript")


@app.get("/widget.css")
async def serve_widget_css():
    path = WIDGET_DIR / "widget.css"
    if not path.exists():
        raise HTTPException(status_code=404, detail="widget.css not found")
    return FileResponse(path, media_type="text/css")

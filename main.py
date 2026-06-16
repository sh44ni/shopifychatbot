"""
main.py — FastAPI application: chat endpoint, lead endpoint, widget serving.
"""

import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

_START_TIME = time.time()

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
from email_notify import (
    send_general_lead_alert,
    send_wholesale_alert,
    send_case_alert,
    send_customer_case_confirmation,
    send_lead_confirmation,
)
from prompts import build_system_prompt

# ─── Config ──────────────────────────────────────────────────────────────────

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

WIDGET_DIR    = Path(__file__).parent / "widget"
DASHBOARD_DIR = Path(__file__).parent / "dashboard"

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_products",
            "description": "Fetch the live product catalogue from the Nata Bakery Shopify store, including names, prices, availability, and descriptions.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stockists",
            "description": "Fetch all active NZ stockist locations for Nata Portuguese Bakery — including Farro Fresh, Woolworths, New World, Moore Wilson, and many independent cafes and delis across New Zealand.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lookup_order",
            "description": "Look up a customer order by order number (e.g. #1042) or email address.",
            "parameters": {
                "type": "object",
                "properties": {
                    "identifier": {
                        "type": "string",
                        "description": "The order number (e.g. '1042' or '#1042') or customer email address",
                    }
                },
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_support_ticket",
            "description": (
                "Create a support ticket / complaint case for a customer. "
                "Call this whenever a customer: complains, reports a problem, requests a refund, "
                "is unhappy with a product or delivery, or explicitly asks to raise a complaint or ticket. "
                "Collect name + (email or phone) + a brief subject and description before calling this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name":        {"type": "string", "description": "Customer's full name"},
                    "email":       {"type": "string", "description": "Customer's email address (preferred)"},
                    "phone":       {"type": "string", "description": "Customer's phone number"},
                    "subject":     {"type": "string", "description": "Short one-line subject of the complaint"},
                    "description": {"type": "string", "description": "Full description of the issue as described by the customer"},
                    "session_id":  {"type": "string", "description": "The current chat session ID"},
                },
                "required": ["name", "subject", "description"],
            },
        },
    },
]

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
    title="Nata Portuguese Bakery AI Chat",
    description="AI-powered customer support for Nata Portuguese Bakery",
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
        if lead_data.get("email"):
            send_lead_confirmation(
                name=lead_data.get("name", ""),
                to_email=lead_data["email"],
            )
        print(f"[Lead] Saved lead #{result['id']} for session {session_id}")
    else:
        print(f"[Lead] Failed to save: {result['error']}")


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    path = DASHBOARD_DIR / "status.html"
    if path.exists():
        return FileResponse(path, media_type="text/html")
    return {"status": "ok", "message": "Nata Portuguese Bakery AI Chat API"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/api/public-stats")
async def public_stats():
    """Public stats — no auth required, contains no sensitive customer data."""
    import sqlite3
    from datetime import datetime
    db = os.getenv("LEADS_DB", "leads.db")
    today = datetime.now().strftime("%Y-%m-%d")
    uptime = int(time.time() - _START_TIME)
    try:
        with sqlite3.connect(db) as conn:
            total_messages = conn.execute(
                "SELECT COUNT(*) FROM chat_history"
            ).fetchone()[0]
            messages_today = conn.execute(
                "SELECT COUNT(*) FROM chat_history WHERE DATE(timestamp)=?", (today,)
            ).fetchone()[0]
            total_sessions = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM chat_history"
            ).fetchone()[0]
        return {
            "status": "online",
            "total_messages": total_messages,
            "messages_today": messages_today,
            "total_sessions": total_sessions,
            "uptime_seconds": uptime,
        }
    except Exception:
        return {
            "status": "online",
            "total_messages": 0,
            "messages_today": 0,
            "total_sessions": 0,
            "uptime_seconds": uptime,
        }


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


@app.get("/debug/locations")
async def debug_locations():
    """Debug endpoint — shows raw Shopify locations and what the cache holds."""
    import requests as req
    store_url = os.getenv("SHOPIFY_STORE_URL", "NOT SET")
    token = shopify_api._get_access_token()
    token_preview = token[:8] + "..." if token else "NOT SET"

    url = f"https://{store_url}/admin/api/2026-04/locations.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    try:
        resp = req.get(url, headers=headers, timeout=10)
        raw = resp.json()
        # Also show what fetch_locations() returns (cached)
        cached = shopify_api.fetch_locations()
        return {
            "store_url": store_url,
            "token_preview": token_preview,
            "status_code": resp.status_code,
            "url_called": url,
            "raw_response": raw,
            "raw_count": len(raw.get("locations", [])),
            "cached_locations": cached,
            "cached_count": len(cached),
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

    # 1. Build system prompt
    system_prompt = build_system_prompt()

    # 2. Get conversation history
    history = chat_history.get_history(session_id)

    # 3. Save user message to history
    chat_history.add_message(session_id, "user", user_message)

    # 4. Build messages for OpenAI
    messages = [{"role": "system", "content": system_prompt}] + history + [
        {"role": "user", "content": user_message}
    ]

    # 5. Call OpenAI GPT-4o with tool calling loop
    raw_reply = ""
    try:
        for _ in range(3):  # Max 3 iterations for safety
            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                tools=TOOLS,
                max_tokens=800,
                temperature=0.7,
            )
            response_message = response.choices[0].message
            
            if response_message.tool_calls:
                message_dict = {
                    "role": response_message.role,
                    "content": response_message.content,
                    "tool_calls": [
                        {
                            "id": t.id,
                            "type": t.type,
                            "function": {
                                "name": t.function.name,
                                "arguments": t.function.arguments
                            }
                        } for t in response_message.tool_calls
                    ]
                }
                messages.append(message_dict)
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    print(f"[Tool] {function_name} called")
                    
                    if function_name == "get_products":
                        results = shopify_api.fetch_products()
                    elif function_name == "get_stockists":
                        results = shopify_api.fetch_stockists()
                    elif function_name == "lookup_order":
                        args = json.loads(tool_call.function.arguments)
                        results = shopify_api.fetch_order(args.get("identifier", ""))
                    elif function_name == "create_support_ticket":
                        args = json.loads(tool_call.function.arguments)
                        case_result = leads_db.save_case(
                            name=args.get("name", ""),
                            email=args.get("email", ""),
                            phone=args.get("phone", ""),
                            subject=args.get("subject", ""),
                            description=args.get("description", ""),
                            session_id=args.get("session_id", session_id),
                        )
                        if case_result.get("success"):
                            case_id = case_result["case_id"]
                            print(f"[Case] Created {case_id} for {args.get('name')}")
                            # Fire team + customer emails in background
                            case_data = {
                                "case_id":     case_id,
                                "name":        args.get("name"),
                                "email":       args.get("email"),
                                "phone":       args.get("phone"),
                                "subject":     args.get("subject"),
                                "description": args.get("description"),
                            }
                            send_case_alert(case_data)
                            if args.get("email"):
                                send_customer_case_confirmation(
                                    name=args.get("name"),
                                    to_email=args.get("email"),
                                    case_id=case_id,
                                    subject=args.get("subject"),
                                )
                            results = {"success": True, "case_id": case_id,
                                       "message": f"Support ticket {case_id} created successfully."}
                        else:
                            results = {"success": False, "error": case_result.get("error", "Unknown error")}
                    else:
                        results = {"error": f"Unknown function: {function_name}"}
                    
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": function_name,
                        "content": json.dumps(results)
                    })
            else:
                raw_reply = response_message.content or ""
                break
    except Exception as e:
        print(f"[OpenAI] Error: {e}")
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")

    # 6. Extract lead data if present
    clean_reply, lead_data = _extract_and_strip_lead(raw_reply)

    # 7. Save assistant reply to history
    chat_history.add_message(session_id, "assistant", clean_reply)

    # 8. Persist lead if extracted
    if lead_data and lead_data.get("name"):
        await _save_extracted_lead(session_id, lead_data)

    return {"reply": clean_reply}


# ─── Support Cases ────────────────────────────────────────────────────────────

class CaseRequest(BaseModel):
    name: str
    email: str = ""
    phone: str = ""
    subject: str = ""
    description: str = ""
    session_id: str = ""


@app.post("/api/cases")
async def create_case(body: CaseRequest):
    """Submit a support case — public endpoint (called from widget or dashboard form)."""
    result = leads_db.save_case(
        name=body.name,
        email=body.email,
        phone=body.phone,
        subject=body.subject,
        description=body.description,
        session_id=body.session_id,
    )
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])

    case = leads_db.get_case(result["case_id"])
    # Fire team + customer emails
    if case:
        send_case_alert(case)
        if body.email:
            send_customer_case_confirmation(
                name=body.name,
                to_email=body.email,
                case_id=result["case_id"],
                subject=body.subject,
            )

    return {"success": True, "case_id": result["case_id"], "id": result["id"]}


@app.get("/api/cases")
async def api_get_cases(request: Request, limit: int = 100, status: str = ""):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import sqlite3 as _sqlite3
    db = os.getenv("LEADS_DB", "leads.db")
    try:
        with _sqlite3.connect(db) as conn:
            conn.row_factory = _sqlite3.Row
            query = "SELECT * FROM support_cases"
            params: list = []
            if status:
                query += " WHERE status=?"
                params.append(status)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = conn.execute(query, params).fetchall()
            total_q = "SELECT COUNT(*) FROM support_cases"
            total_p: list = []
            if status:
                total_q += " WHERE status=?"
                total_p.append(status)
            total = conn.execute(total_q, total_p).fetchone()[0]
        return {"cases": [dict(r) for r in rows], "total": total}
    except Exception as e:
        return {"error": str(e)}


@app.patch("/api/cases/{case_id}")
async def update_case(case_id: str, request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    body = await request.json()
    new_status = body.get("status", "")
    notes = body.get("notes", "")
    ok = leads_db.update_case_status(case_id, new_status, notes)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid status or case not found")
    return {"success": True}


# ─── Order Lookup ─────────────────────────────────────────────────────────────

@app.get("/api/orders/lookup")
async def order_lookup(request: Request, q: str = ""):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")
    import shopify as shopify_api_module
    order = shopify_api_module.fetch_order(q.strip())
    if not order:
        return {"found": False, "order": None}
    return {"found": True, "order": order}


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


# ─── Dashboard ────────────────────────────────────────────────────────────────

DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "admin123")


def _check_auth(request: Request) -> bool:
    """Simple token auth: ?token=xxx or Authorization: Bearer xxx header."""
    token = request.query_params.get("token", "")
    if token == DASHBOARD_PASSWORD:
        return True
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer ") and auth_header[7:] == DASHBOARD_PASSWORD:
        return True
    return False


@app.get("/dashboard")
async def serve_dashboard():
    path = DASHBOARD_DIR / "index.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    return FileResponse(path, media_type="text/html")


@app.get("/api/analytics")
async def api_analytics(request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import sqlite3
    from datetime import datetime, timedelta
    db = os.getenv("LEADS_DB", "leads.db")
    today = datetime.now().strftime("%Y-%m-%d")
    week_ago = (datetime.now() - timedelta(days=6)).strftime("%Y-%m-%d")
    try:
        with sqlite3.connect(db) as conn:
            total_leads     = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
            wholesale_leads = conn.execute("SELECT COUNT(*) FROM leads WHERE inquiry_type='wholesale'").fetchone()[0]
            general_leads   = conn.execute("SELECT COUNT(*) FROM leads WHERE inquiry_type!='wholesale'").fetchone()[0]
            leads_today     = conn.execute("SELECT COUNT(*) FROM leads WHERE DATE(created_at)=?", (today,)).fetchone()[0]
            total_messages  = conn.execute("SELECT COUNT(*) FROM chat_history").fetchone()[0]
            msgs_today      = conn.execute("SELECT COUNT(*) FROM chat_history WHERE DATE(timestamp)=?", (today,)).fetchone()[0]
            total_sessions  = conn.execute("SELECT COUNT(DISTINCT session_id) FROM chat_history").fetchone()[0]
            # Daily leads for last 7 days
            daily_rows = conn.execute(
                """SELECT DATE(created_at) as day, COUNT(*) as cnt
                   FROM leads WHERE DATE(created_at) >= ?
                   GROUP BY day ORDER BY day""",
                (week_ago,)
            ).fetchall()
            # Inquiry type breakdown
            type_rows = conn.execute(
                "SELECT inquiry_type, COUNT(*) FROM leads GROUP BY inquiry_type"
            ).fetchall()
            # Cases stats
            total_cases  = conn.execute("SELECT COUNT(*) FROM support_cases").fetchone()[0]
            cases_open   = conn.execute("SELECT COUNT(*) FROM support_cases WHERE status='open'").fetchone()[0]
            cases_today  = conn.execute("SELECT COUNT(*) FROM support_cases WHERE DATE(created_at)=?", (today,)).fetchone()[0]
            case_status_rows = conn.execute(
                "SELECT status, COUNT(*) FROM support_cases GROUP BY status"
            ).fetchall()
        return {
            "total_leads":     total_leads,
            "wholesale_leads": wholesale_leads,
            "general_leads":   general_leads,
            "leads_today":     leads_today,
            "total_messages":  total_messages,
            "messages_today":  msgs_today,
            "total_sessions":  total_sessions,
            "total_cases":     total_cases,
            "cases_open":      cases_open,
            "cases_today":     cases_today,
            "daily_leads":     [{"day": r[0], "count": r[1]} for r in daily_rows],
            "lead_types":      [{"type": r[0], "count": r[1]} for r in type_rows],
            "case_statuses":   [{"status": r[0], "count": r[1]} for r in case_status_rows],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/leads")
async def api_leads(request: Request, limit: int = 100, offset: int = 0, type: str = ""):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import sqlite3
    db = os.getenv("LEADS_DB", "leads.db")
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            if type:
                rows = conn.execute(
                    "SELECT * FROM leads WHERE inquiry_type=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (type, limit, offset)
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) FROM leads WHERE inquiry_type=?", (type,)).fetchone()[0]
            else:
                rows = conn.execute(
                    "SELECT * FROM leads ORDER BY created_at DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ).fetchall()
                total = conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        return {"leads": [dict(r) for r in rows], "total": total}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/chat-history")
async def api_chat_sessions(request: Request, limit: int = 50, offset: int = 0):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import sqlite3
    db = os.getenv("LEADS_DB", "leads.db")
    try:
        with sqlite3.connect(db) as conn:
            rows = conn.execute(
                """SELECT session_id,
                          COUNT(*) as message_count,
                          MIN(timestamp) as started_at,
                          MAX(timestamp) as last_message
                   FROM chat_history
                   GROUP BY session_id
                   ORDER BY last_message DESC
                   LIMIT ? OFFSET ?""",
                (limit, offset)
            ).fetchall()
            total = conn.execute("SELECT COUNT(DISTINCT session_id) FROM chat_history").fetchone()[0]
        return {
            "sessions": [
                {"session_id": r[0], "message_count": r[1],
                 "started_at": r[2], "last_message": r[3]}
                for r in rows
            ],
            "total": total,
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/chat-history/{session_id}")
async def api_chat_thread(session_id: str, request: Request):
    if not _check_auth(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
    import sqlite3
    db = os.getenv("LEADS_DB", "leads.db")
    try:
        with sqlite3.connect(db) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT role, content, timestamp FROM chat_history WHERE session_id=? ORDER BY timestamp ASC",
                (session_id,)
            ).fetchall()
        return {"session_id": session_id, "messages": [dict(r) for r in rows]}
    except Exception as e:
        return {"error": str(e)}


"""
shopify.py — Shopify Admin REST API wrapper with 5-minute in-memory cache.
"""

import os
import time
import html
import re
import requests
from dotenv import load_dotenv

load_dotenv()

SHOPIFY_STORE_URL   = os.getenv("SHOPIFY_STORE_URL", "")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_CLIENT_ID   = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")

BASE_URL = f"https://{SHOPIFY_STORE_URL}/admin/api/2026-04"

CACHE_TTL = 300  # 5 minutes
_cache: dict = {}
_token_cache: dict = {}   # { "token": str, "expires_at": float }


def _get_access_token() -> str:
    """
    Returns a valid Admin API access token.
    - If SHOPIFY_ACCESS_TOKEN is set in .env, use it directly.
    - Otherwise, fetch one via Client Credentials (Client ID + Secret).
    """
    # Static token takes priority
    if SHOPIFY_ACCESS_TOKEN and not SHOPIFY_ACCESS_TOKEN.startswith("atkn_"):
        return SHOPIFY_ACCESS_TOKEN

    # Check cached token (expires_at - 60s buffer)
    if _token_cache.get("token") and time.time() < _token_cache.get("expires_at", 0) - 60:
        return _token_cache["token"]

    # Fetch new token via client credentials
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("[Shopify] No valid access token or client credentials found in .env")
        return SHOPIFY_ACCESS_TOKEN  # fallback even if atkn_

    try:
        resp = requests.post(
            f"https://{SHOPIFY_STORE_URL}/admin/oauth/access_token",
            json={
                "grant_type":    "client_credentials",
                "client_id":     SHOPIFY_CLIENT_ID,
                "client_secret": SHOPIFY_CLIENT_SECRET,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        token = data.get("access_token", "")
        expires_in = data.get("expires_in", 3600)
        _token_cache["token"] = token
        _token_cache["expires_at"] = time.time() + expires_in
        print(f"[Shopify] Fetched new access token via client credentials (expires in {expires_in}s)")
        return token
    except Exception as e:
        print(f"[Shopify] Failed to fetch token via client credentials: {e}")
        return SHOPIFY_ACCESS_TOKEN


def _get_headers() -> dict:
    return {
        "X-Shopify-Access-Token": _get_access_token(),
        "Content-Type": "application/json",
    }



def _is_fresh(key: str) -> bool:
    if key not in _cache:
        return False
    _, ts = _cache[key]
    return (time.time() - ts) < CACHE_TTL


def _strip_html(raw: str) -> str:
    """Remove HTML tags and decode entities from Shopify body_html."""
    clean = re.sub(r"<[^>]+>", " ", raw or "")
    clean = html.unescape(clean)
    return re.sub(r"\s+", " ", clean).strip()


# ─── Products ────────────────────────────────────────────────────────────────

def fetch_products() -> list[dict]:
    """Return formatted product list, cached for 5 minutes."""
    if _is_fresh("products"):
        return _cache["products"][0]

    try:
        resp = requests.get(f"{BASE_URL}/products.json?limit=250", headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        raw_products = resp.json().get("products", [])
    except Exception as e:
        print(f"[Shopify] Error fetching products: {e}")
        # Return cached stale data if available, else empty
        return _cache.get("products", ([], 0))[0]

    products = []
    for p in raw_products:
        # Lowest variant price
        prices = [float(v.get("price", 0)) for v in p.get("variants", []) if v.get("price")]
        min_price = min(prices) if prices else None

        products.append({
            "title": p.get("title", ""),
            "description": _strip_html(p.get("body_html", "")),
            "price": f"NZD {min_price:.2f}" if min_price else "Price on request",
            "tags": p.get("tags", ""),
            "available": any(
                v.get("inventory_quantity", 1) > 0
                for v in p.get("variants", [])
            ),
        })

    _cache["products"] = (products, time.time())
    return products


# ─── Locations ───────────────────────────────────────────────────────────────

def fetch_locations() -> list[dict]:
    """Return active store locations, cached for 5 minutes."""
    if _is_fresh("locations"):
        return _cache["locations"][0]

    try:
        resp = requests.get(f"{BASE_URL}/locations.json", headers=_get_headers(), timeout=10)
        resp.raise_for_status()
        raw_locs = resp.json().get("locations", [])
    except Exception as e:
        print(f"[Shopify] Error fetching locations: {e}")
        return _cache.get("locations", ([], 0))[0]

    locations = []
    for loc in raw_locs:
        if not loc.get("active", False):
            continue
        locations.append({
            "name": loc.get("name", ""),
            "address": loc.get("address1", ""),
            "city": loc.get("city", ""),
            "phone": loc.get("phone", ""),
        })

    _cache["locations"] = (locations, time.time())
    return locations


# ─── Order Lookup ────────────────────────────────────────────────────────────

def _format_order(o: dict) -> dict:
    return {
        "order_number": o.get("order_number"),
        "name": o.get("name"),
        "email": o.get("email"),
        "financial_status": o.get("financial_status"),
        "fulfillment_status": o.get("fulfillment_status") or "unfulfilled",
        "total_price": o.get("total_price"),
        "currency": o.get("currency", "NZD"),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "note": o.get("note", ""),
        "line_items": [
            {
                "title": item.get("title"),
                "variant_title": item.get("variant_title", ""),
                "quantity": item.get("quantity"),
                "price": item.get("price"),
            }
            for item in o.get("line_items", [])
        ],
        "shipping_address": {
            "name":    o.get("shipping_address", {}).get("name", ""),
            "address": o.get("shipping_address", {}).get("address1", ""),
            "city":    o.get("shipping_address", {}).get("city", ""),
            "country": o.get("shipping_address", {}).get("country", ""),
        } if o.get("shipping_address") else None,
        "fulfillments": [
            {
                "status":          f.get("status"),
                "tracking_number": f.get("tracking_number"),
                "tracking_url":    f.get("tracking_url"),
                "updated_at":      f.get("updated_at"),
            }
            for f in o.get("fulfillments", [])
        ],
    }


def fetch_order(identifier: str) -> dict | None:
    """
    Look up a Shopify order by order number (e.g. "1001" or "#1001") or email.
    Returns a formatted order dict or None if not found.
    """
    identifier = identifier.strip()
    clean_id = identifier.lstrip("#").strip()

    headers = _get_headers()

    # Search by order name / number
    try:
        resp = requests.get(
            f"{BASE_URL}/orders.json",
            params={"name": clean_id, "status": "any", "limit": 1},
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        orders = resp.json().get("orders", [])
        if orders:
            return _format_order(orders[0])
    except Exception as e:
        print(f"[Shopify] Order lookup by name failed: {e}")

    # Fall back to email search
    if "@" in identifier:
        try:
            resp = requests.get(
                f"{BASE_URL}/orders.json",
                params={"email": identifier, "status": "any", "limit": 5},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            orders = resp.json().get("orders", [])
            if orders:
                return _format_order(orders[0])
        except Exception as e:
            print(f"[Shopify] Order lookup by email failed: {e}")

    return None


# ─── Inventory (optional) ────────────────────────────────────────────────────

def fetch_inventory(location_id: str) -> list[dict]:
    """Fetch inventory levels for a given location (not cached — call sparingly)."""
    try:
        resp = requests.get(
            f"{BASE_URL}/inventory_levels.json?location_ids={location_id}",
            headers=_get_headers(),
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("inventory_levels", [])
    except Exception as e:
        print(f"[Shopify] Error fetching inventory: {e}")
        return []

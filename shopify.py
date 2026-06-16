"""
shopify.py — Shopify Admin REST API wrapper with 5-minute in-memory cache.
"""

import os
import time
import html
import re
import xml.etree.ElementTree as ET
import requests
from dotenv import load_dotenv

load_dotenv()

SHOPIFY_STORE_URL   = os.getenv("SHOPIFY_STORE_URL", "").removeprefix("https://").removeprefix("http://").rstrip("/")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
SHOPIFY_CLIENT_ID   = os.getenv("SHOPIFY_CLIENT_ID", "")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")

BASE_URL = f"https://{SHOPIFY_STORE_URL}/admin/api/2026-04"

CACHE_TTL = 300  # 5 minutes
STOCKIST_CACHE_TTL = 3600  # 1 hour — stockist list changes rarely
_cache: dict = {}
_token_cache: dict = {}   # { "token": str, "expires_at": float }
_static_token_valid: bool = True  # set to False if static token returns 401

GOOGLE_MAPS_KML_URL = "https://www.google.com/maps/d/kml?mid=1XRweKGpgC6hxKapAX_-TBCPc6sBcSkY&forcekml=1"


def _invalidate_token():
    """Force a fresh token fetch on the next request."""
    global _static_token_valid
    _static_token_valid = False
    _token_cache.clear()
    print("[Shopify] Token invalidated — will fetch fresh on next request")


def _get_access_token() -> str:
    """
    Returns a valid Admin API access token.
    - If SHOPIFY_ACCESS_TOKEN is set in .env and hasn't returned a 401, use it.
    - Otherwise, fetch one via Client Credentials (Client ID + Secret).
    """
    global _static_token_valid

    # Static token takes priority if it hasn't been marked invalid by a 401
    if SHOPIFY_ACCESS_TOKEN and _static_token_valid:
        return SHOPIFY_ACCESS_TOKEN

    # Check cached dynamic token (expires_at - 60s buffer)
    if _token_cache.get("token") and time.time() < _token_cache.get("expires_at", 0) - 60:
        return _token_cache["token"]

    # Fetch new token via client credentials
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        print("[Shopify] No valid access token or client credentials found in .env")
        return SHOPIFY_ACCESS_TOKEN  # fallback

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

def _shopify_get(url: str, **kwargs) -> requests.Response:
    """
    GET with automatic 401 retry: if the first attempt returns 401,
    invalidate the token and retry once with a fresh one.
    """
    resp = requests.get(url, headers=_get_headers(), **kwargs)
    if resp.status_code == 401:
        print(f"[Shopify] 401 received — invalidating token and retrying: {url}")
        _invalidate_token()
        resp = requests.get(url, headers=_get_headers(), **kwargs)
    return resp


def fetch_products() -> list[dict]:
    """Return formatted product list, cached for 5 minutes."""
    if _is_fresh("products"):
        return _cache["products"][0]

    try:
        resp = _shopify_get(f"{BASE_URL}/products.json?limit=250", timeout=10)
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
                v.get("inventory_quantity", 0) > 0
                or v.get("inventory_policy") == "continue"
                or v.get("inventory_management") is None
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
        resp = _shopify_get(f"{BASE_URL}/locations.json", timeout=10)
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


# ─── Stockists (Google My Maps KML) ─────────────────────────────────────────

def fetch_stockists() -> list[dict]:
    """
    Fetch all NZ stockist locations from the public Google My Maps KML feed.
    Grouped by retailer chain (Farro Fresh, Woolworths, etc.).
    Cached for 1 hour since stockist list changes infrequently.
    """
    cache_key = "stockists"
    cached_val = _cache.get(cache_key)
    if cached_val and (time.time() - cached_val[1]) < STOCKIST_CACHE_TTL:
        return cached_val[0]

    try:
        resp = requests.get(GOOGLE_MAPS_KML_URL, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"kml": "http://www.opengis.net/kml/2.2"}

        stockists = []
        document = root.find("kml:Document", ns)
        if document is None:
            document = root

        for folder in document.findall("kml:Folder", ns):
            # Folder name = retailer chain (e.g. "Farro Fresh", "Woolworths")
            folder_name_el = folder.find("kml:name", ns)
            chain = folder_name_el.text.strip() if folder_name_el is not None else "Other"

            for placemark in folder.findall("kml:Placemark", ns):
                name_el = placemark.find("kml:name", ns)
                name = name_el.text.strip() if name_el is not None else chain
                stockists.append({
                    "chain": chain,
                    "name": name,
                })

        _cache[cache_key] = (stockists, time.time())
        print(f"[Stockists] Fetched {len(stockists)} locations from Google My Maps")
        return stockists

    except Exception as e:
        print(f"[Stockists] Error fetching KML: {e}")
        return _cache.get(cache_key, ([], 0))[0]


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
        resp = _shopify_get(
            f"{BASE_URL}/orders.json",
            params={"name": clean_id, "status": "any", "limit": 1},
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
            resp = _shopify_get(
                f"{BASE_URL}/orders.json",
                params={"email": identifier, "status": "any", "limit": 5},
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
        resp = _shopify_get(
            f"{BASE_URL}/inventory_levels.json?location_ids={location_id}",
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("inventory_levels", [])
    except Exception as e:
        print(f"[Shopify] Error fetching inventory: {e}")
        return []

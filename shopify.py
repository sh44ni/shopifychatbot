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

SHOPIFY_STORE_URL = os.getenv("SHOPIFY_STORE_URL", "")
SHOPIFY_ACCESS_TOKEN = os.getenv("SHOPIFY_ACCESS_TOKEN", "")
BASE_URL = f"https://{SHOPIFY_STORE_URL}/admin/api/2024-01"
HEADERS = {"X-Shopify-Access-Token": SHOPIFY_ACCESS_TOKEN, "Content-Type": "application/json"}

CACHE_TTL = 300  # 5 minutes in seconds
_cache: dict = {}


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
        resp = requests.get(f"{BASE_URL}/products.json?limit=250", headers=HEADERS, timeout=10)
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
            "price": f"PKR {min_price:.2f}" if min_price else "Price on request",
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
        resp = requests.get(f"{BASE_URL}/locations.json", headers=HEADERS, timeout=10)
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


# ─── Inventory (optional) ────────────────────────────────────────────────────

def fetch_inventory(location_id: str) -> list[dict]:
    """Fetch inventory levels for a given location (not cached — call sparingly)."""
    try:
        resp = requests.get(
            f"{BASE_URL}/inventory_levels.json?location_ids={location_id}",
            headers=HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("inventory_levels", [])
    except Exception as e:
        print(f"[Shopify] Error fetching inventory: {e}")
        return []

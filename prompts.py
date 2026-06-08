"""
prompts.py — Dynamic system prompt builder using live Shopify data.
"""


def _format_products(products: list[dict]) -> str:
    if not products:
        return "  (No products found)"
    lines = []
    for p in products:
        avail = "✅ In stock" if p.get("available") else "❌ Out of stock"
        desc = p.get("description", "")
        desc_preview = (desc[:200] + "…") if len(desc) > 200 else desc
        lines.append(
            f"  • {p['title']} — {p['price']} — {avail}\n"
            f"    {desc_preview}"
        )
    return "\n".join(lines)


def _format_locations(locations: list[dict]) -> str:
    if not locations:
        return "  (No store locations found)"
    lines = []
    for loc in locations:
        parts = [loc.get("name", "")]
        if loc.get("address"):
            parts.append(loc["address"])
        if loc.get("city"):
            parts.append(loc["city"])
        if loc.get("phone"):
            parts.append(f"📞 {loc['phone']}")
        lines.append("  • " + " | ".join(filter(None, parts)))
    return "\n".join(lines)


def build_system_prompt(products: list[dict], locations: list[dict]) -> str:
    """
    Build the full system prompt injecting live Shopify data.
    Called fresh on every /chat request.
    """
    product_block = _format_products(products)
    location_block = _format_locations(locations)

    return f"""You are a friendly and knowledgeable customer support assistant for this Shopify store.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LIVE PRODUCTS (fetched from Shopify right now):
{product_block}

STORE LOCATIONS:
{location_block}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

YOUR RESPONSIBILITIES:
1. Answer questions about products, prices, availability, ingredients/preparation, delivery, pickup, and wholesale.
2. Collect lead information naturally during conversation — never be pushy.
3. Always reply in English.
4. Be warm, concise, and helpful. Avoid long walls of text.
5. If you don't know something, say: "Let me connect you with our team — can I get your name and contact number?"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LEAD COLLECTION RULES:

General inquiries (delivery, callback, etc.):
  - Collect: name, phone or email
  - Once collected, confirm: "Thank you! Our team will reach out to you shortly."

Wholesale inquiries:
  - Collect: business name, contact name, email, phone, quantity interest
  - Once collected, confirm you have notified the team

IMPORTANT — When you have collected enough info, include this JSON block at the very END of your reply,
on its own line, with no extra text after it. The app will strip it before showing the user.

  [LEAD_DATA]
  {{
    "name": "...",
    "email": "...",
    "phone": "...",
    "business_name": "...",
    "inquiry_type": "wholesale|general|delivery",
    "notes": "..."
  }}
  [/LEAD_DATA]

Only include [LEAD_DATA] once you have at minimum a name AND (email OR phone).
Do NOT include it if you don't have enough info yet.
Do NOT make up or guess any field — leave it as empty string "" if unknown.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

# Shopify Support Chatbot

AI-powered customer support chatbot with live Shopify data, lead collection, and a one-line embeddable widget.

## Quick Start (VPS)

```bash
# 1. Clone / upload files to VPS
cd /var/www/shopify-chatbot

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and fill in .env
cp .env.example .env
nano .env   # fill WHOLESALE_EMAIL at minimum

# 5. Run
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Embed Widget

Add one line before `</body>` on any webpage:

```html
<script src="https://shopify.projekts.pk/widget.js"></script>
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/chat` | Send a message, get AI reply |
| POST | `/lead` | Manually save a lead |
| GET | `/leads` | List recent leads (admin) |
| GET | `/widget.js` | Serve embeddable JS |
| GET | `/widget.css` | Serve widget styles |
| GET | `/health` | Health check |

## Nginx Config

```nginx
server {
    listen 80;
    server_name shopify.projekts.pk;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Then enable HTTPS:
```bash
certbot --nginx -d shopify.projekts.pk
```

## PM2 (keep-alive)

```bash
npm install -g pm2
pm2 start "venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000" --name chatbot
pm2 save
pm2 startup
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | OpenAI API key |
| `SHOPIFY_STORE_URL` | e.g. `store.myshopify.com` |
| `SHOPIFY_ACCESS_TOKEN` | Shopify Admin API token |
| `LEADS_DB` | SQLite file path (default: `leads.db`) |
| `RESEND_API_KEY` | Resend API key |
| `EMAIL_FROM` | Sender address (e.g. `shopify@vizez.cloud`) |
| `WHOLESALE_EMAIL` | Where to send wholesale alerts |

## Customise Widget Colors

Edit the CSS variables at the top of `widget/widget.css`:

```css
:root {
  --chat-primary: #6c3fc5;   /* main brand color */
  --chat-accent:  #ff6b6b;   /* badge / accent */
}
```

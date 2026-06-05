# Telegram clean IP provider bot

`Worker.js` is a Cloudflare Worker that connects a Telegram BotFather bot to a Cloudflare D1 database and the Hugging Face analyzer service.

## Features

- Registers Telegram users and generates a recoverable secret code.
- Accepts scanner submissions with `/submit IP ping jitter latency loss upload download`.
- Enriches submitted IPs with `https://api.ip.sb/geoip/`.
- Stores measurements in D1 and periodically flushes unprocessed rows to the analyzer.
- Returns ranked results with `/top day all all dl`.

## Required Cloudflare bindings and variables

Create a D1 database named `DB` and configure these Worker variables:

- `BOT_TOKEN` — Telegram token from BotFather.
- `WEBHOOK_SECRET` — random path secret used in `/telegram/<secret>`.
- `SECRET_SALT` — secret salt for user recovery codes.
- `ANALYZER_URL` — Hugging Face Space URL, for example `https://example.hf.space`.
- `ANALYZER_TOKEN` — optional bearer token shared with the analyzer.

## D1 schema

```sql
CREATE TABLE users (
  id TEXT PRIMARY KEY,
  username TEXT,
  first_name TEXT,
  last_name TEXT,
  language_code TEXT,
  is_bot INTEGER NOT NULL DEFAULT 0,
  is_premium INTEGER NOT NULL DEFAULT 0,
  secret TEXT NOT NULL,
  added_ips INTEGER NOT NULL DEFAULT 0,
  used_ips INTEGER NOT NULL DEFAULT 0,
  reputation REAL NOT NULL DEFAULT 100,
  banned_until INTEGER NOT NULL DEFAULT 0,
  ban_count INTEGER NOT NULL DEFAULT 0,
  updated_at INTEGER NOT NULL
);

CREATE TABLE measurements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  ip TEXT NOT NULL,
  ping REAL NOT NULL,
  jitter REAL NOT NULL,
  latency REAL NOT NULL,
  loss REAL NOT NULL,
  upload REAL NOT NULL,
  download REAL NOT NULL,
  country TEXT,
  isp TEXT,
  city TEXT,
  organization TEXT,
  created_at INTEGER NOT NULL,
  flushed INTEGER NOT NULL DEFAULT 0
);
```

## BotFather and webhook setup

1. Create a bot with BotFather and copy the token into `BOT_TOKEN`.
2. Deploy the Worker with the D1 binding and variables above.
3. Register the webhook:

```bash
curl "https://api.telegram.org/bot$BOT_TOKEN/setWebhook" \
  -d "url=https://<worker-domain>/telegram/$WEBHOOK_SECRET"
```

4. Add a Cloudflare Cron Trigger such as `*/15 * * * *` so the Worker flushes data to the analyzer every 15 minutes.

---
title: Clean IP Database Analyzer
emoji: 🧹
colorFrom: yellow
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Clean IP Database Analyzer

This Hugging Face Space runs the Pluribus analyzer service for lawful, authorized network testing. It receives clean-IP measurements from the Cloudflare Worker, stores recent rows, caches repeated queries, and returns ranked Cloudflare IP candidates.

## Endpoints

- `GET /health` — service health check.
- `POST /ingest` — accepts `{ "measurements": [...] }` batches. Set `ANALYZER_TOKEN` and send `Authorization: Bearer <token>` for protected deployments.
- `GET /top?window=day&isp=all&city=all&metric=dl&limit=10` — returns ranked IPs.

## Ranking fields

Supported time windows are `4h`, `day`, and `week`. Supported metrics are `ping`, `jitter`, `latency`, `loss`, `dl`, and `ul`.

## Deployment

1. Create a Docker Space on Hugging Face.
2. Upload `Analyzer_bot.py`, `Dockerfile`, and this readme.
3. Add `ANALYZER_TOKEN` as a Space secret when you want authenticated ingestion.
4. Point the Cloudflare Worker `ANALYZER_URL` setting at the Space URL.

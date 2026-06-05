"""Hugging Face Space analyzer for the Pluribus clean IP database.

The service accepts batches from the Cloudflare Worker, enriches and aggregates
recent measurements, and exposes ranked results by time window, ISP, city, and
metric. It stores state in local JSON files so it works on a free Docker Space;
mount persistent storage for production use.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

from flask import Flask, jsonify, request

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
RAW_DB = DATA_DIR / "measurements.jsonl"
CACHE_DB = DATA_DIR / "cache.json"
MAX_CACHE_AGE_SECONDS = int(os.environ.get("MAX_CACHE_AGE_SECONDS", "900"))
MAX_ROWS = int(os.environ.get("MAX_ROWS", "250000"))
ADMIN_TOKEN = os.environ.get("ANALYZER_TOKEN", "")

app = Flask(__name__)


@dataclass(slots=True)
class Measurement:
    ip: str
    user_id: str
    timestamp: int
    ping: float
    jitter: float
    latency: float
    loss: float
    upload: float
    download: float
    country: str = ""
    isp: str = ""
    city: str = ""
    organization: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Measurement":
        geo = payload.get("geo") or {}
        return cls(
            ip=str(payload["ip"]),
            user_id=str(payload.get("user_id", "anonymous")),
            timestamp=int(payload.get("timestamp") or time.time()),
            ping=float(payload.get("ping", 0)),
            jitter=float(payload.get("jitter", 0)),
            latency=float(payload.get("latency", 0)),
            loss=float(payload.get("loss", payload.get("packet_loss", 0))),
            upload=float(payload.get("upload", 0)),
            download=float(payload.get("download", 0)),
            country=str(payload.get("country") or geo.get("country", "")),
            isp=str(payload.get("isp") or geo.get("isp", "")),
            city=str(payload.get("city") or geo.get("city", "")),
            organization=str(payload.get("organization") or geo.get("organization", "")),
        )


def require_token() -> tuple[bool, Any]:
    if not ADMIN_TOKEN:
        return True, None
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token != ADMIN_TOKEN:
        return False, (jsonify({"error": "unauthorized"}), 401)
    return True, None


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DB.touch(exist_ok=True)


def append_measurements(rows: Iterable[Measurement]) -> int:
    ensure_data_dir()
    count = 0
    with RAW_DB.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(asdict(row), separators=(",", ":")) + "\n")
            count += 1
    compact_if_needed()
    CACHE_DB.unlink(missing_ok=True)
    return count


def iter_measurements() -> Iterable[Measurement]:
    ensure_data_dir()
    with RAW_DB.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield Measurement(**json.loads(line))


def compact_if_needed() -> None:
    lines = RAW_DB.read_text(encoding="utf-8").splitlines() if RAW_DB.exists() else []
    if len(lines) > MAX_ROWS:
        RAW_DB.write_text("\n".join(lines[-MAX_ROWS:]) + "\n", encoding="utf-8")


def cache_key(window: str, isp: str, city: str, metric: str, limit: int) -> str:
    return "|".join([window, isp.lower(), city.lower(), metric, str(limit)])


def load_cache() -> dict[str, Any]:
    if not CACHE_DB.exists():
        return {}
    try:
        return json.loads(CACHE_DB.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict[str, Any]) -> None:
    ensure_data_dir()
    CACHE_DB.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def window_seconds(name: str) -> int:
    return {"4h": 14_400, "day": 86_400, "week": 604_800}.get(name, 86_400)


def rank_rows(window: str, isp: str, city: str, metric: str, limit: int) -> list[dict[str, Any]]:
    now = int(time.time())
    cutoff = now - window_seconds(window)
    rows = [r for r in iter_measurements() if r.timestamp >= cutoff]
    if isp and isp.lower() != "all":
        rows = [r for r in rows if r.isp.lower() == isp.lower()]
    if city and city.lower() != "all":
        rows = [r for r in rows if r.city.lower() == city.lower()]

    grouped: dict[str, list[Measurement]] = {}
    for row in rows:
        grouped.setdefault(row.ip, []).append(row)

    metric_map = {"ping": "ping", "jitter": "jitter", "latency": "latency", "loss": "loss", "ul": "upload", "dl": "download"}
    attr = metric_map.get(metric, "download")
    reverse = attr in {"upload", "download"}

    ranked = []
    for ip, group in grouped.items():
        latest = max(group, key=lambda r: r.timestamp)
        ranked.append(
            {
                "ip": ip,
                "samples": len(group),
                "score": round(mean(getattr(r, attr) for r in group), 3),
                "ping": round(mean(r.ping for r in group), 3),
                "jitter": round(mean(r.jitter for r in group), 3),
                "latency": round(mean(r.latency for r in group), 3),
                "loss": round(mean(r.loss for r in group), 4),
                "upload": round(mean(r.upload for r in group), 3),
                "download": round(mean(r.download for r in group), 3),
                "country": latest.country,
                "isp": latest.isp,
                "city": latest.city,
                "organization": latest.organization,
            }
        )
    ranked.sort(key=lambda item: item["score"], reverse=reverse)
    return ranked[:limit]


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "pluribus-analyzer"})


@app.post("/ingest")
def ingest():
    ok, response = require_token()
    if not ok:
        return response
    payload = request.get_json(force=True, silent=True) or {}
    rows = payload.get("measurements", payload if isinstance(payload, list) else [])
    measurements = [Measurement.from_payload(row) for row in rows]
    return jsonify({"stored": append_measurements(measurements)})


@app.get("/top")
def top():
    window = request.args.get("window", "day")
    isp = request.args.get("isp", "all")
    city = request.args.get("city", "all")
    metric = request.args.get("metric", "dl")
    limit = min(int(request.args.get("limit", "10")), 50)
    key = cache_key(window, isp, city, metric, limit)
    cache = load_cache()
    cached = cache.get(key)
    if cached and time.time() - cached["created_at"] < MAX_CACHE_AGE_SECONDS:
        return jsonify({"cached": True, "results": cached["results"]})
    results = rank_rows(window, isp, city, metric, limit)
    cache[key] = {"created_at": time.time(), "results": results}
    save_cache(cache)
    return jsonify({"cached": False, "results": results})


if __name__ == "__main__":
    ensure_data_dir()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))

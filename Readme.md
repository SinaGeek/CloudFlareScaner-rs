# Pluribus Scanner

Pluribus Scanner is an asynchronous Cloudflare clean-IP scanner for lawful, authorized testing. Cloudflare Anycast can route the same service through many IP ranges; this project helps you find the ranges that are fastest and most stable from your own network.

The repository now contains three deployable parts:

1. **Python scanner** (`start-file-async.py`) — interactive two-stage scanner with resume support and optional Cloudflare DNS upload.
2. **Rust terminal UI** (`Rust/`) — a cross-platform Rust prototype that reads Cloudflare IPv4 ranges and renders a live terminal table while writing `selected-ips.txt` and `selected-ips.csv`.
3. **Bots** (`Telegram_BOT/` and `HF_bot/`) — a Cloudflare Worker Telegram bot plus a Hugging Face analyzer service for community-submitted results.

## Python dependency fix

If you see a warning like this on Python 3.14:

```text
RequestsDependencyWarning: urllib3 (...) or chardet (...)/charset_normalizer (...) doesn't match a supported version
```

install the pinned dependency set from this repository:

```bash
python -m pip install --upgrade -r requirements.txt
```

`requirements.txt` keeps `requests`, `urllib3`, `charset-normalizer`, and `chardet` in compatible major-version ranges. The scanner also filters the legacy warning so a globally polluted Python installation does not hide the scanner prompt.

## Running the Python scanner

```bash
python start-file-async.py
```

The scanner asks for:

- number of clean IPs to keep;
- maximum ping, jitter, latency, and packet loss;
- optional include/exclude IP prefixes;
- upload/download test sizes and minimum speeds;
- optional Cloudflare DNS credentials for uploading selected records.

### Stage 1: normal scan

The scanner loads `ipv4.txt`, samples candidate IPs without materializing huge CIDR ranges in memory, runs ping/loss and latency/jitter checks, then speed-tests the valid candidates.

### Stage 2: extended search

After the first table is filled, you can run an extended search. Extended search uses the current average ping, loss, jitter, latency, upload speed, and download speed as stricter thresholds and tries to find candidates that improve the final top list.

### Output files

- `selected-ips.txt` — clean IPs only.
- `selected-ips.csv` — full metric table.
- `selected-ips-extended.txt` and `selected-ips-extended.csv` — generated after extended search.
- `progress.json` — checkpoint used to resume after interruption.

## Running the Rust terminal UI

```bash
cd Rust
cargo run -- --input ../ipv4.txt --max-ip 10 --max-latency 1000
```

The Rust UI is intentionally dependency-light. It tests TCP reachability to port `443`, estimates average latency, jitter, and packet loss from repeated connection attempts, renders a live table, and writes the same `selected-ips.*` output files.

Useful options:

```text
-i, --input <file>       IPv4 CIDR list (default: ../ipv4.txt)
-n, --max-ip <count>     Number of clean IP candidates to keep
    --max-latency <ms>   Maximum average TCP latency
    --attempts <count>   TCP attempts per IP
    --timeout <ms>       Per-attempt connect timeout
```

## Telegram bot and analyzer

The community workflow is split into two services:

- `Telegram_BOT/Worker.js` registers Telegram users, issues secret codes, accepts `/submit` measurements, enriches IPs with `api.ip.sb`, stores D1 rows, and flushes data to the analyzer.
- `HF_bot/Analyzer_bot.py` receives batches, keeps recent measurements, caches repeated `/top` requests, and returns ranked IPs by time window, ISP, city, and metric.

See `Telegram_BOT/Readme.md` and `HF_bot/readme.md` for deployment steps, required environment variables, and database schema.

## GitHub Actions

`.github/workflows/build.yml` compiles the Python files and builds/tests the Rust UI on Linux, Windows, and macOS. Release binaries are uploaded as workflow artifacts.

## Example terminal table

```text
|---|---------------|--------|-------|-------|--------|----------|---------|
| # |       IP      |Ping(ms)|Loss(%)|Jit(ms)|Lat(ms)|Up(Mbps)|Down(Mbps)|
|---|---------------|--------|-------|-------|--------|----------|---------|
|  1|172.67.219.212 |    133 |0.0    |   100 |   265 |   1.69 |     7.14 |
|   |    Average    |    133 |  0.0  |   100 |   265 |   1.69 |     7.14 |
|---|---------------|--------|-------|-------|--------|----------|---------|
```

## Responsible use

Only scan networks and upload DNS records that you own or are authorized to test. Community submissions should be truthful measurements from your own connection so other users receive reliable clean-IP recommendations.

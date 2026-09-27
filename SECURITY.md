# MediaGrab AI — Security Architecture & Threat Model

**Version:** 1.0.0  
**Status:** Pre-Deployment Audit Complete  
**Last Verified:** September 2026  

---

## 1. Executive Summary & Threat Model

MediaGrab AI is a web application that accepts arbitrary user-submitted URLs to extract and download media streams. Accepting arbitrary external URLs is an inherently high-risk pattern that exposes servers to:

1. **Server-Side Request Forgery (SSRF)**: Attackers attempting to scan internal networks, reach loopback services (`127.0.0.1`), or exfiltrate credentials from cloud metadata endpoints (`169.254.169.254`).
2. **DNS Rebinding & Time-of-Check to Time-of-Use (TOCTOU)**: Domain names configured with ultra-low TTLs that resolve to a public IP on initial validation, but rebind to an internal address when fetched.
3. **Subprocess Escape & Malicious Extractor Exploitation**: Untrusted extractor plugins or malformed responses targeting `yt-dlp` or shell command injection vulnerabilities.
4. **Denial of Service (DoS) & Storage Exhaustion**: Giant file downloads, infinite playlist explosions, or continuous high-frequency extraction requests.
5. **Path Traversal & Arbitrary File Overwrite**: Malicious video titles (e.g. `../../etc/cron.d/job`) compromising server file structures.
6. **Prompt Injection Attacks**: Malicious web pages embedding directives into `og:title` or descriptions to hijack LLM behavior.

To defend against these threats, MediaGrab AI adopts a strict **Defense-in-Depth** and **Zero-Trust** model built in from day one.

---

## 2. Server-Side Request Forgery (SSRF) Defenses

All SSRF validation is enforced in `backend/app/security/ssrf_validator.py` before any network connection is initiated.

### 2.1 RFC Network Range Blacklist
Every hostname submitted by the user is resolved to all associated IPv4 and IPv6 addresses via `socket.getaddrinfo`. The request is rejected if **any** address falls into private, loopback, multicast, or reserved ranges:

- **Loopback**: `127.0.0.0/8`, `::1`
- **Private Class A, B, C**: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- **Link-Local & Cloud Metadata**: `169.254.0.0/16` (including AWS/GCP/Azure/DigitalOcean metadata at `169.254.169.254`), `fe80::/10`
- **Current Network / Broadcast**: `0.0.0.0/8`, `255.255.255.255/32`, `::/128`
- **Carrier-Grade NAT & Benchmark**: `100.64.0.0/10`, `198.18.0.0/15`
- **IPv4-Mapped IPv6**: `::ffff:0:0/96` (extracted and verified against all IPv4 rules)
- **IPv6 Unique Local (ULA)**: `fc00::/7`
- **Documentation & Discard**: `192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`, `2001:db8::/32`
- **Multicast & Reserved**: `224.0.0.0/4`, `240.0.0.0/4`, `ff00::/8`

### 2.2 Hostname & Scheme Restrictions
- **Scheme Whitelist**: Strictly `http` and `https`. All others (`file://`, `ftp://`, `gopher://`, `dict://`, `data:`, `javascript:`) are rejected.
- **Embedded Credentials Blocked**: URLs containing userinfo (e.g. `http://user:pass@host` or `http://attacker.com@127.0.0.1`) are immediately rejected.
- **Blocked Hostnames**: `localhost`, `*.localdomain`, `metadata.google.internal`, `instance-data`.
- **Length Ceiling**: URL length capped at 2,048 characters.

### 2.3 Hop-by-Hop Redirect Inspection (DNS Rebinding Defense)
Standard HTTP clients follow 3xx redirects automatically without validating the destination. In MediaGrab AI, `safe_http_request()` disables automatic redirects and handles each hop iteratively:
1. Target URL is resolved and checked against the full SSRF filter.
2. HTTP client executes single hop (`follow_redirects=False`).
3. If response status is `301/302/303/307/308`, the `Location` header is resolved to an absolute URL.
4. The new destination URL is subjected to the full SSRF filter before initiating connection.
5. Hard cap of maximum 5 redirects.

### 2.4 Headless Browser SSRF Route Interception (Tier 4)
During headless browser execution in Playwright (Tier 4 fallback):
1. An asynchronous route interceptor (`page.route("**/*")`) intercepts **every single HTTP/HTTPS request** initiated by the browser (scripts, XHR, fetches, images, iframes, stylesheets).
2. The destination URL of each subresource request is resolved and checked against the full SSRF blacklist.
3. If the request targets a loopback, internal LAN IP, cloud metadata IP, or non-http scheme, it is immediately aborted via `route.abort('blockedbyclient')`.
4. Browser contexts are strictly ephemeral: created per-extraction and closed immediately with zero persistent state, storage, or cookies.

---

## 3. Isolated Subprocess Sandboxing

Subprocess execution is managed by `backend/app/security/sandbox.py`.

### 3.1 Non-Shell Execution
`yt-dlp` and `ffmpeg` are spawned using Python's `asyncio.create_subprocess_exec()` with explicit tokenized argument lists. `shell=True` is **never** used, eliminating command injection vulnerabilities.

### 3.2 Environment Sanitization
The child process does not inherit the master application environment:
- All sensitive environment variables (`GEMINI_API_KEY`, `REDIS_URL`, AWS credentials, database URLs, auth tokens) are completely stripped.
- Only a minimal whitelist of system keys (`PATH`, `SYSTEMROOT`, `TEMP`, `PYTHONUTF8`) is forwarded.

### 3.3 Defensive Execution Arguments
Every `yt-dlp` invocation includes:
- `--no-config`: Disallows loading any host configuration files (`/etc/yt-dlp.conf` or `~/.config/yt-dlp`).
- `--no-cache-dir`: Disables reading from or writing to local disk cache.
- `--no-playlist`: Rejects playlist URLs to prevent an attacker queuing thousands of videos and exhausting memory or bandwidth.
- `--max-filesize 1073741824`: Hard cap on media file size (1 GB).
- `--socket-timeout 15`: Prevents hung network connections.
- `--restrict-filenames`: Restricts filename characters.

### 3.4 Fast-Fail Timing Architecture & Hard Timeouts
To eliminate the "takes forever then errors" failure mode, each extraction tier enforces an independent short timeout and bails immediately on clear failure signals:
- **Tier 1 (yt-dlp)**: 8 seconds maximum (bails immediately on "unsupported URL" or extractor failure).
- **Tier 2 (Direct Media Check)**: 5 seconds maximum (bails immediately on 404 or text/html MIME).
- **Tier 3 (Static HTML Scrape)**: 5 seconds maximum (bails immediately if no OpenGraph/video tags exist).
- **Tier 4 (Headless Browser)**: 15 seconds maximum (Playwright renders dynamic JS, network idle wait capped at 10s).
- **Total Extraction Ceiling**: **30 seconds hard cap** across all tiers combined, guaranteeing no silent hangs.
- **Media Download Job**: Bounded by a 10-minute timeout.
- Subprocesses exceeding timeouts are gracefully terminated (`SIGTERM`), followed by immediate kill (`SIGKILL`) if unresponsive after 1 second.

---

## 4. Rate Limiting & Concurrency Controls

Implemented in `backend/app/security/rate_limiter.py`.

### 4.1 Sliding-Window Algorithm
Unlike fixed-window counters that allow burst attacks across window boundaries, MediaGrab AI uses a sliding-window algorithm tracking timestamp histories per IP address:
- **Metadata Requests**: Maximum 30 requests per 300 seconds (5 minutes).
- **Download Requests**: Maximum 10 downloads per 600 seconds (10 minutes).
- Returns HTTP `429 Too Many Requests` with a calculated `Retry-After` header when quota is exceeded.

### 4.2 Concurrent Job Limiting
- Maximum of **2 concurrent active downloads** per IP address.
- Active jobs are tracked across async workers with mutex locks, preventing bandwidth and local disk exhaustion.

---

## 5. Storage Security & Path Traversal Prevention

Implemented in `backend/app/services/storage_manager.py` and `sanitizer.py`.

### 5.1 Unguessable UUID Storage Keys
- Downloaded files on disk are stored as `storage/downloads/<uuid4>.<ext>`.
- The storage path is never derived from video titles or user input.
- Files cannot be accessed directly by relative path or directory traversal (`../../`).

### 5.2 Content-Disposition Sanitization
When the file is served to the client browser:
- Dangerous extensions (`.exe`, `.bat`, `.cmd`, `.sh`, `.vbs`, etc.) are stripped or overridden to safe media extensions (`.mp4`, `.mp3`).
- Path separators (`/`, `\`) and non-alphanumeric characters are sanitized.
- Filename is truncated to 100 characters.

### 5.3 1-Hour Ephemeral Storage (TTL)
- A background worker (`start_cleanup_worker`) runs every 5 minutes.
- Files older than 3,600 seconds (1 hour) are permanently unlinked from disk and purged from memory.

---

## 6. AI Assistant Prompt Injection Hardening

Implemented in `backend/app/services/ai_assistant.py`.

- **Data-Instruction Separation**: All external data (URLs, scraped OpenGraph titles, platform text) is treated strictly as **untrusted data**, never instructions.
- Untrusted content is wrapped in explicit XML delimiters (`<untrusted_user_input>`).
- Any attempt to break delimiters (e.g. `</untrusted_user_input>`) is stripped before prompt construction.
- Strict system prompt rules instruct the LLM never to follow instructions found within untrusted content.
- Built-in heuristic engine acts as a 100% offline, zero-latency fallback requiring no external API calls.

---

## 7. Transport Security & HTTP Security Headers

Enforced by `SecurityHeadersMiddleware` in `backend/app/main.py`:
- `X-Content-Type-Options: nosniff` (Prevents MIME-type sniffing attacks)
- `X-Frame-Options: DENY` (Clickjacking prevention)
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Content-Security-Policy: default-src 'self'; img-src 'self' data: https: blob:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self' ws: wss:;`

---

## 8. Dependency Hygiene & Update Procedure

### Pinned Dependencies
All backend packages are pinned in `backend/requirements.txt`:
```txt
fastapi==0.141.1
uvicorn[standard]==0.49.0
pydantic==2.13.4
pydantic-settings==2.15.0
httpx==0.28.1
beautifulsoup4==4.15.0
yt-dlp==2026.8.19
imageio-ffmpeg==0.6.0
pytest==9.1.1
pytest-asyncio==1.4.0
```

### Regular Update & Audit Commands
`yt-dlp` platform extractors frequently require updates as video platforms adjust their player formats.

```powershell
# 1. Update yt-dlp to latest stable release
python -m pip install --upgrade yt-dlp

# 2. Run Python dependency vulnerability audit
python -m pip_audit -r backend/requirements.txt

# 3. Run Frontend dependency vulnerability audit
cd frontend
npm audit
```

Both `pip-audit` and `npm audit` return **0 known vulnerabilities**.

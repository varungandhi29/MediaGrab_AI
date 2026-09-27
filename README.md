# MediaGrab AI 🎥⚡

**MediaGrab AI** is a universal media downloader and stream extractor equipped with an AI assistant layer and enterprise-grade security defenses built in from day one.

Designed with a **Zero-Trust** approach, MediaGrab AI protects your infrastructure from Server-Side Request Forgery (SSRF), DNS rebinding, resource exhaustion, and command injection when processing arbitrary user-submitted URLs.

---

## ✨ Key Features

- 🎯 **Single URL Input**: Paste any URL from 1,800+ platforms (YouTube, Vimeo, TikTok, Instagram, X/Twitter, Reddit, SoundCloud, Twitch, etc.) or direct media links.
- ⚡ **4-Tier Fast-Fail Extraction Engine**:
  1. *Tier 1*: Sandboxed `yt-dlp` extraction covering 1,800+ video services (8s timeout).
  2. *Tier 2*: Direct media file inspector (`Content-Type` validation for `.mp4`, `.webm`, `.mp3`, `.m3u8`, etc., 5s timeout).
  3. *Tier 3*: Lightweight embedded HTML5 video scraper (`og:video` meta tags, `<video>` tags, 5s timeout).
  4. *Tier 4*: Headless Chromium browser rendering via Playwright with network response sniffing and post-JS DOM inspection (15s timeout).
  - *Fast-Fail Guarantee*: Sequential bailout on negative signals with a 30s maximum total ceiling.
- 🎬 **Genuine Resolution Selector**: Only displays qualities that actually exist in the source stream (480p, 720p, 1080p Full HD, 1440p 2K, 2160p 4K). Never fabricates fake options.
- 🎵 **High-Fidelity Audio Extraction**: One-click "Audio only (MP3)" conversion at 320kbps via FFmpeg.
- 📊 **Live Progress Bar**: Real-time download percentage, download speed (MB/s), and ETA via Server-Sent Events (SSE).
- 💾 **Direct Browser Downloads**: Streams files directly without buffering entire gigabyte payloads in server memory.
- 🤖 **AI Assistant Layer**:
  - Auto-detects platform from pasted links with instant confirmation.
  - Smart use-case recommendation (Mobile/Data Saver, Standard HD, Pro Editing/4K, Podcast/Audio).
  - Plain-language error translation for private videos, geo-blocks, or rate limits.
  - Strict prompt-injection defense treating all external data as untrusted.
- 📜 **Session Download History**: Convenient browser-based history with direct re-download links (no login required for v1).
- ⚖️ **Legal & Terms Page**: Built-in copyright fair use disclaimer and compliance notices.

---

## 🛡️ Security Defenses Built-In

Detailed documentation is available in [`SECURITY.md`](SECURITY.md).

- **SSRF Shield**: Resolves hostnames against all IPv4/IPv6 addresses and blocks loopback (`127.0.0.0/8`, `::1`), private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`), cloud metadata (`169.254.169.254`), and IPv4-mapped IPv6.
- **DNS Rebinding & Redirect Defense**: Inspects and re-validates every redirect hop before establishing connections.
- **Isolated Subprocess Sandboxing**: Spawns `yt-dlp` via `create_subprocess_exec` (no `shell=True`) with stripped environment variables (no leaked secrets), hard execution timeouts, and strict disk size caps.
- **Sliding-Window Rate Limiting**: Per-IP sliding window limits for metadata (30 req / 5 min) and downloads (10 req / 10 min), plus concurrency limits (max 2 concurrent downloads per IP).
- **Ephemeral Storage**: All downloads stored with random UUID filenames. Automatically destroyed after 1 hour (TTL).
- **Security Headers**: Enforces CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, and `Referrer-Policy`.

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+ (Python 3.14 supported)
- Node.js 18+ (Node 22 supported)
- FFmpeg (automatically provided via `imageio-ffmpeg` or system PATH)

### 1. Backend Setup

```powershell
# Navigate to backend directory
cd backend

# Install pinned dependencies
python -m pip install -r requirements.txt

# Run backend test suite (SSRF, rate limiting, sanitization)
python -m pytest tests

# Start backend server (port 8000)
python run_backend.py
```

### 2. Frontend Setup

```powershell
# Navigate to frontend directory
cd frontend

# Install dependencies
npm install

# Start Vite dev server (port 5173 with proxy to backend)
npm run dev

# Or build for production
npm run build
```

When `frontend/dist` is built, the backend automatically serves the complete full-stack application at `http://localhost:8000`!

---

## ⚙️ Environment Variables

Create a `.env` file in `backend/` to customize configurations:

| Variable | Default | Description |
|---|---|---|
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server bind port |
| `ENVIRONMENT` | `production` | `production` or `development` |
| `FILE_TTL_SECONDS` | `3600` | Temporary download file TTL (1 hour) |
| `MAX_FILE_SIZE_BYTES` | `1073741824` | Maximum download size per job (1 GB) |
| `METADATA_RATE_LIMIT_REQUESTS` | `30` | Max metadata requests per sliding window |
| `METADATA_RATE_LIMIT_WINDOW_SECONDS` | `300` | Metadata sliding window duration (5 min) |
| `DOWNLOAD_RATE_LIMIT_REQUESTS` | `10` | Max downloads per sliding window |
| `DOWNLOAD_RATE_LIMIT_WINDOW_SECONDS` | `600` | Download sliding window duration (10 min) |
| `MAX_CONCURRENT_DOWNLOADS_PER_IP`| `2` | Max simultaneous active downloads per IP |
| `GEMINI_API_KEY` | *(optional)* | Google Gemini API key for advanced AI features |
| `FFMPEG_PATH` | *(auto-detected)* | Custom path to FFmpeg binary |

---

## 🧪 Testing & Verification

MediaGrab AI includes automated test coverage:

```powershell
# Run backend tests
cd backend
python -m pytest tests -v

# Run dependency vulnerability audits
cd ..
python -m pip_audit -r backend/requirements.txt
cd frontend
npm audit
```

---

## ⚖️ Legal & Copyright Disclaimer

MediaGrab AI is intended solely for personal backup, research, public domain works, Creative Commons media, and content for which the user holds explicit retrieval rights. It does not circumvent digital rights management (DRM) or proprietary encryption. Users are solely responsible for adhering to applicable copyright laws and platform terms of service.

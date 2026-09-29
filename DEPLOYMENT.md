# MediaGrab AI - Production Deployment Guide 🚀🌐

MediaGrab AI is engineered to be deployed as a **single, unified, high-performance service** where the compiled React frontend, FastAPI backend, FFmpeg media engine, and Playwright scrapers run seamlessly together under one domain and port.

---

## 🏗️ Deployment Architecture

```
[ User Browser ]
       │
       ▼  (HTTPS / Port 443 or 8000)
┌────────────────────────────────────────────────────────┐
│                   Unified Container / Host             │
│                                                        │
│  FastAPI (Uvicorn) - Port 8000                         │
│  ├── /api/*               ──► Security, SSRF & Engine  │
│  ├── /stream/*            ──► Media Streaming Proxy   │
│  ├── /media/*             ──► Range & Audio Sync       │
│  └── /*                   ──► React Vite SPA (dist/)   │
│                                                        │
│  FFmpeg Engine ◄── Subprocess Sandboxing               │
│  Playwright Chromium (Tier 4 Headless Scraper)        │
└────────────────────────────────────────────────────────┘
```

---

## ⚡ Option 1: Docker / Docker Compose (Recommended for Any VPS or Cloud)

This is the cleanest, most resilient way to run MediaGrab AI in production. It packages FFmpeg, Playwright Chromium, Node, and Python into an isolated container.

### Step 1: Clone and Enter Directory
```bash
git clone <your-repo-url>
cd MediaGrab_AI
```

### Step 2: Configure Environment (Optional)
Create or edit `.env` in the root:
```env
PORT=8000
ENVIRONMENT=production
FILE_TTL_SECONDS=3600
MAX_FILE_SIZE_BYTES=1073741824
GEMINI_API_KEY=your_gemini_api_key_here
```

### Step 3: Build & Start in Background
```bash
docker compose up -d --build
```

### Step 4: Verify Deployment
```bash
# Check container status & health
docker compose ps

# View real-time logs
docker compose logs -f

# Check health endpoint
curl http://localhost:8000/api/health
```

To stop:
```bash
docker compose down
```

---

## ☁️ Option 2: 1-Click Free / Cloud Hosting (Render, Railway, Fly.io)

### Deploying to Render
1. Push your repository to **GitHub** or **GitLab**.
2. Go to [Render Dashboard](https://dashboard.render.com).
3. Click **New +** -> **Blueprint**.
4. Connect your repository. Render will automatically read [`render.yaml`](render.yaml) and configure the Docker service.
5. Click **Apply**. Render will build and deploy the container on your custom `.onrender.com` URL with free SSL!

### Deploying to Railway
1. Go to [Railway Dashboard](https://railway.app).
2. Click **New Project** -> **Deploy from GitHub repo**.
3. Select your `MediaGrab_AI` repository.
4. Railway will automatically detect the [`Dockerfile`](Dockerfile) and build it.
5. Under **Settings** -> **Networking**, click **Generate Domain**.

### Deploying to Fly.io
```bash
# Install Flyctl
curl -L https://fly.io/install.sh | sh

# Launch application
fly launch --dockerfile Dockerfile

# Deploy
fly deploy
```

---

## 🐧 Option 3: Self-Hosted Linux VPS (Ubuntu / Debian + Nginx + SSL)

If you have a digital VPS (DigitalOcean, Linode, AWS EC2, Hetzner, Vultr):

### Step 1: Install System Dependencies
```bash
sudo apt update && sudo apt install -y python3-pip python3-venv ffmpeg nodejs npm nginx certbot python3-certbot-nginx
```

### Step 2: Clone & Build Frontend
```bash
cd /var/www
git clone <your-repo-url> mediagrab
cd mediagrab/frontend
npm install
npm run build
```

### Step 3: Setup Python Environment
```bash
cd /var/www/mediagrab
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
playwright install chromium
playwright install-deps
```

### Step 4: Setup Systemd Service
Create `/etc/systemd/system/mediagrab.service`:
```ini
[Unit]
Description=MediaGrab AI Unified Service
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/mediagrab/backend
Environment="PATH=/var/www/mediagrab/venv/bin:/usr/bin"
Environment="PYTHONPATH=/var/www/mediagrab/backend"
Environment="ENVIRONMENT=production"
ExecStart=/var/www/mediagrab/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2

Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mediagrab
sudo systemctl start mediagrab
```

### Step 5: Configure Nginx & SSL
Create `/etc/nginx/sites-available/mediagrab.conf`:
```nginx
server {
    server_name yourdomain.com www.yourdomain.com;

    client_max_body_size 1024M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket & Streaming support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
```

Enable site & get free SSL certificate:
```bash
sudo ln -s /etc/nginx/sites-available/mediagrab.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
sudo certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

---

## 💻 Option 4: Local Production Mode (Windows / macOS / Linux)

To run the production-optimized build on your machine without running two dev terminals:

### On Windows:
Double-click:
```powershell
deploy_production.bat
```
*Or via PowerShell:*
```powershell
.\deploy_production.ps1
```

### On macOS / Linux:
```bash
cd frontend && npm run build && cd ..
export PYTHONPATH="backend"
python backend/run_backend.py
```

Open `http://localhost:8000` in any browser!

## 🏷️ Custom Domain & "MediaGrabAI" Named URLs

### 1. Active Named Tunnel (Live Now)
- **URL**: [`https://mediagrabai.loca.lt`](https://mediagrabai.loca.lt)
- **Subdomain**: Dedicated `mediagrabai` name
- **Password/IP for First-Time Browser Visit**: `49.36.76.97` (Localtunnel asks for tunnel IP on first visit for abuse prevention; once entered, it unlocks forever).

### 2. High-Performance Edge Tunnel (Zero Prompts, Live Now)
- **URL**: [`https://pay-pichunter-addresses-sword.trycloudflare.com`](https://pay-pichunter-addresses-sword.trycloudflare.com)
- Powered by Cloudflare global CDN without any password prompts.

### 3. Your Own Custom Domain (e.g. `mediagrabai.com` or `mediagrab.ai`)
If you purchase or own your own domain (e.g. from Namecheap, Porkbun, or Cloudflare Registrar):
1. **Authenticate Cloudflare CLI**:
   ```bash
   .\cloudflared.exe tunnel login
   ```
2. **Create Named Tunnel**:
   ```bash
   .\cloudflared.exe tunnel create mediagrabai
   ```
3. **Route Your Domain**:
   ```bash
   .\cloudflared.exe tunnel route dns mediagrabai mediagrabai.com
   ```
4. **Run Live on Your Custom Domain**:
   ```bash
   .\cloudflared.exe tunnel run --url http://localhost:8000 mediagrabai
   ```
   Your app will immediately be live at `https://mediagrabai.com` with free Cloudflare SSL!

---

## 🛡️ Pre-Flight Verification Checklist

Before opening to public traffic, verify:
- [x] **SSRF Protection**: Verified blocking internal IPs (`127.0.0.1`, `10.0.0.0/8`, `169.254.169.254`).
- [x] **FFmpeg Engine**: `http://<domain>/api/health` reports `"ffmpeg_available": true`.
- [x] **Full-Screen & Hotkeys**: Arrow keys, Space, 'F', 'M' keys operational.
- [x] **Multi-Quality Playback**: 1080p, 720p, 480p, 360p switching seamless.
- [x] **Audio-Video Seeking**: Drift correction verified without drops.
- [x] **00:00 Initial Start**: Video restarts at the beginning on every fresh launch.

# GoFile & HDHub Direct Link Bypasser Telegram Bot

A fast, lightweight, and rate-limit immune Telegram bot that converts **GoFile** and **HDHub / GreenMotors / HubCloud** sharing links into high-speed direct download URLs.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/brozzi1/gofile-bypass-telegram-bot)

## ✨ Features
- **Multi-Service Bypass**:
  - **GoFile.io**: Pure Python SHA-256 token generation + dynamic session authorization via Cloudflare Worker proxy.
  - **HDHub / GreenMotors / HubCloud**: Ultra-fast pure Python HTTP decoding (< 1s, < 15MB RAM) with automatic deep scraping of fast server mirrors (Google Cloud, PixelDrain, Telegram).
- **Concurrent Processing**: If a user sends up to 10 links in a message, all links resolve in parallel.
- **Multi-User & Queue System**: Multiple users can use the bot simultaneously without blocking; same-user requests are queued via FIFO.
- **Clean Telegram UI**: Formatted HTML message with blockquoted metadata and compact hyperlinked direct download links.
- **Render & Cloud Ready**: Zero heavy browser overhead (< 15MB RAM footprint), works on Render's 512MB free tier without crashing.
- **Standalone CLI Tools**: Both `gofile_resolver.py` and `hdhub_resolver.py` can also be run directly from terminal or imported into Python projects.

---

## 🚀 Deploy to Render (1-Click)

Click the button below to deploy this bot to Render for free:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/brozzi1/gofile-bypass-telegram-bot)

1. Click **Deploy to Render**.
2. Sign in or create a free account on [render.com](https://render.com).
3. Enter your **`BOT_TOKEN`** (obtained from [@BotFather](https://t.me/BotFather)).
4. Click **Apply**. Render will automatically build the service, start the bot, and pass the web health check!

> **If creating a Web Service manually in Render's dashboard:**
> * **Runtime**: `Python 3`
> * **Build Command**: `pip install -r requirements.txt`
> * **Start Command**: `python main.py` *(Replace Render's default placeholder `gunicorn your_application.wsgi`)*
> * **Environment Variables**: Add `BOT_TOKEN` under the Environment tab.

---

## ⚡ Deploy to Pella.app

1. **Create your Telegram Bot**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Send `/newbot`, name your bot, and copy your **HTTP API Token**.

2. **Connect to Pella.app**:
   - Create a new project on [Pella.app](https://pella.app).
   - Connect your GitHub repository: `https://github.com/brozzi1/gofile-bypass-telegram-bot`.

3. **Set Environment Variables on Pella.app**:
   - `BOT_TOKEN`: `your_bot_token_from_botfather`
   - `WORKER_URL`: `https://your-worker-subdomain.workers.dev`
   - *(Optional)* `WORKER_TOKEN`: `your_worker_token` (leave unset to automatically use dynamic session tokens)

4. **Start the Bot**:
   - Pella will detect `Procfile` or `Dockerfile`, install dependencies, and start `bot.py`.

---

## 💻 Running Locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file from `.env.example`:
   ```bash
   cp .env.example .env
   ```
   Fill in your `BOT_TOKEN`.

3. Run the bot:
   ```bash
   python main.py
   ```

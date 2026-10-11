# GoFile Direct Link Bypasser Telegram Bot

A fast, lightweight, and rate-limit immune Telegram bot that converts GoFile sharing links into direct Cloudflare Worker download URLs.

## Features
- **Instant Resolution**: Resolves single or multi-file links in ~1.5 seconds.
- **Concurrent Processing**: If a user sends multiple links, all links resolve in parallel.
- **Rate-Limit Safe**: Built-in caching eliminates redundant account calls and prevents GoFile HTTP 429 errors.
- **Clean Telegram UI**: Formatted HTML message with file name, size, direct URL, and an inline **⬇️ Direct Download** button.

---

## Deploying on Pella.app

1. **Create your Telegram Bot**:
   - Open Telegram and message [@BotFather](https://t.me/BotFather).
   - Use `/newbot`, name your bot, and copy your **HTTP API Token**.

2. **Upload / Connect to Pella.app**:
   - Create a new project on [Pella.app](https://pella.app).
   - Connect your GitHub repository containing these files (or upload the files):
     - `bot.py`
     - `gofile_resolver.py`
     - `requirements.txt`
     - `Procfile`
     - `Dockerfile`

3. **Set Environment Variables on Pella.app**:
   - In your project settings / environment variables section on Pella.app, add:
     - `BOT_TOKEN`: `your_bot_token_from_botfather`
     - `WORKER_URL`: `https://your-worker-subdomain.workers.dev`
     - *(Optional)* `WORKER_TOKEN`: `your_worker_token` (default: `RYyZhLtRBdD5idwzBACnwXtT9iYpRibr`)

4. **Start the Bot**:
   - Build and start the service.
   - Pella will detect `Procfile` or `Dockerfile`, install dependencies from `requirements.txt`, and start `bot.py`.
   - Message your bot on Telegram with `/start` and test by pasting a GoFile link!

---

## Running Locally

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Create a `.env` file (or copy `.env.example`):
   ```env
   BOT_TOKEN=your_telegram_bot_token_here
   ```

3. Run the bot:
   ```bash
   python bot.py
   ```

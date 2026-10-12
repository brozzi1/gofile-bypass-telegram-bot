#!/usr/bin/env python3
"""
GoFile Telegram Bypass Bot (Production Version)
Features:
- Single formatted response per batch.
- Blockquoted file metadata with compact hyperlinks.
- Max 10 links per batch to prevent flooding.
- Fully concurrent across multiple users.
- Per-user FIFO queue system: if a user sends links while one is resolving,
  the new links are queued and processed sequentially for that user.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional, Set, Tuple

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Import optimized resolvers
from gofile_resolver import GoFileResolver, DEFAULT_WORKER_TOKEN
from hdhub_resolver import HDHubResolver

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("BypassBot")

BOT_TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
WORKER_URL = os.getenv("WORKER_URL", "https://go-file.ddbypassed.workers.dev")
WORKER_TOKEN = os.getenv("WORKER_TOKEN") or DEFAULT_WORKER_TOKEN
MAX_LINKS_PER_BATCH = 10
MAX_TG_MSG_LENGTH = 3900  # Safe threshold below Telegram's 4096 limit

# Global resolver instances
resolver = GoFileResolver(worker_token=WORKER_TOKEN, worker_url=WORKER_URL)
hdhub_resolver = HDHubResolver(enable_chrome_fallback=False)

GOFILE_REGEX = re.compile(
    r"https?://(?:www\.)?gofile\.io/d/([a-zA-Z0-9_-]+(?:::[^\s]+)?)",
    re.IGNORECASE,
)
HDHUB_REGEX = re.compile(
    r"https?://(?:www\.)?(?:greenmotors\.[a-z]+|hubcloud\.[a-z]+)[^\s]*",
    re.IGNORECASE,
)

# Per-user queue structures
user_queues: Dict[int, asyncio.Queue] = {}
user_active_tasks: Set[int] = set()
queue_lock = asyncio.Lock()


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send welcome message upon /start."""
    user = update.effective_user
    welcome_text = (
        f"👋 <b>Hello {html.escape(user.first_name)}!</b>\n\n"
        "⚡ <b>Welcome to GoFile & HDHub Direct Link Bypasser Bot.</b>\n\n"
        "Send me any <b>GoFile</b> or <b>HDHub / GreenMotors / HubCloud</b> links, and I will resolve them into fast direct download links.\n\n"
        "<b>Supported Links:</b>\n"
        "• <b>GoFile.io</b> — Instant Cloudflare Worker bypassed direct links.\n"
        "• <b>HDHub / GreenMotors</b> — Instant HubCloud bypass + Direct Server Mirrors (Google Cloud, PixelDrain, Telegram).\n\n"
        "<b>Features:</b>\n"
        "• Up to <b>10 links</b> per message.\n"
        "• Single clean formatted response message.\n"
        "• Smart per-user queue system.\n\n"
        "<i>Send me a link or list of links to get started!</i>"
    )
    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send help instructions."""
    help_text = (
        "📖 <b>How to Use:</b>\n\n"
        "1. Paste one or more links in this chat (max 10 per message).\n"
        "2. The bot resolves both GoFile and HDHub / GreenMotors links in parallel.\n\n"
        "<b>GoFile Password Protected:</b>\n"
        "Format: <code>https://gofile.io/d/FILE_ID::password</code>\n\n"
        "<b>Queue System:</b>\n"
        "If you send more links while your current batch is resolving, "
        "they will be queued and automatically processed next."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)


def sync_resolve_batch(items: List[Tuple[str, str]]) -> List[Tuple[str, str, Optional[dict], Optional[Exception]]]:
    """Resolve a mixed batch of links concurrently."""
    def _worker(item: Tuple[str, str]):
        ltype, url = item
        try:
            if ltype == "hdhub":
                res = hdhub_resolver.resolve(url, deep=True)
                return ltype, url, res, None
            else:
                res = resolver.resolve(url)
                return ltype, url, res, None
        except Exception as e:
            return ltype, url, None, e

    workers = min(len(items), 5) if items else 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(_worker, items))


def format_file_block(idx: int, file_info: dict, folder_name: str = "") -> str:
    """Format single GoFile information with blockquoted metadata."""
    name = html.escape(file_info.get("name", "Unknown File"))
    size_bytes = file_info.get("size", 0)
    size_mb = size_bytes / (1024 * 1024)
    if size_mb >= 1024:
        size_str = f"{size_mb / 1024:.2f} GB"
    else:
        size_str = f"{size_mb:.2f} MB"

    bypassed_url = file_info.get("bypassed_url", "")

    quote_parts = [
        f"<b>Size:</b> {size_str}",
    ]
    if folder_name and folder_name != file_info.get("name"):
        quote_parts.append(f"<b>Folder:</b> {html.escape(folder_name)}")

    content = "\n".join(quote_parts)
    return (
        f"📁 <b>{idx}. {name}</b>\n"
        f"<blockquote>{content}</blockquote>\n"
        f"<b><a href=\"{bypassed_url}\">⚡ Fast Direct Download</a></b>\n\n"
    )


def format_hdhub_block(idx: int, data: dict) -> str:
    """Format single HDHub / GreenMotors result with direct mirrors."""
    title = html.escape(data.get("title", "HDHub File"))
    hubcloud_url = data.get("hubcloud_url", "")
    servers = data.get("servers", [])

    server_lines = []
    for s in servers:
        s_name = html.escape(s.get("name", "Direct Download"))
        s_url = s.get("url", "")
        server_lines.append(f"• <a href=\"{s_url}\"><b>{s_name}</b></a>")

    servers_block = "\n".join(server_lines) if server_lines else f"• <a href=\"{hubcloud_url}\"><b>Open HubCloud Drive</b></a>"
    return (
        f"🎬 <b>{idx}. {title}</b>\n"
        f"<blockquote>🔗 <b>HubCloud:</b> <a href=\"{hubcloud_url}\">Drive Link</a></blockquote>\n"
        f"<b>⚡ Fast Mirrors:</b>\n"
        f"{servers_block}\n\n"
    )


async def process_batch(update: Update, items: List[Tuple[str, str]], was_truncated: bool) -> None:
    """Process a single batch of links for a user and reply with a single formatted message."""
    total_links = len(items)
    status_text = f"⚡ <b>Resolving {total_links} link(s)...</b>"
    if was_truncated:
        status_text += "\n<i>(Limited to first 10 links to prevent flooding)</i>"

    status_msg = await update.message.reply_text(status_text, parse_mode=ParseMode.HTML)

    t0 = time.perf_counter()
    loop = asyncio.get_running_loop()

    try:
        # Run resolution in thread pool
        batch_results = await loop.run_in_executor(None, sync_resolve_batch, items)
    except Exception as e:
        logger.exception("Batch resolution failed")
        try:
            await status_msg.edit_text(f"❌ <b>Error processing batch:</b> {html.escape(str(e))}", parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return

    t1 = time.perf_counter()
    elapsed_sec = t1 - t0

    # Build response message
    header = f"⚡ <b>Bypasser Results</b> (<code>{elapsed_sec:.2f}s</code>)\n\n"
    items_text = []
    file_counter = 1

    for ltype, url, data, err in batch_results:
        if err:
            err_msg = html.escape(str(err))
            item = (
                f"❌ <b>Failed:</b> <code>{html.escape(url)}</code>\n"
                f"<blockquote><b>Error:</b> {err_msg}</blockquote>\n"
            )
            items_text.append(item)
            continue

        if ltype == "hdhub" and data:
            item = format_hdhub_block(file_counter, data)
            items_text.append(item)
            file_counter += 1
            continue

        files = data.get("files", []) if data else []
        folder_name = data.get("name", "") if data else ""
        if not files:
            item = (
                f"⚠️ <b>Empty:</b> <code>{html.escape(url)}</code>\n"
                f"<blockquote>No downloadable files found.</blockquote>\n"
            )
            items_text.append(item)
            continue

        for f in files:
            item = format_file_block(file_counter, f, folder_name)
            items_text.append(item)
            file_counter += 1

    # Safe chunking if combined text exceeds Telegram's 4096 character limit
    messages_to_send = []
    current_msg = header

    for item in items_text:
        if len(current_msg) + len(item) > MAX_TG_MSG_LENGTH:
            messages_to_send.append(current_msg)
            current_msg = item
        else:
            current_msg += item

    if current_msg:
        messages_to_send.append(current_msg)

    # Edit status message with first chunk, send rest if any
    try:
        if messages_to_send:
            await status_msg.edit_text(
                messages_to_send[0],
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            for extra_msg in messages_to_send[1:]:
                await update.message.reply_text(
                    extra_msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
    except Exception as e:
        logger.error(f"Failed to edit/send message: {e}")
        try:
            await update.message.reply_text(
                messages_to_send[0] if messages_to_send else "No output.",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


async def user_worker(user_id: int) -> None:
    """Worker task that processes all queued requests for a specific user sequentially."""
    try:
        while True:
            async with queue_lock:
                q = user_queues.get(user_id)
                if not q or q.empty():
                    user_active_tasks.discard(user_id)
                    user_queues.pop(user_id, None)
                    break
                update, items, was_truncated = q.get_nowait()

            try:
                await process_batch(update, items, was_truncated)
            except Exception as e:
                logger.error(f"Error processing user {user_id} item: {e}")
    finally:
        async with queue_lock:
            user_active_tasks.discard(user_id)
            user_queues.pop(user_id, None)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming messages with links, enforce limit, and manage per-user queue."""
    if not update.message:
        return

    text = update.message.text or update.message.caption or ""
    gofile_matches = GOFILE_REGEX.findall(text)
    hdhub_matches = HDHUB_REGEX.findall(text)

    all_items: List[Tuple[str, str]] = []
    seen = set()

    for code in gofile_matches:
        u = f"https://gofile.io/d/{code}"
        if u not in seen:
            seen.add(u)
            all_items.append(("gofile", u))

    for u in hdhub_matches:
        u = u.strip()
        if u not in seen:
            seen.add(u)
            all_items.append(("hdhub", u))

    if not all_items:
        return

    user = update.effective_user
    user_id = user.id

    was_truncated = False
    if len(all_items) > MAX_LINKS_PER_BATCH:
        all_items = all_items[:MAX_LINKS_PER_BATCH]
        was_truncated = True

    async with queue_lock:
        if user_id not in user_queues:
            user_queues[user_id] = asyncio.Queue()

        q = user_queues[user_id]
        is_active = user_id in user_active_tasks

        if is_active:
            # User already has a task running -> enqueue and notify
            q.put_nowait((update, all_items, was_truncated))
            q_pos = q.qsize()
            trunc_note = f" (limited to {MAX_LINKS_PER_BATCH} links)" if was_truncated else ""
            await update.message.reply_text(
                f"⏳ <b>Added to your queue (Position #{q_pos})</b>\n"
                f"Your previous request is currently processing. "
                f"This batch of {len(all_items)} link(s){trunc_note} will start automatically next.",
                parse_mode=ParseMode.HTML,
            )
        else:
            # User is idle -> start processing immediately
            user_active_tasks.add(user_id)
            q.put_nowait((update, all_items, was_truncated))
            asyncio.create_task(user_worker(user_id))


def start_health_check_server(port: int) -> None:
    """Lightweight background HTTP server for Render/Koyeb web service health checks."""
    from http.server import HTTPServer, BaseHTTPRequestHandler
    import threading

    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"GoFile Bypass Telegram Bot is running!")

        def log_message(self, format, *args):
            pass  # Silence access logs

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    logger.info(f"Render health-check server listening on port {port}")


def main() -> None:
    """Start the bot."""
    if not BOT_TOKEN:
        print(
            "ERROR: BOT_TOKEN is not set!\n"
            "Please set your bot token as an environment variable BOT_TOKEN or in a .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    port = os.getenv("PORT")
    if port:
        try:
            start_health_check_server(int(port))
        except Exception as e:
            logger.warning(f"Could not start health-check server on port {port}: {e}")

    print("Starting GoFile Bypass Telegram Bot (Multi-user, Queue-enabled)...")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("Bot is up and listening for messages. Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()


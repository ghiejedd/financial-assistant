"""
Main entry point for Financial Assistant.
Runs Telegram Bot and FastAPI Dashboard simultaneously.
"""

import asyncio
import logging
import os
import signal
import sys
import threading

import uvicorn
from dotenv import load_dotenv

import database as db
import bot as telegram_bot
from server import app as fastapi_app, sse_notify

# ── Logging Setup ──
logging.basicConfig(
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("financial_assistant")

# Reduce noise from libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main():
    """Main entry point — run bot and dashboard together."""
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token or token == "your_bot_token_here":
        logger.error(
            "❌ TELEGRAM_BOT_TOKEN not set!\n"
            "   1. Create a bot with @BotFather on Telegram\n"
            "   2. Copy the token\n"
            "   3. Create a .env file with: TELEGRAM_BOT_TOKEN=your_token_here"
        )
        sys.exit(1)

    host = os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(os.getenv("DASHBOARD_PORT", "8000"))

    # ── Initialize database ──
    asyncio.run(db.init_db())

    # ── Connect SSE notifications ──
    telegram_bot.set_sse_notify(sse_notify)

    # ── Start FastAPI Dashboard in a thread ──
    logger.info(f"🌐 Dashboard starting on http://localhost:{port}")

    uvicorn_config = uvicorn.Config(
        app=fastapi_app,
        host=host,
        port=port,
        log_level="warning",
        access_log=False,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    dashboard_thread = threading.Thread(
        target=uvicorn_server.run,
        daemon=True,
    )
    dashboard_thread.start()

    # ── Start Telegram Bot (main thread) ──
    logger.info("🤖 Telegram Bot starting...")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("💰 Financial Assistant is running!")
    logger.info(f"📊 Dashboard: http://localhost:{port}")
    logger.info("🤖 Bot: Ready to receive messages")
    logger.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    logger.info("Press Ctrl+C to stop.")

    bot_app = telegram_bot.create_bot(token)
    bot_app.run_polling(drop_pending_updates=True, bootstrap_retries=-1)


if __name__ == "__main__":
    main()

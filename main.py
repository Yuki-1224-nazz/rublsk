#!/usr/bin/env python3
"""
Roblox Cookie Checker Telegram Bot
Fast, accurate cookie validation with Robux capture and user lookup.
"""

import os
import sys
import logging
import asyncio
import signal

from telegram.ext import Application

from utils.config import Config
from bot.handlers import register_handlers
from core.proxy_rotator import ProxyRotator

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Reduce noisy loggers
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)


def setup_directories():
    """Create required directories."""
    os.makedirs(Config.TEMP_DIR, exist_ok=True)
    os.makedirs(Config.RESULTS_DIR, exist_ok=True)


async def post_init(application: Application):
    """Post-initialization hook."""
    logger.info("🤖 Bot starting up...")

    # Pre-load proxies if available
    proxy_rotator = ProxyRotator()
    count = await proxy_rotator.load_proxies()
    if count > 0:
        logger.info(f"🔄 Loaded {count} proxies")
    else:
        logger.info("🔄 Running without proxies (direct connection)")

    # Set bot commands
    from telegram import BotCommand
    await application.bot.set_my_commands([
        BotCommand("start", "Start the bot"),
        BotCommand("check", "Upload cookies file to check"),
        BotCommand("lookup", "Lookup a Roblox user"),
        BotCommand("proxy", "Set custom proxies"),
        BotCommand("stats", "Show current session stats"),
        BotCommand("cancel", "Cancel current check"),
    ])

    logger.info("✅ Bot is ready!")


def main():
    """Main entry point."""
    # Validate config
    if not Config.validate():
        logger.error("❌ BOT_TOKEN not set! Please set the BOT_TOKEN environment variable.")
        sys.exit(1)

    # Setup directories
    setup_directories()

    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()

    # Register handlers
    register_handlers(application)

    # Post-init hook
    application.post_init = post_init

    # Start the bot
    logger.info("🚀 Starting Roblox Cookie Checker Bot...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
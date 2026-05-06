import requests
import telebot
import time
from datetime import datetime
from config import BOT_TOKEN, OWNER_ID

bot = telebot.TeleBot(BOT_TOKEN)

start_time = time.time()
stats = {
    "total": 0,
    "found": 0,
    "not_found": 0,
    "errors": 0,
}


def owner_only(func):
    """Decorator to restrict commands to the owner."""
    def wrapper(message):
        if message.from_user.id != OWNER_ID:
            bot.reply_to(message, "⛔ Access denied. Owner only.")
            return
        return func(message)
    return wrapper


def parse_date(date_str):
    if not date_str:
        return "Unknown Date"
    formats = ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return "Unknown Date"


def get_roblox_user_info(username):
    user_lookup_url = "https://users.roblox.com/v1/usernames/users"
    response = requests.post(user_lookup_url, json={"usernames": [username]})
    response.raise_for_status()

    data = response.json().get("data", [])
    if not data:
        return None

    user_id = data[0]["id"]

    profile = requests.get(f"https://users.roblox.com/v1/users/{user_id}").json()
    friends = requests.get(
        f"https://friends.roblox.com/v1/users/{user_id}/friends/count"
    ).json().get("count", 0)
    followers = requests.get(
        f"https://friends.roblox.com/v1/users/{user_id}/followers/count"
    ).json().get("count", 0)
    badges = requests.get(
        f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100"
    ).json().get("data", [])
    groups = requests.get(
        f"https://groups.roblox.com/v1/users/{user_id}/groups/roles"
    ).json().get("data", [])
    collectibles = requests.get(
        f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=10"
    ).json().get("data", [])

    avatar_resp = requests.get(
        f"https://thumbnails.roblox.com/v1/users/avatar-headshot"
        f"?userIds={user_id}&size=150x150&format=Png"
    ).json()
    avatar_url = "N/A"
    avatar_data = avatar_resp.get("data", [])
    if avatar_data:
        avatar_url = avatar_data[0].get("imageUrl", "N/A")

    description = profile.get("description", "").strip() or "N/A"

    return {
        "UserID": user_id,
        "Username": profile.get("name"),
        "DisplayName": profile.get("displayName"),
        "ProfileURL": f"https://www.roblox.com/users/{user_id}/profile",
        "Description": description,
        "IsBanned": profile.get("isBanned", False),
        "AccountAgeDays": profile.get("age"),
        "JoinDate": parse_date(profile.get("created")),
        "BadgeCount": len(badges),
        "CollectibleCount": len(collectibles),
        "GroupCount": len(groups),
        "FriendCount": friends,
        "FollowerCount": followers,
        "AvatarURL": avatar_url,
    }


def format_user_info(info):
    banned_status = "Yes ⚠️" if info["IsBanned"] else "No"
    return (
        f"🔎 *Roblox User Info*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Username:* `{info['Username']}`\n"
        f"🏷 *Display Name:* `{info['DisplayName']}`\n"
        f"🆔 *User ID:* `{info['UserID']}`\n"
        f"🔗 *Profile:* [Link]({info['ProfileURL']})\n"
        f"📝 *Description:* {info['Description']}\n"
        f"🚫 *Banned:* {banned_status}\n"
        f"📅 *Join Date:* {info['JoinDate']}\n"
        f"📆 *Account Age:* {info['AccountAgeDays']} days\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏅 *Badges:* {info['BadgeCount']}\n"
        f"🎒 *Collectibles:* {info['CollectibleCount']}\n"
        f"👥 *Groups:* {info['GroupCount']}\n"
        f"🤝 *Friends:* {info['FriendCount']}\n"
        f"👣 *Followers:* {info['FollowerCount']}\n"
    )


@bot.message_handler(commands=["start"])
@owner_only
def handle_start(message):
    bot.reply_to(
        message,
        "👋 *Welcome to Roblox User Lookup Bot!*\n\n"
        "Send /lookup `<username>` to search for a Roblox user.\n"
        "Example: `/lookup Roblox`",
        parse_mode="Markdown",
    )


@bot.message_handler(commands=["lookup"])
@owner_only
def handle_lookup(message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.reply_to(message, "Usage: `/lookup <username>`", parse_mode="Markdown")
        return

    username = args[1].strip()
    bot.reply_to(message, f"🔍 Looking up *{username}*...", parse_mode="Markdown")

    try:
        stats["total"] += 1
        info = get_roblox_user_info(username)
        if info:
            stats["found"] += 1
            bot.send_message(
                message.chat.id, format_user_info(info), parse_mode="Markdown"
            )
        else:
            stats["not_found"] += 1
            bot.send_message(
                message.chat.id,
                f"❌ User `{username}` not found.",
                parse_mode="Markdown",
            )
    except Exception as e:
        stats["errors"] += 1
        bot.send_message(message.chat.id, f"❌ Error: {e}")


def format_elapsed(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@bot.message_handler(commands=["stats"])
@owner_only
def handle_stats(message):
    elapsed = time.time() - start_time
    text = (
        f"⚡ *CHECKING STATS* ⚡\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Progress:*\n"
        f"🔑 *Total:* {stats['total']}\n"
        f"💎 *Found:* {stats['found']}\n"
        f"❌ *Not Found:* {stats['not_found']}\n"
        f"⚠️ *Errors:* {stats['errors']}\n"
        f"📝 *Checked:* {stats['total']}/{stats['total']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"⏱️ *Uptime:* {format_elapsed(elapsed)}\n"
        f"━━━━━━━━━━━━━━━━━━━"
    )
    bot.reply_to(message, text, parse_mode="Markdown")


if __name__ == "__main__":
    print("Bot is running...")
    bot.infinity_polling()

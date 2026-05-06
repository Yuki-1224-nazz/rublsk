import requests
import time
from datetime import datetime
from rich.console import Console
from rich.text import Text

# Initialize console
console = Console()

# Custom banner (your design)
custom_banner = """
888~-_            888       888           888   _   
888   \\   e88~-_  888-~88e  888   /~~~8e  888 e~ ~  
888    | d888   i 888  888b 888       88b 888d8b    
888   /  8888   | 888  8888 888  e88~-888 888Y88b   
888_-~   Y888   ' 888  888P 888 C888  888 888 Y88b  
888 ~-_   "88_-~  888-_88"  888  "88_-888 888  Y88b 
"""

# Print the banner and credits
console.print(Text(custom_banner, style="cyan bold"))
console.print(Text("         Adjusted by @KiritaniShinyaa", style="yellow bold"))

def parse_date(date_str):
    formats = ["%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return "Unknown Date"

def get_roblox_user_info(username, password):
    try:
        user_lookup_url = "https://users.roblox.com/v1/usernames/users"
        response = requests.post(user_lookup_url, json={"usernames": [username]})
        response.raise_for_status()
        user_data = response.json().get("data", [])[0]
        user_id = user_data["id"]

        profile = requests.get(f"https://users.roblox.com/v1/users/{user_id}").json()
        friends = requests.get(f"https://friends.roblox.com/v1/users/{user_id}/friends/count").json().get("count", 0)
        followers = requests.get(f"https://friends.roblox.com/v1/users/{user_id}/followers/count").json().get("count", 0)
        badges = requests.get(f"https://badges.roblox.com/v1/users/{user_id}/badges?limit=100").json().get("data", [])
        groups = requests.get(f"https://groups.roblox.com/v1/users/{user_id}/groups/roles").json()
        collectibles = requests.get(f"https://inventory.roblox.com/v1/users/{user_id}/assets/collectibles?limit=10").json().get("data", [])
        avatar = f"https://thumbnails.roblox.com/v1/users/avatar-headshot?userIds={user_id}&size=150x150&format=Png"

        return {
            "USER": username,
            "PASS": password,
            "UserID": user_id,
            "Username": profile.get("name"),
            "DisplayName": profile.get("displayName"),
            "ProfileURL": f"https://www.roblox.com/users/{user_id}/profile",
            "Description": profile.get("description", "N/A"),
            "IsBanned": profile.get("isBanned", False),
            "AccountAgeDays": profile.get("age"),
            "JoinDate": parse_date(profile.get("created")),
            "BadgeCount": len(badges),
            "CollectibleCount": len(collectibles),
            "GroupCount": len(groups),
            "FriendCount": friends,
            "FollowerCount": followers,
            "Avatar": avatar
        }

    except Exception as e:
        console.print(f"× Error fetching {username}: {e}", style="red bold")
        return None

file_name = input("Enter Roblak: ")

try:
    with open(file_name, "r") as file:
        lines = file.read().splitlines()

    accounts = []

    console.print("\n🚀 Fetching data...\n", style="yellow bold")
    for line in lines:
        try:
            username, password = line.split(":", 1)
            username, password = username.strip(), password.strip()
            if username and password:
                accounts.append((username, password))
            else:
                console.print(f"× Skipping invalid entry: {line}", style="red bold")
        except ValueError:
            console.print(f"× Invalid format: {line}", style="red bold")

    output_file_name = "roblak_results.txt"
    with open(output_file_name, "w") as output_file:
        for index, (username, password) in enumerate(accounts, start=1):
            console.print(f"🔍 Checking {index}/{len(accounts)}: {username}...", style="yellow bold")
            info = get_roblox_user_info(username, password)
            if info:
                line_output = " | ".join([f"{key}: {val}" for key, val in info.items()])
                output_file.write(line_output + "\n")
                output_file.write("-" * 80 + "\n")  # Separator line

                console.print(line_output, style="green")
                console.print("-" * 80, style="cyan")
            else:
                console.print(f"× Failed to fetch info for: {username}", style="red bold")
            time.sleep(0.1)

    console.print(f"\n✓ Done! Results saved in '{output_file_name}'.", style="green bold")

except FileNotFoundError:
    console.print("× Error: File not found!", style="red bold")
except Exception as e:
    console.print(f"× Unexpected error: {e}", style="red bold")

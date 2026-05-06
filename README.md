# 🤖 RubLSK - Roblox Cookie Checker Telegram Bot

A fast, accurate, and feature-rich Telegram bot for Roblox cookie validation with Robux capture, user lookup, and proxy rotation.

## ✨ Features

- **⚡ Super Fast Checking** - Async concurrent checking with configurable concurrency (up to 50+ simultaneous)
- **💰 Robux Capture** - Automatically captures Robux balance, premium status, credit, and pending Robux on valid cookies
- **👤 Full User Lookup** - Automatically runs full profile lookup (friends, followers, groups, badges, collectibles) on valid cookies
- **📦 Multi-Format Support** - .txt, .zip, .rar, .7z, .json, .csv, .tsv, .log, .dat, .xml, .yaml and more
- **📁 Per-File Breakdown** - When uploading archives, shows cookie count per file inside
- **🔄 Proxy Rotation** - Smart proxy rotator with health checking and weighted selection
- **💎 Value Tier System** - Automatic account valuation (BASIC → LEGENDARY)
- **📊 Real-time Progress** - Live progress updates during checking
- **🚫 Banned Detection** - Identifies banned accounts separately
- **📁 Results Export** - Full results file + hits-only file with valid cookies

## 🚀 Commands

| Command | Description |
|---------|-------------|
| `/start` | Show welcome menu with inline buttons |
| `/check` | Upload a cookie file to validate |
| `/proxy` | Upload custom proxy list |
| `/stats` | Show current check session stats |
| `/cancel` | Cancel a running check |

> **Note:** User lookup + Robux capture runs **automatically** on every valid cookie found — no separate command needed! Just upload your file with `/check` and the bot does everything.

## 📁 Supported File Formats

- `.txt` - Plain text (one cookie per line)
- `.zip` - ZIP archives (parses each inner file individually, supports nested archives)
- `.rar` - RAR archives (parses each inner file individually)
- `.7z` - 7-Zip archives (parses each inner file individually)
- `.json` - JSON arrays or objects
- `.jsonl` - JSON Lines format
- `.csv` - Comma-separated values
- `.tsv` - Tab-separated values
- `.log` - Log files
- `.dat`, `.cfg`, `.ini` - Config/data files
- `.xml` - XML files
- `.yaml`, `.yml` - YAML files
- Any other text-based format

> **Archive files (.zip, .rar, .7z):** Each file inside the archive is checked individually. You'll see a per-file breakdown showing how many cookies were found in each file. Nested archives (e.g., a .zip inside another .zip) are also supported.

## 🍪 Supported Cookie Formats

The bot automatically extracts cookies from various formats:

- Plain `.ROBLOSECURITY` value
- `.ROBLOSECURITY=cookie_value`
- `cookie:.ROBLOSECURITY=cookie_value`
- JSON: `{"cookie": "value"}`, `{"token": "value"}`
- Key:value pairs
- And more auto-detected formats

## 🚀 Deployment on Railway

### 1. Fork or push this repo to GitHub

### 2. Create a new Railway project
- Go to [railway.app](https://railway.app)
- Click "New Project" → "Deploy from GitHub repo"
- Select your repository

### 3. Set environment variables
In the Railway dashboard, add these variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `BOT_TOKEN` | ✅ | Your Telegram bot token from @BotFather |
| `PROXY_ENABLED` | ❌ | Enable proxy rotation (default: true) |
| `PROXY_FILE` | ❌ | Path to proxy file (default: proxies.txt) |
| `MAX_CONCURRENT` | ❌ | Max concurrent checks (default: 50) |
| `CHECK_TIMEOUT` | ❌ | Timeout per check in seconds (default: 15) |
| `DELAY_BETWEEN` | ❌ | Delay between checks (default: 0.05) |

### 4. Deploy
Railway will auto-detect the Python project and deploy using the Procfile.

## 🛠 Local Development

```bash
# Clone the repo
git clone https://github.com/Yuki-1224-nazz/rublsk.git
cd rublsk

# Install dependencies
pip install -r requirements.txt

# Set bot token
export BOT_TOKEN="your_bot_token_here"

# Run
python main.py
```

## 🔄 Proxy Setup

Create a `proxies.txt` file in the project root with one proxy per line:

```
# Format: ip:port
192.168.1.1:8080

# Format: ip:port:user:pass
10.0.0.1:3128:myuser:mypass

# Format: protocol://ip:port
socks5://10.0.0.2:1080

# Format: protocol://user:pass@ip:port
http://user:pass@proxy.example.com:8080
```

Or upload proxies through the bot using `/proxy`.

## 📊 Value Tier System

| Tier | Criteria |
|------|----------|
| 💤 BASIC | Low value account |
| 📝 OK | Some activity |
| ✨ GOOD | Moderate value |
| 🔥 RARE | High value (lots of Robux/limiteds) |
| ⭐ LEGENDARY | Exceptional account |

## 📁 Project Structure

```
rublsk/
├── main.py              # Entry point
├── bot/
│   ├── __init__.py
│   ├── handlers.py      # Telegram bot handlers
│   └── sessions.py      # User session management
├── core/
│   ├── __init__.py
│   ├── cookie_checker.py # Main checking engine
│   ├── proxy_rotator.py  # Smart proxy rotation
│   ├── file_parser.py    # Multi-format file parser
│   ├── robux_capture.py  # Robux & financial capture
│   └── user_lookup.py    # Roblox user profile lookup
├── utils/
│   ├── __init__.py
│   ├── config.py         # Configuration manager
│   └── helpers.py        # Utility functions
├── requirements.txt
├── Procfile
├── runtime.txt
├── railway.json
└── README.md
```

## ⚠️ Disclaimer

This tool is for educational purposes only. Use responsibly and in accordance with Roblox's Terms of Service.
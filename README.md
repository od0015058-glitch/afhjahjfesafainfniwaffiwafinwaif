# Archive Bot

[• English •](README.md) | [• فارسی •](README.fa.md)

An async Telegram bot that collects videos/files in a queue and creates an archive of them.

## Features

- Queue Telegram documents, videos, audio files, animations, voice messages, and video notes
- Reply to a queued file and send `/delete` to remove it
- Duplicate detection before archiving with the option to keep or remove duplicate files
- Smart format suggestion based on file metadata
- Supported formats: ZIP, RAR, 7Z, TAR, TAR.GZ, TAR.BZ2, TAR.XZ, TAR.ZSTD, TAR.ZST, GZ, XZ, ZST
- Compression level prompt with CPU-load explanation
- Optional archive password for supported formats
- Maximum output size prompt, with the default being 2000 MB
- Split large archives into numbered parts
- Create multiple independent archives for large queues
- Download status with speed, elapsed time, ETA, and transferred amount
- Telegram upload heartbeat with elapsed time since Telegram upload path does not expose reliable byte progress
- The ability to send a custom archive name with safe character limits
- Runtime cleanup at startup, job start, job finish, and shutdown

## Supported password formats

| Format | Password support | Requirement |
|---|---|---|
| 7Z | Yes | `7z` |
| ZIP | Yes | `7z` |
| RAR | Yes | `rar` |
| TAR / TAR.GZ / TAR.BZ2 / TAR.XZ / TAR.ZST | No | Not applicable |

For 7Z, the bot uses encrypted headers.

## Requirements

- Python 3.11 or 3.12 recommended
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- Telegram API credentials from <https://my.telegram.org> (You can also use [This](https://t.me/ApiHashGeneratorBot) bot.)
- Linux server recommended
- Optional command-line tools:
  - `p7zip-full` for 7Z and password-protected ZIP
  - `zstd` for TAR.ZST / TAR.ZSTD
  - `rar` for RAR archives

## Installation

### 1. Install system packages

Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip p7zip-full zstd
```

To install RAR:

```bash
sudo apt install -y rar
```

If that fails, read the troubleshooting section.

### 2. Clone the repository

```bash
git clone https://github.com/BlueMammad/TelegramArchiveBot.git
cd TelegramArchiveBot
```

### 3. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

### 4. Configure `.env`

```bash
cp .env.example .env
nano .env
```

Example:

```env
API_ID=123456
API_HASH=your_api_hash
BOT_TOKEN=123456:your_bot_token
ARCHIVE_BOT_DATA=./archive_bot_data
MAX_PARALLEL_DOWNLOADS=3
MAX_PARALLEL_JOBS=1
MAX_PARALLEL_UPLOADS=1
DEFAULT_MAX_MB=2000
EDIT_INTERVAL=4.0
SEND_INTERVAL=1.1
DRAFT_INTERVAL=4.0
BURST_SUMMARY_DELAY=3.0
```

### 5. Run the bot

```bash
python3 bot.py
```

Expected output:

```text
Archive bot is running. Press Ctrl+C to stop.
```

## BotFather access control

Create your bot with [@BotFather](https://t.me/BotFather), copy the token, and put it in `.env`.

If you want the bot to be usable only by you, open your bot settings in @BotFather and configure the allowed users so only your Telegram account can use it.

## Usage

1. Send files or videos to the bot.
2. Wait for the queue summary to appear after the burst settles.
3. To remove a file, reply to that file and send `/delete`.
4. Click **Compress all**.
5. Pick the format.
6. Pick the compression level.
7. Pick the maximum output size.
8. Set a password if supported, or skip.
9. Choose the default archive name or send a custom safe name.
10. If duplicates are detected, choose whether to keep or remove them.
11. Start the job.
12. Download the archive or archive parts.

## Split archives

If the output exceeds the part limit, the bot can create files like:

```text
archive.tar.zst.part001
archive.tar.zst.part002
archive.tar.zst.part003
```

Download every part before joining/extracting.

On Linux:

```bash
cat archive.tar.zst.part* > archive.tar.zst
```

Then extract normally.

## Running with systemd

```bash
sudo nano /etc/systemd/system/archivebot.service
```

Example:

```ini
[Unit]
Description=Archive Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/TelegramArchiveBot
ExecStart=/root/TelegramArchiveBot/venv/bin/python /root/TelegramArchiveBot/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable archivebot
sudo systemctl start archivebot
sudo systemctl status archivebot
```

Logs:

```bash
journalctl -u archivebot -f
```

## Troubleshooting

### Permission denied while installing packages

```bash
cd ~/TelegramArchiveBot
deactivate 2>/dev/null || true
sudo chown -R "$USER:$USER" ~/TelegramArchiveBot
rm -rf venv
python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -r requirements.txt
```

If you cloned the repository as root, use `/root/TelegramArchiveBot` instead of `~/TelegramArchiveBot`.

### `externally-managed-environment`

You are installing into system Python. Use a virtual environment.

```bash
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

### Missing `API_ID`, `API_HASH`, or `BOT_TOKEN`

Make sure `.env` exists next to `bot.py`.

```bash
ls -la .env
```

### Python 3.13 event-loop issues

Use Python 3.11 or 3.12 if your PyroTGFork build has event-loop issues.

### `rar` package cannot be installed

Some distributions do not include the proprietary `rar` package
in their default repositories.

You can install it manually from the official RARLAB release:

```bash
wget https://www.rarlab.com/rar/rarlinux-x64-701.tar.gz

tar -xf rarlinux-x64-701.tar.gz

cd rar

sudo install -Dm755 rar /usr/local/bin/rar
```

Verify installation:

```bash
rar
```

If installing `rar` is not possible, use another archive format instead.

The bot only errors when `rar` is selected and the `rar` binary
is missing from the system.

The bot only errors when RAR is selected and the `rar` command is missing, so installing RAR is optional.

### `zstd is not installed`

```bash
sudo apt install -y zstd
```

### `7z is not installed`

```bash
sudo apt install -y p7zip-full
```

### Old files remain on disk

The bot cleans:

- Runtime folders on startup
- Per-user work/output folders when a new job starts
- Downloaded source files after a job
- Runtime folders on shutdown

If files remain, fix permissions:

```bash
sudo chown -R "$USER:$USER" ./archive_bot_data
```

## Environment variables

| Variable | Default | Description |
|---|---:|---|
| `API_ID` | required | Telegram API ID |
| `API_HASH` | required | Telegram API hash |
| `BOT_TOKEN` | required | Bot token |
| `ARCHIVE_BOT_DATA` | `./archive_bot_data` | Runtime folder |
| `MAX_PARALLEL_DOWNLOADS` | `3` | Concurrent downloads |
| `MAX_PARALLEL_JOBS` | `1` | Concurrent archive jobs |
| `MAX_PARALLEL_UPLOADS` | `1` | Concurrent uploads |
| `DEFAULT_MAX_MB` | `2000` | Default output part size |
| `EDIT_INTERVAL` | `4.0` | Minimum edit interval |
| `SEND_INTERVAL` | `1.1` | Minimum send interval per chat |
| `DRAFT_INTERVAL` | `4.0` | Legacy interval value |
| `BURST_SUMMARY_DELAY` | `3.0` | Delay before recreating queue summary |

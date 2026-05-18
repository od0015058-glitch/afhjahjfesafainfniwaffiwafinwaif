from dotenv import load_dotenv
load_dotenv()

import asyncio
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import string
import time
import uuid
import zipfile
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiohttp
import aiofiles
from pyrogram import Client, filters
from pyrogram.types import Message, CallbackQuery

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_API_BASE = os.environ.get("BOT_API_BASE", "https://api.telegram.org")
ROOT_DIR = Path(os.environ.get("ARCHIVE_BOT_DATA", "./archive_bot_data")).resolve()
MAX_PARALLEL_DOWNLOADS = int(os.environ.get("MAX_PARALLEL_DOWNLOADS", "3"))
MAX_PARALLEL_JOBS = int(os.environ.get("MAX_PARALLEL_JOBS", "1"))
MAX_PARALLEL_UPLOADS = int(os.environ.get("MAX_PARALLEL_UPLOADS", "1"))
DEFAULT_MAX_MB = int(os.environ.get("DEFAULT_MAX_MB", "2000"))
EDIT_INTERVAL = float(os.environ.get("EDIT_INTERVAL", "4.0"))
SEND_INTERVAL = float(os.environ.get("SEND_INTERVAL", "1.1"))
DRAFT_INTERVAL = float(os.environ.get("DRAFT_INTERVAL", "4.0"))
BURST_SUMMARY_DELAY = float(os.environ.get("BURST_SUMMARY_DELAY", "3.0"))

ROOT_DIR.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DIR = ROOT_DIR / "downloads"
WORK_DIR = ROOT_DIR / "work"
OUTPUT_DIR = ROOT_DIR / "outputs"
for _d in (DOWNLOAD_DIR, WORK_DIR, OUTPUT_DIR):
    _d.mkdir(parents=True, exist_ok=True)

app: Client | None = None

download_queue: asyncio.Queue = asyncio.Queue()
job_queue: asyncio.Queue = asyncio.Queue()
download_sem = asyncio.Semaphore(MAX_PARALLEL_DOWNLOADS)
job_sem = asyncio.Semaphore(MAX_PARALLEL_JOBS)
upload_sem = asyncio.Semaphore(MAX_PARALLEL_UPLOADS)

safe_chars = f"-_.() {string.ascii_letters}{string.digits}"

@dataclass
class FileItem:
    id: str
    file_id: str
    name: str
    size: int
    mime: str
    kind: str
    message_id: int                  # Telegram message that carried the file
    path: str | None = None
    status: str = "queued"           # queued | downloading | done | error
    error: str | None = None
    progress: float = 0.0
    unique_id: str | None = None
    file_msg_id: int | None = None

@dataclass
class UserState:
    user_id: int
    chat_id: int
    items: list[FileItem] = field(default_factory=list)
    step: str = "idle"
    format: str | None = None
    level: int = 1
    max_mb: int = DEFAULT_MAX_MB
    overflow: str | None = None
    password: str | None = None
    archive_base_name: str = "archive"
    status_message_id: int | None = None
    welcome_message_id: int | None = None
    temp: dict[str, Any] = field(default_factory=dict)
    busy: bool = False

states: dict[int, UserState] = {}
last_edits: dict[tuple[int, int], float] = {}
last_sends: dict[int, float] = {}

FORMATS: dict[str, dict[str, Any]] = {
    "zip":      {"title": "ZIP",      "category": "Universal",       "levels": (0, 9),  "default": 1,
                 "text": "Most compatible. Good for sharing, weak extra compression on videos."},
    "rar":      {"title": "RAR",      "category": "Universal",       "levels": (0, 5),  "default": 1,
                 "text": "Good compression and recovery options if rar is installed on the server."},
    "7z":       {"title": "7Z",       "category": "High Compression","levels": (0, 9),  "default": 1,
                 "text": "Strong compression. Usually better than ZIP, heavier on CPU at high levels."},
    "tar":      {"title": "TAR",      "category": "Unix Archive",    "levels": (0, 0),  "default": 0,
                 "text": "Archive only, no compression. Fastest when files are already compressed."},
    "tar.gz":   {"title": "TAR.GZ",   "category": "Unix Archive",    "levels": (1, 9),  "default": 1,
                 "text": "Very compatible on Linux. Fast compression, moderate ratio."},
    "tar.bz2":  {"title": "TAR.BZ2",  "category": "Unix Archive",    "levels": (1, 9),  "default": 1,
                 "text": "Older high-compression option. Usually slower than gzip."},
    "tar.xz":   {"title": "TAR.XZ",   "category": "Unix Archive",    "levels": (0, 9),  "default": 1,
                 "text": "Excellent ratio for text/code. Slow and CPU-heavy at high levels."},
    "tar.zstd": {"title": "TAR.ZSTD", "category": "Modern",          "levels": (1, 19), "default": 3,
                 "text": "Modern sweet spot. Great speed/ratio balance if zstd is installed."},
    "tar.zst":  {"title": "TAR.ZST",  "category": "Modern",          "levels": (1, 19), "default": 3,
                 "text": "Same as TAR.ZSTD with shorter extension."},
    "gz":       {"title": "GZ",       "category": "Single Stream",   "levels": (1, 9),  "default": 1,
                 "text": "Single-file stream compression. For multiple files, TAR.GZ is better."},
    "xz":       {"title": "XZ",       "category": "Single Stream",   "levels": (0, 9),  "default": 1,
                 "text": "Single-file high compression. For multiple files, TAR.XZ is better."},
    "zst":      {"title": "ZST",      "category": "Single Stream",   "levels": (1, 19), "default": 3,
                 "text": "Single-file zstd compression. For multiple files, TAR.ZST is better."},
}

VIDEO_EXT   = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".flv", ".wmv", ".ts", ".m2ts"}
ARCHIVE_EXT = {".zip", ".rar", ".7z", ".gz", ".xz", ".zst", ".bz2", ".tar"}
IMAGE_EXT   = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".avif", ".gif"}
AUDIO_EXT   = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}

def get_state(user_id: int, chat_id: int) -> UserState:
    state = states.get(user_id)
    if not state:
        state = UserState(user_id=user_id, chat_id=chat_id)
        states[user_id] = state
    state.chat_id = chat_id
    return state

def clean_name(name: str) -> str:
    cleaned = "".join(c for c in name if c in safe_chars).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:180] or "file"

def human_size(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size or 0)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"

def button(text: str, data: str, style: str | None = None) -> dict[str, str]:
    item = {"text": text, "callback_data": data}
    if style:
        item["style"] = style
    return item

def kb(rows: list[list[dict[str, str]]]) -> dict[str, Any]:
    return {"inline_keyboard": rows}

def progress_bar(value: float, width: int = 12) -> str:
    value = max(0.0, min(1.0, value))
    filled = int(round(value * width))
    return "▰" * filled + "▱" * (width - filled)

def file_token(user_id: int, message_id: int, name: str) -> str:
    raw = f"{user_id}:{message_id}:{name}:{uuid.uuid4().hex}".encode()
    return hashlib.sha256(raw).hexdigest()[:16]

def ready_items(state: UserState) -> list[FileItem]:
    return [i for i in state.items if i.status == "done" and i.path and Path(i.path).exists()]

def _delete_path(p: str | Path | None) -> None:
    if not p:
        return
    with contextlib.suppress(Exception):
        Path(p).unlink(missing_ok=True)

def _delete_tree(p: Path | None) -> None:
    if not p or not p.exists():
        return
    with contextlib.suppress(Exception):
        shutil.rmtree(p, ignore_errors=True)

def cleanup_runtime_files() -> None:
    for directory in (DOWNLOAD_DIR, WORK_DIR, OUTPUT_DIR):
        _delete_tree(directory)
        directory.mkdir(parents=True, exist_ok=True)

async def bot_api(method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    url = f"{BOT_API_BASE.rstrip('/')}/bot{BOT_TOKEN}/{method}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload,
                                    timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json(content_type=None)
                return data if isinstance(data, dict) else None
    except Exception:
        return None

async def _rate_gate(chat_id: int) -> None:
    """Enforce SEND_INTERVAL between successive sendMessage calls to the same chat."""
    now = time.monotonic()
    wait = SEND_INTERVAL - (now - last_sends.get(chat_id, 0))
    if wait > 0:
        await asyncio.sleep(wait)
    last_sends[chat_id] = time.monotonic()

async def send_ui(
    chat_id: int,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    reply_to: int | None = None,
) -> int | None:
    await _rate_gate(chat_id)
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    data = await bot_api("sendMessage", payload)
    if data and data.get("ok"):
        return data["result"]["message_id"]
    with contextlib.suppress(Exception):
        msg = await app.send_message(chat_id, text, reply_to_message_id=reply_to)
        return msg.id
    return None

async def edit_ui(
    chat_id: int,
    message_id: int | None,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    force: bool = False,
) -> None:
    if not message_id:
        return
    key = (chat_id, message_id)
    now = time.monotonic()
    if not force and now - last_edits.get(key, 0) < EDIT_INTERVAL:
        return
    last_edits[key] = now
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = await bot_api("editMessageText", payload)
    if data and data.get("ok"):
        return
    with contextlib.suppress(Exception):
        await app.edit_message_text(chat_id, message_id, text)

async def answer(cq: CallbackQuery, text: str = "", alert: bool = False) -> None:
    with contextlib.suppress(Exception):
        await cq.answer(text, show_alert=alert)

async def delete_message(chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    await bot_api("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

async def send_draft(chat_id: int, text: str, reply_to: int | None = None) -> None:
    """Fire-and-forget progress note. NOT rate-gated (used from thread callbacks)."""
    payload: dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True
    await bot_api("sendMessage", payload)

def duplicate_groups(items: list[FileItem]) -> list[list[FileItem]]:
    buckets: dict[str, list[FileItem]] = {}
    for item in items:
        key = item.unique_id or f"{item.name}:{item.size}:{item.mime}"
        buckets.setdefault(key, []).append(item)
    return [group for group in buckets.values() if len(group) > 1]

def duplicate_count(items: list[FileItem]) -> int:
    return sum(len(group) - 1 for group in duplicate_groups(items))

def remove_duplicate_items(state: UserState) -> int:
    removed = 0
    keep_ids: set[str] = set()
    new_items: list[FileItem] = []
    for item in state.items:
        key = item.unique_id or f"{item.name}:{item.size}:{item.mime}"
        if key in keep_ids:
            _delete_path(item.path)
            removed += 1
            continue
        keep_ids.add(key)
        new_items.append(item)
    state.items = new_items
    return removed

def duplicate_text(state: UserState) -> str:
    groups = duplicate_groups(state.items)
    count = duplicate_count(state.items)
    preview: list[str] = []
    for group in groups[:5]:
        preview.append(f"• {group[0].name} ×{len(group)}")
    more = len(groups) - len(preview)
    if more > 0:
        preview.append(f"• … and {more} more duplicate group(s)")
    return "\n".join([
        "🧬 <b>Duplicate files detected</b>",
        "",
        f"I found <b>{count}</b> duplicate file(s) in <b>{len(groups)}</b> group(s).",
        "",
        "\n".join(preview),
        "",
        "Do you want to keep all copies, or remove duplicates before creating the archive?"
    ])

def duplicate_keyboard() -> dict[str, Any]:
    return kb([
        [button("📌 Keep duplicates", "dup_keep", "primary")],
        [button("🧹 Remove duplicates", "dup_delete", "success")],
        [button("‹ Back", "back_list", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def guess_format(items: list[FileItem]) -> tuple[str, str]:
    if not items:
        return "tar.zst", "No files yet. TAR.ZST is a modern default."
    exts = [Path(i.name.lower()).suffix for i in items]
    total = sum(i.size for i in items)
    media_count = sum(1 for e in exts if e in VIDEO_EXT | IMAGE_EXT | AUDIO_EXT | ARCHIVE_EXT)
    textish_count = sum(1 for e in exts if e in {
        ".txt", ".json", ".csv", ".log", ".xml", ".html", ".css",
        ".js", ".ts", ".py", ".go", ".rs", ".java", ".md", ".sql",
    })
    if media_count >= max(1, len(items) * 0.65):
        return "tar", "Most files are already compressed — TAR skips CPU waste."
    if len(items) == 1 and total >= 1024 ** 3:
        return "tar.zst", "One large file — ZSTD balances speed and ratio well."
    if textish_count >= max(1, len(items) * 0.5):
        return "tar.zst", "Mostly text/code — TAR.ZST compresses well without XZ CPU cost."
    return "tar.zst", "Mixed files — TAR.ZST is usually the best speed/size balance."

def clean_archive_base_name(name: str) -> str:
    cleaned = "".join(c for c in name if c in safe_chars).strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = cleaned.strip("._- ")
    return cleaned[:64] or "archive"

def archive_name_text(state: UserState) -> str:
    return "\n".join([
        "🏷 <b>Archive name</b>",
        "",
        f"Default: <b>{state.archive_base_name}</b>",
        "",
        "Send a custom name, or click the default button.",
        "",
        "Limits: 1–64 safe characters. Letters, numbers, spaces, dots, dashes, underscores and parentheses are allowed.",
    ])

def archive_name_keyboard() -> dict[str, Any]:
    return kb([
        [button("Use default archive name", "name_default", "success")],
        [button("‹ Back", "back_password", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def upload_heartbeat_text(filename: str, index: int, total: int, file_size: int, started: float, tick: int = 0) -> str:
    elapsed = duration_text(time.monotonic() - started)
    frames = ["▰▱▱", "▰▰▱", "▰▰▰", "▱▰▰", "▱▱▰", "▱▱▱"]
    frame = frames[tick % len(frames)]
    return "\n".join([
        "📤 <b>Uploading to Telegram</b>",
        "",
        f"{frame} <b>{index} / {total}</b>",
        f"◇ File: <b>{filename}</b>",
        f"◇ Size: <b>{human_size(file_size)}</b>",
        f"◇ Time spent: <b>{elapsed}</b>",
        "",
        "Telegram is accepting the file in big chunks. The library may wait between chunks, so this can look paused even when it is still working.",
    ])

def archive_name(fmt: str, index: int | None = None, base_name: str = "archive") -> str:
    base = clean_archive_base_name(base_name)
    stem = base if index is None else f"{base}_{index:03d}"
    return f"{stem}.{fmt}"

def predicted_archive_names(state: UserState) -> list[str]:
    fmt = state.format or "tar.zst"
    items = state.items
    total = sum(i.size for i in items)
    max_bytes = max(1, state.max_mb) * 1024 * 1024
    if state.overflow == "groups" and total > max_bytes:
        groups = group_items(items, max_bytes)
        return [archive_name(fmt, i, state.archive_base_name) for i in range(1, len(groups) + 1)]
    if total > max_bytes:
        return [f"{archive_name(fmt, base_name=state.archive_base_name)}.part001", f"{archive_name(fmt, base_name=state.archive_base_name)}.part002", "…"]
    return [archive_name(fmt, base_name=state.archive_base_name)]


WELCOME_TEXT = (
    "👋 <b>Archive Bot</b>\n\n"
    "Send me files or videos and I'll queue them up.\n"
    "When you're ready, click <b>Compress all</b> in the queue message "
    "and I'll pack everything into ZIP, 7Z, TAR.ZST and more.\n\n"
    "Large outputs are split automatically.\n\n"
    "📘 Setup docs and language-specific READMEs are available on GitHub:\n"
    "https://github.com/BlueMammad/TelegramArchiveBot"
)

def summary_text(state: UserState) -> str:
    total = sum(i.size for i in state.items)
    lines = [
        "📦 <b>Archive queue</b>",
        f"◇ Files: <b>{len(state.items)}</b>",
        f"◇ Total metadata size: <b>{human_size(total)}</b>",
        "",
    ]
    if not state.items:
        lines.append("Send videos or files and I will add them here.")
    else:
        quoted: list[str] = []
        for idx, item in enumerate(state.items[:10], 1):
            icon = {"done": "✅", "downloading": "⬇️", "queued": "⏳", "error": "⚠️"}.get(item.status, "•")
            quoted.append(f"{idx}. {icon} <b>{item.name}</b> · {human_size(item.size)}")
        if len(state.items) > 10:
            quoted.append(f"… and {len(state.items) - 10} more")
        lines.append("<blockquote expandable>" + "\n".join(quoted) + "</blockquote>")
        lines.extend([
            "",
            "🗑 To delete a specific queued file, reply to that file and send <code>/delete</code>.",
        ])
    fmt, reason = guess_format(state.items)
    lines.extend(["", f"💡 Suggested: <b>{FORMATS[fmt]['title']}</b>", f"↳ {reason}"])
    return "\n".join(lines)

def summary_keyboard(state: UserState) -> dict[str, Any]:
    rows: list[list[dict]] = []
    if state.items:
        rows.append([button("🧹 Clear list", "clear_ask", "danger")])
        rows.append([button("🧊 Compress all", "compress_all", "primary")])
    return kb(rows)

def file_msg_text(item: FileItem) -> str:
    icon = {"done": "✅", "downloading": "⬇️", "queued": "⏳", "error": "⚠️"}.get(item.status, "•")
    base = f"{icon} <b>{item.name}</b>\n◇ {human_size(item.size)}"
    if item.status == "downloading" and item.progress > 0:
        base += f"\n{progress_bar(item.progress)} {item.progress * 100:.0f}%"
    if item.status == "error" and item.error:
        base += f"\n⚠️ {item.error[:200]}"
    return base

def file_msg_keyboard(item: FileItem) -> dict[str, Any]:
    return kb([[button("🗑 Remove this file", f"remove:{item.id}")]])

def format_text(state: UserState) -> str:
    suggested, reason = guess_format(state.items)
    return "\n".join([
        "🧊 <b>Choose archive format</b>",
        "",
        f"✨ Smart suggestion: <b>{FORMATS[suggested]['title']}</b>",
        f"↳ {reason}",
        "",
        "▣ <b>Universal</b>  ZIP · RAR · 7Z",
        "▣ <b>Unix archives</b>  TAR · TAR.GZ · TAR.BZ2 · TAR.XZ · TAR.ZST",
        "▣ <b>Single stream</b>  GZ · XZ · ZST",
    ])

def format_keyboard(state: UserState) -> dict[str, Any]:
    s, _ = guess_format(state.items)
    def btn(fmt: str) -> dict:
        label = FORMATS[fmt]["title"]
        return button(("✨ " if s == fmt else "") + label, f"fmt:{fmt}", "success" if s == fmt else "primary")
    return kb([
        [btn("zip"), btn("rar"), btn("7z")],
        [btn("tar"), btn("tar.gz"), btn("tar.bz2")],
        [btn("tar.xz"), btn("tar.zstd"), btn("tar.zst")],
        [btn("gz"), btn("xz"), btn("zst")],
        [button("‹ Back", "back_list", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def level_text(fmt: str) -> str:
    meta = FORMATS[fmt]
    lo, hi = meta["levels"]
    default = meta["default"]
    if lo == hi:
        return (f"⚙️ <b>Compression level</b>\n\n"
                f"<b>{meta['title']}</b> has no level option. "
                f"I will use level <b>{default}</b>.\n\nTap Continue.")
    return "\n".join([
        "⚙️ <b>Compression level</b>",
        f"Format: <b>{meta['title']}</b>   Range: <b>{lo}–{hi}</b>   Default: <b>{default}</b>",
        "",
        "Lower = faster, less compression.  Higher = slower, smaller output.",
        "Send a number or tap the default button.",
    ])

def level_keyboard(fmt: str) -> dict[str, Any]:
    default = FORMATS[fmt]["default"]
    return kb([
        [button(f"Use default ({default})", f"level:{default}", "success")],
        [button("‹ Back", "back_format", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def max_text(state: UserState) -> str:
    return "\n".join([
        "📏 <b>Maximum output part size</b>",
        f"Default: <b>{DEFAULT_MAX_MB} MB</b>",
        "",
        "If the archive exceeds this limit it will be split or grouped.",
        "Send a size in MB, or tap the default button.",
    ])

def max_keyboard() -> dict[str, Any]:
    return kb([
        [button(f"Use default ({DEFAULT_MAX_MB} MB)", f"max:{DEFAULT_MAX_MB}", "success")],
        [button("‹ Back", "back_level", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def overflow_text(state: UserState) -> str:
    return "\n".join([
        "🧩 <b>Input is larger than the output limit</b>",
        "",
        "◇ <b>Split archive</b> — one archive split into numbered parts.",
        "◇ <b>Multiple archives</b> — independent archives, each extractable on its own.",
    ])

def overflow_keyboard() -> dict[str, Any]:
    return kb([
        [button("✂️ Split archive", "overflow:split", "primary"),
         button("📚 Multiple archives", "overflow:groups", "success")],
        [button("‹ Back", "back_max", "primary"), button("✕ Cancel", "cancel_ask", "danger")],
    ])

def format_supports_password(fmt: str) -> bool:
    return fmt in {"zip", "rar", "7z"}

def password_text(state: UserState) -> str:
    fmt = state.format or "tar.zst"
    if not format_supports_password(fmt):
        return "\n".join([
            "🔐 <b>Password protection is unavailable</b> for <b>TAR/TAR.GZ/TAR.XZ/TAR.ZST</b> archives because these formats do <b>not support built-in encryption</b>.",
            "",
            "Click continue to proceed without a password.",
        ])
    return "\n".join([
        "🔐 <b>Password protection</b>",
        "",
        f"Format: <b>{FORMATS[fmt]['title']}</b>",
        "",
        "Send a password to encrypt the archive, or click Skip.",
        "Use a strong password and keep it safe. I cannot recover it later.",
    ])

def password_keyboard(state: UserState) -> dict[str, Any]:
    fmt = state.format or "tar.zst"
    rows: list[list[dict[str, str]]] = []
    if format_supports_password(fmt):
        rows.append([button("⏭ Skip password", "pass_skip", "primary")])
    else:
        rows.append([button("Continue", "pass_skip", "primary")])
    rows.append([button("‹ Back", "back_max", "primary"), button("✕ Cancel", "cancel_ask", "danger")])
    return kb(rows)

def duration_text(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"

def transfer_stats(done: int, total: int, started: float) -> tuple[str, str, str]:
    elapsed = max(0.001, time.monotonic() - started)
    speed = done / elapsed
    remaining = max(0, total - done)
    eta = remaining / speed if speed > 0 else 0
    return human_size(int(speed)) + "/s", duration_text(elapsed), duration_text(eta)

def verify_deleted(paths: list[Path]) -> tuple[int, int]:
    deleted = 0
    remaining = 0
    for path in paths:
        if path.exists():
            remaining += 1
        else:
            deleted += 1
    return deleted, remaining

def confirm_compress_text(state: UserState) -> str:
    items = state.items
    fmt = state.format or "tar.zst"
    total = sum(i.size for i in items)
    names = predicted_archive_names(state)
    names_str = "\n".join(f"  • {n}" for n in names)
    return "\n".join([
        "✅ <b>Ready to compress</b>",
        "",
        f"◇ Files: <b>{len(items)}</b>   Total size: <b>{human_size(total)}</b>",
        f"◇ Format: <b>{FORMATS[fmt]['title']}</b>   Level: <b>{state.level}</b>",
        f"◇ Part limit: <b>{state.max_mb} MB</b>",
        f"◇ Password: <b>{'enabled' if state.password else 'not set'}</b>",
        f"◇ Archive name: <b>{state.archive_base_name}</b>",
        "",
        "<b>Expected output file(s):</b>",
        names_str,
        "",
        "Tap <b>Start</b> to begin, or go back to change settings.",
    ])

def confirm_compress_keyboard() -> dict[str, Any]:
    return kb([
        [button("🚀 Start", "job_start", "success"), button("✕ Cancel", "cancel_ask", "danger")],
        [button("‹ Format", "back_format", "primary"),
         button("‹ Level", "back_level", "primary"),
         button("‹ Limit", "back_max", "primary")],
    ])

def confirm_clear_text() -> str:
    return "⚠️ <b>Clear the whole queue?</b>\n\nThis removes every file and deletes downloaded copies."

def confirm_cancel_text() -> str:
    return "⚠️ <b>Cancel current operation?</b>\n\nAlready downloaded files stay in the queue."

def confirm_keyboard(yes: str, no: str) -> dict[str, Any]:
    return kb([[button("Yes, confirm", yes, "danger"), button("No, go back", no, "success")]])

async def refresh_summary(state: UserState, force: bool = False) -> None:
    """Edit (or create) the single persistent queue summary message."""
    text = summary_text(state)
    markup = summary_keyboard(state)
    if state.status_message_id:
        await edit_ui(state.chat_id, state.status_message_id, text, markup, force=force)
    else:
        state.status_message_id = await send_ui(state.chat_id, text, markup)

async def refresh_file_msg(state: UserState, item: FileItem) -> None:
    """Edit (or create) the per-file reply message."""
    text = file_msg_text(item)
    markup = file_msg_keyboard(item)
    if item.file_msg_id:
        await edit_ui(state.chat_id, item.file_msg_id, text, markup, force=True)
    else:
        item.file_msg_id = await send_ui(
            state.chat_id, text, markup, reply_to=item.message_id
        )

_refresh_tasks: dict[int, asyncio.Task] = {}

async def _coalesced_summary(state: UserState) -> None:
    await asyncio.sleep(BURST_SUMMARY_DELAY)
    old_id = state.status_message_id
    state.status_message_id = None
    if old_id:
        await delete_message(state.chat_id, old_id)
    await refresh_summary(state, force=True)
    _refresh_tasks.pop(state.user_id, None)

def schedule_summary_refresh(state: UserState) -> None:
    existing = _refresh_tasks.get(state.user_id)
    if existing and not existing.done():
        existing.cancel()
    _refresh_tasks[state.user_id] = asyncio.create_task(_coalesced_summary(state))

def command_exists(name: str) -> bool:
    return shutil.which(name) is not None

async def run_cmd(cmd: list[str], cwd: Path | None = None,
                  env: dict | None = None) -> None:
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        err = (stderr.decode(errors="ignore") or stdout.decode(errors="ignore")
               or "command failed")
        raise RuntimeError(err.strip()[:1000])

async def write_manifest(items: list[FileItem], directory: Path) -> Path:
    manifest = directory / "manifest.json"
    data = [{"name": i.name, "size": i.size, "kind": i.kind, "mime": i.mime}
            for i in items]
    async with aiofiles.open(manifest, "w", encoding="utf-8") as f:
        await f.write(json.dumps(data, ensure_ascii=False, indent=2))
    return manifest

def tar_mode(fmt: str, level: int) -> tuple[str, dict[str, Any]]:
    if fmt == "tar":
        return "w", {}
    if fmt in ("tar.gz", "gz"):
        return "w:gz", {"compresslevel": max(1, min(9, level))}
    if fmt == "tar.bz2":
        return "w:bz2", {"compresslevel": max(1, min(9, level))}
    if fmt in ("tar.xz", "xz"):
        return "w:xz", {"preset": max(0, min(9, level))}
    return "w", {}

async def make_python_archive(items: list[FileItem], fmt: str, level: int,
                               output: Path, status_cb, password: str | None = None) -> None:
    source_paths = [Path(i.path) for i in items if i.path]
    loop = asyncio.get_running_loop()
    if fmt == "zip" and password:
        raise RuntimeError("Password-protected ZIP requires the 7z CLI on this server.")
    if fmt == "zip":
        compression = zipfile.ZIP_STORED if level <= 0 else zipfile.ZIP_DEFLATED
        compresslevel = None if level <= 0 else max(1, min(9, level))
        def _zip():
            with zipfile.ZipFile(output, "w", compression=compression,
                                 compresslevel=compresslevel, allowZip64=True) as zf:
                for path in source_paths:
                    zf.write(path, arcname=path.name)
        await loop.run_in_executor(None, _zip)
        await status_cb(1.0, "ZIP packed")
        return
    if fmt in {"tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "xz"}:
        mode, kwargs = tar_mode(fmt, level)
        def _tar():
            with tarfile.open(output, mode, **kwargs) as tf:
                for path in source_paths:
                    tf.add(path, arcname=path.name)
        await loop.run_in_executor(None, _tar)
        await status_cb(1.0, "TAR packed")
        return
    raise RuntimeError(f"Unsupported internal archive format: {fmt}")

async def make_cli_archive(items: list[FileItem], fmt: str, level: int,
                            output: Path, temp: Path, status_cb, password: str | None = None) -> None:
    staging = temp / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    for item in items:
        src = Path(item.path)
        dst = staging / item.name
        if dst.exists():
            dst = staging / f"{item.id}_{item.name}"
        try:
            if src.stat().st_dev == staging.stat().st_dev:
                os.link(src, dst)
            else:
                shutil.copy2(src, dst)
        except Exception:
            shutil.copy2(src, dst)
    await status_cb(0.05, "Starting compressor")
    if fmt == "7z":
        if not command_exists("7z"):
            raise RuntimeError("7z is not installed on this server.")
        cmd = ["7z", "a", f"-mx={max(0, min(9, level))}"]
        if password:
            cmd.extend([f"-p{password}", "-mhe=on"])
        cmd.extend([str(output), "."])
        await run_cmd(cmd, cwd=staging)
        return
    if fmt == "zip" and password:
        if not command_exists("7z"):
            raise RuntimeError("Password-protected ZIP requires 7z to be installed on this server.")
        cmd = ["7z", "a", "-tzip", f"-mx={max(0, min(9, level))}", f"-p{password}", str(output), "."]
        await run_cmd(cmd, cwd=staging)
        return
    if fmt == "rar":
        if not command_exists("rar"):
            raise RuntimeError("rar is not installed on this server.")
        cmd = ["rar", "a", f"-m{max(0, min(5, level))}"]
        if password:
            cmd.append(f"-p{password}")
        cmd.extend([str(output), "."])
        await run_cmd(cmd, cwd=staging)
        return
    if fmt in {"tar.zstd", "tar.zst", "zst"}:
        if command_exists("tar") and command_exists("zstd"):
            env = {**os.environ, "ZSTD_CLEVEL": str(max(1, min(19, level)))}
            process = await asyncio.create_subprocess_exec(
                "tar", "--zstd", "-cf", str(output), ".",
                cwd=str(staging),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                err = stderr.decode(errors="ignore") or "command failed"
                raise RuntimeError(err.strip()[:1000])
            return
        if not command_exists("zstd"):
            raise RuntimeError("zstd is not installed on this server.")
        tar_path = temp / "archive.tar"
        loop = asyncio.get_running_loop()
        src_paths = [Path(i.path) for i in items if i.path]
        def _tar():
            with tarfile.open(tar_path, "w") as tf:
                for p in src_paths:
                    tf.add(p, arcname=p.name)
        await loop.run_in_executor(None, _tar)
        await run_cmd(["zstd", f"-{max(1, min(19, level))}", "-f",
                       str(tar_path), "-o", str(output)])
        _delete_path(tar_path)
        return
    raise RuntimeError(f"Unsupported CLI archive format: {fmt}")

async def make_archive(items: list[FileItem], fmt: str, level: int,
                        output: Path, temp: Path, status_cb, password: str | None = None) -> None:
    if fmt == "zip" and password:
        await make_cli_archive(items, fmt, level, output, temp, status_cb, password)
    elif fmt in {"zip", "tar", "tar.gz", "tar.bz2", "tar.xz", "gz", "xz"}:
        await make_python_archive(items, fmt, level, output, status_cb, password)
    else:
        await make_cli_archive(items, fmt, level, output, temp, status_cb, password)

def group_items(items: list[FileItem], max_bytes: int) -> list[list[FileItem]]:
    groups: list[list[FileItem]] = []
    current: list[FileItem] = []
    current_size = 0
    for item in sorted(items, key=lambda i: i.size, reverse=True):
        if current and current_size + item.size > max_bytes:
            groups.append(current)
            current = []
            current_size = 0
        current.append(item)
        current_size += item.size
    if current:
        groups.append(current)
    return groups

async def split_file(path: Path, max_bytes: int, status_cb) -> list[Path]:
    outputs: list[Path] = []
    total = path.stat().st_size
    index = 1
    read = 0
    async with aiofiles.open(path, "rb") as src:
        while True:
            chunk_path = path.with_name(f"{path.name}.part{index:03d}")
            remaining = max_bytes
            wrote = False
            async with aiofiles.open(chunk_path, "wb") as dst:
                while remaining > 0:
                    data = await src.read(min(8 * 1024 * 1024, remaining))
                    if not data:
                        break
                    wrote = True
                    await dst.write(data)
                    remaining -= len(data)
                    read += len(data)
                    await status_cb(read / max(1, total), f"Splitting part {index}")
            if not wrote:
                with contextlib.suppress(FileNotFoundError):
                    chunk_path.unlink()
                break
            outputs.append(chunk_path)
            index += 1
    return outputs

async def download_worker() -> None:
    while True:
        state, item = await download_queue.get()
        async with download_sem:
            await download_item(state, item)
        download_queue.task_done()

async def download_item(state: UserState, item: FileItem) -> None:
    if item.status == "done" and item.path and Path(item.path).exists():
        return
    item.status = "downloading"
    schedule_summary_refresh(state)

    user_dir = DOWNLOAD_DIR / str(state.user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    target = user_dir / f"{item.id}_{item.name}"

    try:
        path = await app.download_media(item.file_id, file_name=str(target))
        item.path = str(path)
        item.status = "done"
        item.progress = 1.0
    except Exception as exc:
        item.status = "error"
        item.error = str(exc)[:300]
        raise
    finally:
        schedule_summary_refresh(state)

async def download_pending_items(state: UserState, status_id: int) -> list[FileItem]:
    items = [item for item in state.items if item.status != "done" or not item.path or not Path(item.path).exists()]
    if not items:
        return state.items
    completed = 0
    failed = 0
    total_bytes = sum(item.size for item in items)
    started = time.monotonic()
    progress_bytes: dict[str, int] = {item.id: 0 for item in items}
    last_update = 0.0

    async def update_status(force: bool = False) -> None:
        nonlocal last_update
        now = time.monotonic()
        if not force and now - last_update < 1.5:
            return
        last_update = now
        done_bytes = sum(progress_bytes.values())
        speed, spent, eta = transfer_stats(done_bytes, max(1, total_bytes), started)
        await edit_ui(
            state.chat_id,
            status_id,
            f"⬇️ <b>Downloading queued files</b>\n\n"
            f"{progress_bar(done_bytes / max(1, total_bytes))} <b>{completed + failed}/{len(items)}</b>\n"
            f"◇ Downloaded: <b>{human_size(done_bytes)} / {human_size(total_bytes)}</b>\n"
            f"◇ Speed: <b>{speed}</b>\n"
            f"◇ Time spent: <b>{spent}</b>\n"
            f"◇ ETA: <b>{eta}</b>\n"
            f"✅ Done: <b>{completed}</b>   ⚠️ Failed: <b>{failed}</b>",
            force=force,
        )

    async def one(item: FileItem) -> None:
        nonlocal completed, failed
        item.status = "downloading"
        user_dir = DOWNLOAD_DIR / str(state.user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        target = user_dir / f"{item.id}_{item.name}"
        loop = asyncio.get_running_loop()

        def progress(current: int, total: int) -> None:
            item.progress = current / total if total else 0.0
            progress_bytes[item.id] = current
            loop.call_soon_threadsafe(asyncio.create_task, update_status(False))

        try:
            async with download_sem:
                path = await app.download_media(item.file_id, file_name=str(target), progress=progress)
            item.path = str(path)
            item.status = "done"
            item.progress = 1.0
            progress_bytes[item.id] = item.size or Path(path).stat().st_size
            completed += 1
        except Exception as exc:
            item.status = "error"
            item.error = str(exc)[:300]
            failed += 1
        await update_status(True)

    await asyncio.gather(*(one(item) for item in items))
    if failed:
        raise RuntimeError(f"{failed} file(s) failed to download.")
    await refresh_summary(state, force=True)
    return state.items

async def job_worker() -> None:
    while True:
        state = await job_queue.get()
        async with job_sem:
            await process_job(state)
        job_queue.task_done()

async def process_job(state: UserState) -> None:
    if state.busy:
        return
    state.busy = True
    if not state.items:
        await send_ui(state.chat_id, "⚠️ No files are queued yet.")
        state.busy = False
        return

    fmt = state.format or "tar.zst"
    level = state.level
    max_bytes = max(1, state.max_mb) * 1024 * 1024
    job_id = uuid.uuid4().hex[:12]
    user_work_root = WORK_DIR / str(state.user_id)
    user_output_root = OUTPUT_DIR / str(state.user_id)
    _delete_tree(user_work_root)
    _delete_tree(user_output_root)
    user_work_root.mkdir(parents=True, exist_ok=True)
    user_output_root.mkdir(parents=True, exist_ok=True)
    temp = user_work_root / job_id
    out_dir = user_output_root / job_id
    temp.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    status_id = await send_ui(state.chat_id, "🚀 <b>Job started</b>\n\nPreparing files…")
    last_status_edit = 0.0

    async def status_cb(value: float, label: str) -> None:
        nonlocal last_status_edit
        now = time.monotonic()
        if now - last_status_edit >= 3.0:
            last_status_edit = now
            await edit_ui(
                state.chat_id, status_id,
                f"🧊 <b>{label}</b>\n\n{progress_bar(value)} <b>{value * 100:.0f}%</b>",
                force=True,
            )

    try:
        items = await download_pending_items(state, status_id)
        items = [i for i in items if i.status == "done" and i.path and Path(i.path).exists()]
        if not items:
            raise RuntimeError("No downloaded files are ready.")
        await write_manifest(items, temp)
        outputs: list[Path] = []
        total_input = sum(i.size for i in items)

        if state.overflow == "groups" and total_input > max_bytes:
            groups = group_items(items, max_bytes)
            for idx, group in enumerate(groups, 1):
                output = out_dir / archive_name(fmt, idx, state.archive_base_name)
                await status_cb((idx - 1) / max(1, len(groups)),
                                f"Creating archive {idx}/{len(groups)}")
                await make_archive(group, fmt, level, output,
                                   temp / f"group_{idx}", status_cb, state.password)
                outputs.append(output)
        else:
            output = out_dir / archive_name(fmt, base_name=state.archive_base_name)
            await make_archive(items, fmt, level, output, temp, status_cb, state.password)
            if output.stat().st_size > max_bytes:
                await status_cb(0.0, "Splitting output")
                outputs = await split_file(output, max_bytes, status_cb)
                _delete_path(output)
            else:
                outputs.append(output)

        await edit_ui(state.chat_id, status_id,
                      f"📤 <b>Uploading to Telegram</b>\n\nPreparing <b>{len(outputs)}</b> file(s)…",
                      force=True)

        for idx, path in enumerate(outputs, 1):
            async with upload_sem:
                file_size = path.stat().st_size
                upload_started = time.monotonic()
                stop_heartbeat = asyncio.Event()

                async def heartbeat() -> None:
                    tick = 0
                    while not stop_heartbeat.is_set():
                        await edit_ui(
                            state.chat_id,
                            status_id,
                            upload_heartbeat_text(path.name, idx, len(outputs), file_size, upload_started, tick),
                            force=True,
                        )
                        tick += 1
                        try:
                            await asyncio.wait_for(stop_heartbeat.wait(), timeout=10)
                        except asyncio.TimeoutError:
                            pass

                heartbeat_task = asyncio.create_task(heartbeat())
                try:
                    caption = (
                        f"✅ <b>{path.name}</b>\n"
                        f"◇ Part {idx}/{len(outputs)}\n"
                        f"◇ Size: <b>{human_size(file_size)}</b>"
                    )
                    await app.send_document(state.chat_id, str(path), caption=caption)
                finally:
                    stop_heartbeat.set()
                    with contextlib.suppress(Exception):
                        await heartbeat_task
            await edit_ui(
                state.chat_id,
                status_id,
                f"📤 <b>Uploading to Telegram</b>\n\n"
                f"✅ Uploaded <b>{idx}</b> / <b>{len(outputs)}</b> file(s).\n"
                f"◇ Last file: <b>{path.name}</b>\n"
                f"◇ Time spent on last file: <b>{duration_text(time.monotonic() - upload_started)}</b>",
                force=True,
            )

        await edit_ui(state.chat_id, status_id,
                      "✅ <b>Done!</b>\n\nYour archive is ready.", force=True)

    except Exception as exc:
        await edit_ui(
            state.chat_id, status_id,
            f"⚠️ <b>Job failed</b>\n\n<code>{str(exc)[:3500]}</code>",
            force=True,
        )
    finally:
        _delete_tree(temp)
        _delete_tree(out_dir)
        for item in items:
            _delete_path(item.path)
            item.path = None
        state.items.clear()
        state.busy = False
        state.step = "idle"
        state.overflow = None
        await refresh_summary(state, force=True)

async def start_handler(_, message: Message) -> None:
    state = get_state(message.from_user.id, message.chat.id)
    if not state.welcome_message_id:
        state.welcome_message_id = await send_ui(message.chat.id, WELCOME_TEXT)
    state.status_message_id = None
    await refresh_summary(state, force=True)

async def queue_handler(_, message: Message) -> None:
    state = get_state(message.from_user.id, message.chat.id)
    state.status_message_id = None
    await refresh_summary(state, force=True)


async def clear_handler(_, message: Message) -> None:
    state = get_state(message.from_user.id, message.chat.id)
    await send_ui(message.chat.id, confirm_clear_text(),
                  confirm_keyboard("clear_yes", "back_list"))

def get_media(message: Message) -> tuple[str, str, int, str, str, str | None] | None:
    for attr, kind in [
        ("document",   "document"),
        ("video",      "video"),
        ("audio",      "audio"),
        ("animation",  "animation"),
        ("voice",      "voice"),
        ("video_note", "video_note"),
    ]:
        media = getattr(message, attr, None)
        if media:
            file_id = media.file_id
            unique_id = getattr(media, "file_unique_id", None)
            name = getattr(media, "file_name", None) or f"{kind}_{message.id}"
            size = int(getattr(media, "file_size", 0) or 0)
            mime = getattr(media, "mime_type", "") or ""
            return file_id, clean_name(name), size, mime, kind, unique_id
    return None

async def media_handler(_, message: Message) -> None:
    media = get_media(message)
    if not media:
        return
    state = get_state(message.from_user.id, message.chat.id)
    file_id, name, size, mime, kind, unique_id = media
    token = file_token(state.user_id, message.id, name)
    item = FileItem(
        id=token, file_id=file_id, name=name, size=size,
        mime=mime, kind=kind, message_id=message.id, unique_id=unique_id,
    )
    state.items.append(item)
    schedule_summary_refresh(state)

async def delete_handler(_, message: Message) -> None:
    state = get_state(message.from_user.id, message.chat.id)
    if not message.reply_to_message:
        await send_ui(message.chat.id, "Reply to a queued file and send /delete.")
        return
    target_id = message.reply_to_message.id
    item = next((i for i in state.items if i.message_id == target_id), None)
    if not item:
        await send_ui(message.chat.id, "I could not find that file in your queue.")
        return
    _delete_path(item.path)
    state.items.remove(item)
    await send_ui(message.chat.id, f"🗑 Removed <b>{item.name}</b> from the queue.")
    await refresh_summary(state, force=True)

async def text_handler(_, message: Message) -> None:
    state = get_state(message.from_user.id, message.chat.id)
    text = (message.text or "").strip()
    if text.startswith("/") and state.step not in {"level", "max", "password", "archive_name"}:
        return
    if state.step == "level":
        try:
            value = int(text)
        except ValueError:
            await send_ui(message.chat.id, "Send a valid integer for the compression level.")
            return
        lo, hi = FORMATS[state.format]["levels"]
        if not (lo <= value <= hi):
            await send_ui(message.chat.id, f"Allowed range is {lo}–{hi}.")
            return
        state.level = value
        state.step = "max"
        await send_ui(message.chat.id, max_text(state), max_keyboard())
        return
    if state.step == "max":
        try:
            value = int(text)
        except ValueError:
            await send_ui(message.chat.id, "Send a valid size in MB.")
            return
        if value < 1:
            await send_ui(message.chat.id, "The size must be at least 1 MB.")
            return
        state.max_mb = value
        state.step = "confirm"
        await send_ui(message.chat.id,
                      confirm_compress_text(state),
                      confirm_compress_keyboard())
    if state.step == "archive_name":
        cleaned_name = clean_archive_base_name(text)
        state.archive_base_name = cleaned_name
        state.step = "confirm"
        await send_ui(message.chat.id,
                      confirm_compress_text(state),
                      confirm_compress_keyboard())
        return


async def callback_handler(_, cq: CallbackQuery) -> None:
    user_id = cq.from_user.id
    chat_id = cq.message.chat.id
    state = get_state(user_id, chat_id)
    data = cq.data or ""
    await answer(cq)

    if data.startswith("remove:"):
        token = data.split(":", 1)[1]
        item = next((i for i in state.items if i.id == token), None)
        if item:
            _delete_path(item.path)
            state.items.remove(item)
            with contextlib.suppress(Exception):
                await edit_ui(chat_id, item.file_msg_id,
                              f"🗑 <i>{item.name}</i> removed.", force=True)
        await refresh_summary(state, force=True)
        return

    if data == "clear_ask":
        await edit_ui(chat_id, cq.message.id,
                      confirm_clear_text(),
                      confirm_keyboard("clear_yes", "back_list"), force=True)
        return

    if data == "clear_yes":
        for item in state.items:
            _delete_path(item.path)
        state.items.clear()
        state.step = "idle"
        await edit_ui(chat_id, cq.message.id, "🧹 <b>Queue cleared.</b>", force=True)
        await refresh_summary(state, force=True)
        return

    if data == "compress_all":
        if not state.items:
            await answer(cq, "No files are queued yet.", True)
            return
        state.step = "format"
        await edit_ui(chat_id, cq.message.id,
                      format_text(state), format_keyboard(state), force=True)
        return

    if data.startswith("fmt:"):
        fmt = data.split(":", 1)[1]
        if fmt not in FORMATS:
            await answer(cq, "Unknown format.", True)
            return
        state.format = fmt
        state.level = FORMATS[fmt]["default"]
        state.step = "level"
        await edit_ui(chat_id, cq.message.id,
                      level_text(fmt), level_keyboard(fmt), force=True)
        return

    if data.startswith("level:"):
        state.level = int(data.split(":", 1)[1])
        state.step = "max"
        await edit_ui(chat_id, cq.message.id,
                      max_text(state), max_keyboard(), force=True)
        return

    if data.startswith("max:"):
        state.max_mb = int(data.split(":", 1)[1])
        state.step = "password"
        await edit_ui(chat_id, cq.message.id,
                      password_text(state),
                      password_keyboard(state), force=True)
        return

    if data.startswith("overflow:"):
        state.overflow = data.split(":", 1)[1]
        state.step = "confirm"
        await edit_ui(chat_id, cq.message.id,
                      confirm_compress_text(state),
                      confirm_compress_keyboard(), force=True)
        return

    if data == "dup_keep":
        state.temp["duplicates_checked"] = True
        await edit_ui(chat_id, cq.message.id,
                      confirm_compress_text(state),
                      confirm_compress_keyboard(), force=True)
        return

    if data == "dup_delete":
        removed = remove_duplicate_items(state)
        state.temp["duplicates_checked"] = True
        await refresh_summary(state, force=True)
        await edit_ui(chat_id, cq.message.id,
                      f"🧬 <b>Removed {removed} duplicate file(s).</b>\n\n" + confirm_compress_text(state),
                      confirm_compress_keyboard(), force=True)
        return

    if data == "pass_skip":
        state.password = None
        state.step = "archive_name"
        await edit_ui(chat_id, cq.message.id,
                      archive_name_text(state),
                      archive_name_keyboard(), force=True)
        return

    if data == "name_default":
        state.archive_base_name = clean_archive_base_name(state.archive_base_name or "archive")
        state.step = "confirm"
        await edit_ui(chat_id, cq.message.id,
                      confirm_compress_text(state),
                      confirm_compress_keyboard(), force=True)
        return

    if data == "job_start":
        if duplicate_count(state.items) and not state.temp.get("duplicates_checked"):
            await edit_ui(chat_id, cq.message.id,
                          duplicate_text(state),
                          duplicate_keyboard(), force=True)
            return
        items = state.items
        total = sum(i.size for i in items)
        max_bytes = max(1, state.max_mb) * 1024 * 1024
        if total > max_bytes and not state.overflow:
            state.step = "overflow"
            await edit_ui(chat_id, cq.message.id,
                          overflow_text(state), overflow_keyboard(), force=True)
            return
        await edit_ui(chat_id, cq.message.id, "✅ <b>Job queued.</b>", force=True)
        await job_queue.put(state)
        return

    if data == "back_list":
        state.step = "idle"
        await edit_ui(chat_id, cq.message.id,
                      summary_text(state), summary_keyboard(state), force=True)
        return

    if data == "back_format":
        state.step = "format"
        await edit_ui(chat_id, cq.message.id,
                      format_text(state), format_keyboard(state), force=True)
        return

    if data == "back_level":
        state.step = "level"
        await edit_ui(chat_id, cq.message.id,
                      level_text(state.format), level_keyboard(state.format), force=True)
        return

    if data == "back_max":
        state.step = "max"
        await edit_ui(chat_id, cq.message.id,
                      max_text(state), max_keyboard(), force=True)
        return

    if data == "back_password":
        state.step = "password"
        await edit_ui(chat_id, cq.message.id,
                      password_text(state), password_keyboard(state), force=True)
        return

    if data == "cancel_ask":
        await edit_ui(chat_id, cq.message.id,
                      confirm_cancel_text(),
                      confirm_keyboard("cancel_yes", "back_list"), force=True)
        return

    if data == "cancel_yes":
        state.step = "idle"
        state.format = None
        state.overflow = None
        state.password = None
        state.archive_base_name = "archive"
        await edit_ui(chat_id, cq.message.id, "🚫 <b>Cancelled.</b>", force=True)
        await refresh_summary(state, force=True)
        return

async def main() -> None:
    global app
    from pyrogram.handlers import MessageHandler, CallbackQueryHandler

    app = Client("archive_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

    app.add_handler(MessageHandler(
        start_handler, filters.command("start") & filters.private))
    app.add_handler(MessageHandler(
        queue_handler, filters.command("queue") & filters.private))
    app.add_handler(MessageHandler(
        clear_handler, filters.command("clear") & filters.private))
    app.add_handler(MessageHandler(
        media_handler,
        filters.private & (
            filters.document | filters.video | filters.audio |
            filters.animation | filters.voice | filters.video_note
        ),
    ))
    app.add_handler(MessageHandler(
        delete_handler, filters.command("delete") & filters.private))
    app.add_handler(MessageHandler(
        text_handler, filters.private & filters.text))
    app.add_handler(CallbackQueryHandler(callback_handler))

    cleanup_runtime_files()

    await app.start()

    for _ in range(MAX_PARALLEL_DOWNLOADS):
        asyncio.create_task(download_worker())
    for _ in range(MAX_PARALLEL_JOBS):
        asyncio.create_task(job_worker())

    print("Archive bot is running. Press Ctrl+C to stop.")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _handle_signal():
        print("\nShutting down…")
        stop_event.set()

    loop.add_signal_handler(signal.SIGINT, _handle_signal)
    loop.add_signal_handler(signal.SIGTERM, _handle_signal)

    await stop_event.wait()
    cleanup_runtime_files()
    await app.stop()
    print("Stopped.")

if __name__ == "__main__":
    asyncio.run(main())

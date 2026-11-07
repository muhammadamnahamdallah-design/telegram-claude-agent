"""Jembatan Telegram untuk agent Claude Code.

Hanya pemilik (ALLOWED_USER_ID) yang bisa memakai bot ini. Setiap pesan
dijalankan oleh Claude Agent SDK dengan akses penuh ke tools DI DALAM container
(container Docker-lah yang jadi sandbox). File kerja disimpan di /app/workspace.
"""
import asyncio
import json
import logging
import os
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
)

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("tg-claude")

# ---- Konfigurasi dari environment -------------------------------------------
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
WORKSPACE_ROOT = Path(os.environ.get("WORKSPACE_ROOT", "/app/workspace"))
MAX_TG = 4000  # batas aman panjang pesan Telegram (limit asli 4096)

WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
SESSIONS_FILE = WORKSPACE_ROOT / ".sessions.json"

# Ditulis ke setiap folder kerja; otomatis dibaca Claude sebagai memori/instruksi.
CLAUDE_MD = """# Instruksi Agent

Kamu adalah asisten tim pribadi yang dioperasikan lewat Telegram.
- Jawab dalam Bahasa Indonesia (atau bahasa yang dipakai user), ringkas dan jelas.
- Kamu boleh menjalankan perintah shell, menulis & mengolah file, serta riset web.
- Tools siap pakai: `ffmpeg` (olah/edit video & audio), `git`, Python.
- Simpan semua file hasil kerja di folder kerja saat ini (cwd). File yang
  diunggah user ada di sub-folder `uploads/`.
- User mengambil file hasil lewat perintah /get <nama_file> di Telegram, jadi
  beri tahu nama file yang kamu hasilkan.
- Jika butuh tool yang belum ada, install sendiri bila memungkinkan, atau beri tahu user.
"""


def load_sessions() -> dict:
    try:
        return json.loads(SESSIONS_FILE.read_text())
    except Exception:
        return {}


def save_sessions(data: dict) -> None:
    try:
        SESSIONS_FILE.write_text(json.dumps(data))
    except Exception as e:
        log.warning("Gagal menyimpan sesi: %s", e)


SESSIONS: dict = load_sessions()
LOCKS: dict[int, asyncio.Lock] = {}


def chat_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in LOCKS:
        LOCKS[chat_id] = asyncio.Lock()
    return LOCKS[chat_id]


def workspace_for(chat_id: int) -> Path:
    d = WORKSPACE_ROOT / str(chat_id)
    d.mkdir(parents=True, exist_ok=True)
    (d / "uploads").mkdir(exist_ok=True)
    cfg = d / "CLAUDE.md"
    if not cfg.exists():
        cfg.write_text(CLAUDE_MD)
    return d


def authorized(update: Update) -> bool:
    user = update.effective_user
    return user is not None and user.id == ALLOWED_USER_ID


async def deny(update: Update) -> None:
    uid = update.effective_user.id if update.effective_user else "?"
    log.warning("Akses ditolak untuk user %s", uid)
    if update.message:
        await update.message.reply_text("⛔ Maaf, bot ini privat.")


# ---- Menjalankan Claude -----------------------------------------------------
async def run_claude(chat_id: int, prompt: str) -> str:
    ws = workspace_for(chat_id)
    kwargs = dict(cwd=str(ws), permission_mode="bypassPermissions")
    sid = SESSIONS.get(str(chat_id))
    if sid:
        kwargs["resume"] = sid
    options = ClaudeAgentOptions(**kwargs)

    texts: list[str] = []
    result: str | None = None
    async for msg in query(prompt=prompt, options=options):
        new_sid = getattr(msg, "session_id", None)
        if new_sid:
            SESSIONS[str(chat_id)] = new_sid
        if isinstance(msg, AssistantMessage):
            for block in msg.content:
                if isinstance(block, TextBlock):
                    texts.append(block.text)
        if hasattr(msg, "result") and getattr(msg, "result"):
            result = msg.result

    save_sessions(SESSIONS)
    out = (result or "\n".join(t for t in texts if t)).strip()
    return out or "(selesai, tanpa teks balasan)"


async def keep_typing(bot, chat_id: int, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


async def send_long(update: Update, text: str) -> None:
    for i in range(0, len(text), MAX_TG):
        await update.message.reply_text(text[i:i + MAX_TG])


# ---- Handlers ---------------------------------------------------------------
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    prompt = update.message.text
    lock = chat_lock(chat_id)
    if lock.locked():
        await update.message.reply_text("⏳ Masih mengerjakan permintaan sebelumnya...")
    async with lock:
        stop = asyncio.Event()
        typing = asyncio.create_task(keep_typing(context.bot, chat_id, stop))
        try:
            answer = await run_claude(chat_id, prompt)
        except Exception as e:
            log.exception("Error saat menjalankan Claude")
            answer = f"⚠️ Terjadi error: {e}"
        finally:
            stop.set()
            await typing
        await send_long(update, answer)


async def on_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    chat_id = update.effective_chat.id
    ws = workspace_for(chat_id)
    msg = update.message
    try:
        if msg.document:
            f = await context.bot.get_file(msg.document.file_id)
            name = msg.document.file_name or msg.document.file_id
        elif msg.video:
            f = await context.bot.get_file(msg.video.file_id)
            name = msg.video.file_name or f"{msg.video.file_id}.mp4"
        elif msg.photo:
            f = await context.bot.get_file(msg.photo[-1].file_id)
            name = f"{msg.photo[-1].file_id}.jpg"
        elif msg.audio:
            f = await context.bot.get_file(msg.audio.file_id)
            name = msg.audio.file_name or f"{msg.audio.file_id}.mp3"
        else:
            return
        dest = ws / "uploads" / Path(name).name
        await f.download_to_drive(str(dest))
        rel = dest.relative_to(ws)
        await msg.reply_text(
            f"✅ File disimpan di: {rel}\nSekarang beri tahu saya mau diapakan file ini."
        )
    except Exception as e:
        await msg.reply_text(
            f"⚠️ Gagal menyimpan file: {e}\n"
            "(Via bot, Telegram hanya bisa mengunduh file < 20 MB. "
            "Untuk file besar, salin ke VPS pakai: docker cp <file> telegram-claude-agent:/app/workspace/)"
        )


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    await update.message.reply_text(
        "👋 Halo! Saya asisten Claude Code Anda.\n\n"
        "Kirim perintah apa pun: riset, tulis/jalankan kode, olah file, "
        "edit video via ffmpeg, dll. Anda juga bisa mengirim file untuk saya olah.\n\n"
        "Perintah:\n"
        "/new — mulai percakapan baru (lupakan konteks)\n"
        "/files — lihat file di folder kerja\n"
        "/get <nama_file> — ambil file hasil kerja\n"
        "/help — bantuan"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    return await cmd_start(update, context)


async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    chat_id = str(update.effective_chat.id)
    SESSIONS.pop(chat_id, None)
    save_sessions(SESSIONS)
    await update.message.reply_text("🆕 Percakapan baru dimulai. Konteks sebelumnya dilupakan.")


async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    ws = workspace_for(update.effective_chat.id)
    lines: list[str] = []
    for p in sorted(ws.rglob("*")):
        if p.is_file() and p.name != "CLAUDE.md":
            lines.append(f"{p.relative_to(ws)}  ({p.stat().st_size} B)")
        if len(lines) >= 50:
            lines.append("...")
            break
    await update.message.reply_text("📂 File:\n" + ("\n".join(lines) if lines else "(kosong)"))


async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return await deny(update)
    ws = workspace_for(update.effective_chat.id).resolve()
    if not context.args:
        await update.message.reply_text("Pakai: /get <nama_file>")
        return
    rel = " ".join(context.args)
    target = (ws / rel).resolve()
    if target != ws and ws not in target.parents:
        await update.message.reply_text("⛔ Path tidak valid.")
        return
    if not target.is_file():
        await update.message.reply_text("File tidak ditemukan.")
        return
    try:
        with open(target, "rb") as fh:
            await context.bot.send_document(update.effective_chat.id, document=fh)
    except Exception as e:
        await update.message.reply_text(f"⚠️ Gagal mengirim (bot maks 50 MB): {e}")


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("files", cmd_files))
    app.add_handler(CommandHandler("get", cmd_get))
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.VIDEO | filters.PHOTO | filters.AUDIO, on_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    log.info("Bot started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

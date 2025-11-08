import os
import logging
import traceback
import base64
import io
from io import BytesIO
from PIL import Image
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, ContextTypes
)
import google.generativeai as genai
import chess
from telegram.error import BadRequest

# ========================================
# SETUP
# ========================================

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
    raise ValueError("❌ Pastikan TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY ada di file .env")

genai.configure(api_key=GEMINI_API_KEY)

MODEL_TEXT = "gemini-2.5-flash"
MODEL_IMAGE = "gemini-2.5-flash-exp"

conversation_history = {}
chess_games = {}

# ========================================
# COMMAND HANDLERS
# ========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = f"""
👋 Halo {user.first_name}!

Saya adalah *AI Assistant* berbasis Gemini 2.5 Flash 🚀

🤖 Saya bisa membantu:
• Menjawab pertanyaan  
• Menulis teks & kode  
• Generate gambar pakai `/image`  
• Ubah foto jadi stiker otomatis 😎  
• Main catur pakai `/chess_start`  
• Kick/Ban anggota grup (admin only)

📌 Perintah:
/start - Mulai bot  
/help - Bantuan  
/clear - Hapus riwayat  
/image <prompt> - Buat gambar  
/chess_start - Main catur  
/kick - Kick anggota (reply/@username)  
/ban - Ban anggota (reply/@username)
"""
    await update.message.reply_text(msg, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🆘 *Bantuan Bot AI*

💡 Cara penggunaan:
1️⃣ Kirim pesan biasa untuk chat AI  
2️⃣ /clear → reset chat  
3️⃣ /image <prompt> → buat gambar  
4️⃣ Kirim foto → otomatis jadi *stiker*!  
5️⃣ /chess_start → mulai catur  
6️⃣ /kick atau /ban → kelola grup (admin)

⚙️ Commands:
/start, /help, /clear, /image, /chess_start, /move, /kick, /ban
""", parse_mode="Markdown")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    conversation_history.pop(uid, None)
    await update.message.reply_text("✅ Riwayat percakapan dihapus!")


# ========================================
# ADMIN TOOLS: KICK & BAN
# ========================================

async def _is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    member = await context.bot.get_chat_member(chat_id, user_id)
    return member.status in ("administrator", "creator")


async def _get_target_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ambil target user dari reply atau argumen username"""
    if update.message.reply_to_message:
        return update.message.reply_to_message.from_user

    if context.args:
        username = context.args[0].lstrip("@")
        try:
            members = await context.bot.get_chat_administrators(update.effective_chat.id)
            for m in members:
                if m.user.username and m.user.username.lower() == username.lower():
                    return m.user
            # kalau bukan admin
            users = await context.bot.get_chat(update.effective_chat.id)
        except Exception:
            pass
    return None


async def _check_bot_permissions(chat_id, context):
    me = await context.bot.get_me()
    bot_member = await context.bot.get_chat_member(chat_id, me.id)
    if bot_member.status != "administrator":
        return False, "Bot bukan admin grup."
    if not getattr(bot_member, "can_restrict_members", False):
        return False, "Bot tidak punya izin untuk mengeluarkan anggota."
    return True, None


async def kick_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not await _is_admin(update, context):
        await update.message.reply_text("❌ Kamu bukan admin, tidak bisa pakai perintah ini.")
        return

    ok, err = await _check_bot_permissions(chat_id, context)
    if not ok:
        await update.message.reply_text(f"⚠️ {err}")
        return

    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_text("Gunakan `/kick` sambil *reply* ke user atau ketik `/kick @username`", parse_mode="Markdown")
        return

    if target.id == update.effective_user.id:
        await update.message.reply_text("❌ Tidak bisa kick diri sendiri.")
        return

    if target.is_bot:
        await update.message.reply_text("🤖 Tidak bisa kick bot.")
        return

    try:
        await context.bot.ban_chat_member(chat_id, target.id)
        await context.bot.unban_chat_member(chat_id, target.id)
        admin_name = update.effective_user.first_name
        await update.message.reply_text(f"👢 {target.mention_html()} dikeluarkan oleh <b>{admin_name}</b>", parse_mode="HTML")
    except BadRequest:
        await update.message.reply_text("⚠️ Tidak bisa kick user itu (mungkin admin).")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal kick: {e}")


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    if not await _is_admin(update, context):
        await update.message.reply_text("❌ Kamu bukan admin, tidak bisa pakai perintah ini.")
        return

    ok, err = await _check_bot_permissions(chat_id, context)
    if not ok:
        await update.message.reply_text(f"⚠️ {err}")
        return

    target = await _get_target_user(update, context)
    if not target:
        await update.message.reply_text("Gunakan `/ban` sambil *reply* ke user atau ketik `/ban @username`", parse_mode="Markdown")
        return

    try:
        await context.bot.ban_chat_member(chat_id, target.id)
        admin_name = update.effective_user.first_name
        await update.message.reply_text(f"🚫 {target.mention_html()} dibanned oleh <b>{admin_name}</b>", parse_mode="HTML")
    except BadRequest:
        await update.message.reply_text("⚠️ Tidak bisa ban user itu (mungkin admin).")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal ban: {e}")


# ========================================
# IMAGE HANDLER
# ========================================

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("📸 Gunakan format: `/image <deskripsi>`", parse_mode="Markdown")
        return

    await update.message.reply_text("🎨 Sedang membuat gambar...")

    try:
        model = genai.GenerativeModel(MODEL_IMAGE)
        response = model.generate_content([f"Buatkan gambar dengan deskripsi: {prompt}"])

        if hasattr(response, "images") and response.images:
            image_data = response.images[0]
            img_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(img_bytes))

            bio = io.BytesIO()
            image.save(bio, format="PNG")
            bio.seek(0)

            await update.message.reply_photo(photo=InputFile(bio, filename="generated.png"), caption=f"🖼️ {prompt}")
        else:
            await update.message.reply_text("⚠️ Model tidak mendukung generate gambar.")
    except Exception as e:
        await update.message.reply_text(f"❌ Terjadi error: {str(e)}")
        logger.error(traceback.format_exc())


# ========================================
# PHOTO → STICKER
# ========================================

async def photo_to_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        msg = await update.message.reply_text("🧩 Sedang ubah gambar jadi stiker...")

        photo_file = await update.message.photo[-1].get_file()
        img_bytes = BytesIO()
        await photo_file.download_to_memory(out=img_bytes)
        img_bytes.seek(0)

        image = Image.open(img_bytes).convert("RGBA")
        image.thumbnail((512, 512))

        bio = BytesIO()
        image.save(bio, format="WEBP")
        bio.seek(0)

        await update.message.reply_sticker(sticker=InputFile(bio, filename="sticker.webp"))
        await msg.edit_text("✅ Gambar berhasil diubah jadi stiker!")
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"⚠️ Gagal ubah gambar ke stiker: {e}")


# ========================================
# CHESS HANDLER
# ========================================

async def chess_start_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in chess_games:
        await update.message.reply_text("⚠️ Game catur sudah aktif.")
        return
    chess_games[chat_id] = chess.Board()
    board = chess_games[chat_id]
    await update.message.reply_text(f"♟️ *Game dimulai!*\n```\n{board}\n```", parse_mode="Markdown")

async def chess_move_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in chess_games:
        await update.message.reply_text("Mulai dulu pakai /chess_start.")
        return
    move_str = " ".join(context.args)
    board = chess_games[chat_id]
    try:
        board.push_san(move_str)
    except Exception:
        await update.message.reply_text(f"❌ Langkah tidak valid: {move_str}")
        return
    if board.is_game_over():
        await update.message.reply_text(f"🏁 Game selesai!\n```\n{board}\n```", parse_mode="Markdown")
        del chess_games[chat_id]
    else:
        await update.message.reply_text(f"Langkah `{move_str}` berhasil!\n```\n{board}\n```", parse_mode="Markdown")


# ========================================
# TEXT HANDLER
# ========================================

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    chat_type = update.message.chat.type

    if chat_type in ["group", "supergroup"]:
        bot_username = context.bot.username
        if f"@{bot_username}" not in text and not (
            update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        ):
            return
        text = text.replace(f"@{bot_username}", "").strip()

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": text})
    context_text = "\n".join(f"{m['role']}: {m['content']}" for m in conversation_history[user_id][-10:])

    try:
        model = genai.GenerativeModel(MODEL_TEXT)
        response = model.generate_content(contents=[{"role": "user", "parts": [context_text]}])
        reply = response.text or "⚠️ Tidak ada respon dari AI."
        conversation_history[user_id].append({"role": "assistant", "content": reply})

        for i in range(0, len(reply), 4000):
            await update.message.reply_text(reply[i:i+4000])
    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"⚠️ Error internal: {e}")


# ========================================
# MAIN
# ========================================

def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("chess_start", chess_start_command))
    app.add_handler(CommandHandler("move", chess_move_command))
    app.add_handler(CommandHandler("kick", kick_command))
    app.add_handler(CommandHandler("ban", ban_command))

    app.add_handler(MessageHandler(filters.PHOTO, photo_to_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot aktif (Gemini 2.5 Flash + Stiker + Catur + Admin Tools)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

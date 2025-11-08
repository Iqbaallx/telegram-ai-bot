import os
import logging
import traceback
import base64
import io
from io import BytesIO
from PIL import Image
from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import google.generativeai as genai
import chess  # <-- Untuk fitur catur

# ========================================
# LOAD ENV & LOGGING SETUP
# ========================================

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========================================
# CONFIGURATION
# ========================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_BOT_TOKEN:
    logger.error("❌ TELEGRAM_BOT_TOKEN tidak ditemukan di .env")
if not GEMINI_API_KEY:
    logger.error("❌ GEMINI_API_KEY tidak ditemukan di .env")

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
    message = f"""
👋 Halo {user.first_name}!

Saya adalah *AI Assistant* berbasis Gemini 2.5 Flash 🚀

🤖 Saya bisa membantu:
• Menjawab pertanyaan
• Membuat kode / script
• Menulis teks & ide
• Generate gambar pakai `/image`
• Ubah gambar jadi stiker otomatis 😎

📌 Perintah:
/start - Mulai bot
/help - Bantuan
/clear - Hapus riwayat chat
/mode - Ganti mode AI
/image <prompt> - Buat gambar
/chess_start - Main catur
"""
    await update.message.reply_text(message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🆘 *Bantuan Bot AI*

💡 Cara penggunaan:
1️⃣ Kirim pesan biasa untuk chat AI  
2️⃣ Gunakan /clear untuk reset chat  
3️⃣ Tag bot di grup untuk bicara  
4️⃣ Gunakan `/image <prompt>` untuk buat gambar  
5️⃣ Kirim foto — otomatis jadi *stiker*!  
6️⃣ Gunakan `/chess_start` untuk main catur

⚙️ Commands:
/start - Mulai bot
/help - Bantuan
/clear - Hapus chat
/mode - Ganti mode
/image - Buat gambar
/chess_start - Mulai catur
/chess_stop - Stop catur
/move <langkah> - Langkah catur
"""
    await update.message.reply_text(text, parse_mode="Markdown")


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in conversation_history:
        del conversation_history[user_id]
        await update.message.reply_text("✅ Riwayat percakapan dihapus!")
    else:
        await update.message.reply_text("ℹ️ Belum ada riwayat percakapan.")


async def mode_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
⚙️ *Mode AI yang tersedia:*
1️⃣ Creative - Imajinatif  
2️⃣ Balanced - Default  
3️⃣ Precise - Akurat & faktual  

Gunakan: `/mode creative` | `/mode balanced` | `/mode precise`
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================================
# IMAGE GENERATION HANDLER
# ========================================

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("📸 Gunakan format: `/image <deskripsi gambar>`", parse_mode="Markdown")
        return

    await update.message.reply_text("🎨 Sedang membuat gambar, tunggu sebentar...")

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
            await text_fallback_image(update, prompt)

    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"🔥 Error generate gambar:\n{err}")
        await update.message.reply_text(f"⚠️ Terjadi error saat membuat gambar:\n{str(e)}")

async def text_fallback_image(update, prompt):
    try:
        text_model = genai.GenerativeModel(MODEL_TEXT)
        response = text_model.generate_content([f"Buatkan deskripsi visual untuk: {prompt}"])
        await update.message.reply_text(f"📝 Deskripsi (fallback):\n{response.text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal fallback: {str(e)}")

# ========================================
# PHOTO → STICKER HANDLER (FITUR BARU)
# ========================================

async def photo_to_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ubah gambar yang dikirim user jadi stiker"""
    try:
        photo_file = await update.message.photo[-1].get_file()
        img_bytes = BytesIO()
        await photo_file.download_to_memory(out=img_bytes)
        img_bytes.seek(0)

        image = Image.open(img_bytes).convert("RGBA")

        bio = BytesIO()
        image.save(bio, format="WEBP")
        bio.seek(0)

        await update.message.reply_sticker(sticker=InputFile(bio, filename="sticker.webp"))
        await update.message.reply_text("✅ Gambar kamu sudah jadi stiker!")
    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"🔥 Error konversi foto ke stiker:\n{err}")
        await update.message.reply_text(f"⚠️ Gagal ubah gambar ke stiker: {str(e)}")

# ========================================
# CHESS HANDLERS (dipersingkat)
# ========================================

import chess

chess_games = {}

async def chess_start_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in chess_games:
        await update.message.reply_text("⚠️ Game catur sudah aktif.")
        return
    chess_games[chat_id] = chess.Board()
    board = chess_games[chat_id]
    await update.message.reply_text(f"♟️ *Game dimulai!*\n```\n{board}\n```", parse_mode="Markdown")

async def chess_stop_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id in chess_games:
        del chess_games[chat_id]
        await update.message.reply_text("✅ Game dihentikan.")
    else:
        await update.message.reply_text("ℹ️ Tidak ada game aktif.")

async def chess_move_command(update, context):
    chat_id = update.effective_chat.id
    if chat_id not in chess_games:
        await update.message.reply_text("Mulai dulu pakai /chess_start.")
        return

    board = chess_games[chat_id]
    move_str = " ".join(context.args)
    try:
        board.push_san(move_str)
    except Exception as e:
        await update.message.reply_text(f"❌ Langkah tidak valid: {move_str}")
        return

    if board.is_game_over():
        await update.message.reply_text(f"Game selesai!\n```\n{board}\n```", parse_mode="Markdown")
        del chess_games[chat_id]
    else:
        await update.message.reply_text(f"Langkah: `{move_str}`\n```\n{board}\n```", parse_mode="Markdown")

# ========================================
# MESSAGE HANDLER
# ========================================

async def handle_message(update, context):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    message_text = update.message.text
    chat_type = update.message.chat.type

    if chat_type in ["group", "supergroup"]:
        bot_username = context.bot.username
        if f"@{bot_username}" not in message_text and not (
            update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id
        ):
            return
        message_text = message_text.replace(f"@{bot_username}", "").strip()

    if not message_text:
        await update.message.reply_text("❓ Silakan kirim pertanyaan atau pesan.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    try:
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        conversation_history[user_id].append({"role": "user", "content": message_text})
        conversation_history[user_id] = conversation_history[user_id][-10:]

        context_text = "\n".join(f"{m['role']}: {m['content']}" for m in conversation_history[user_id])
        model = genai.GenerativeModel(MODEL_TEXT)
        response = model.generate_content(contents=[{"role": "user", "parts": [context_text]}])
        ai_response = response.text or "⚠️ Tidak ada respon dari AI."

        conversation_history[user_id].append({"role": "assistant", "content": ai_response})

        for i in range(0, len(ai_response), 4000):
            await update.message.reply_text(ai_response[i:i + 4000])

        logger.info(f"User {user_name} ({user_id}): {message_text}")
    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"🔥 Error:\n{err}")
        await update.message.reply_text(f"⚠️ Terjadi error internal:\n{str(e)}")

# ========================================
# MAIN FUNCTION
# ========================================

def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        logger.error("❌ Pastikan TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY ada di .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("mode", mode_command))
    app.add_handler(CommandHandler("image", image_command))

    app.add_handler(CommandHandler("chess_start", chess_start_command))
    app.add_handler(CommandHandler("chess_stop", chess_stop_command))
    app.add_handler(CommandHandler("move", chess_move_command))

    # 🆕 Tambahan: ubah gambar jadi stiker
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_sticker))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error {context.error}"))

    logger.info("🤖 Bot aktif (Gemini 2.5 Flash + Gambar + Stiker + Catur)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

# ========================================
# RUN
# ========================================

if __name__ == "__main__":
    main()

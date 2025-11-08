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
import chess

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
    message = f"""
👋 Halo {user.first_name}!

Saya adalah *AI Assistant* berbasis Gemini 2.5 Flash 🚀

🤖 Saya bisa membantu:
• Menjawab pertanyaan
• Menulis teks & kode
• Generate gambar pakai `/image`
• Ubah gambar jadi stiker otomatis 😎
• Main catur pakai `/chess_start`

📌 Perintah:
/start - Mulai bot
/help - Bantuan
/clear - Hapus riwayat
/image <prompt> - Buat gambar
/chess_start - Main catur
"""
    await update.message.reply_text(message, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("""
🆘 *Bantuan Bot AI*

💡 Cara penggunaan:
1️⃣ Kirim pesan biasa untuk chat AI  
2️⃣ Gunakan /clear untuk reset chat  
3️⃣ Gunakan `/image <prompt>` untuk buat gambar  
4️⃣ Kirim foto — otomatis jadi *stiker*!  
5️⃣ Gunakan `/chess_start` untuk main catur  

⚙️ Commands:
/start - Mulai bot
/help - Bantuan
/clear - Hapus chat
/image - Buat gambar
/chess_start - Mulai catur
""", parse_mode="Markdown")

async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    conversation_history.pop(user_id, None)
    await update.message.reply_text("✅ Riwayat percakapan dihapus!")

# ========================================
# IMAGE GENERATION HANDLER
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
# PHOTO TO STICKER HANDLER (AUTO)
# ========================================

async def photo_to_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ubah gambar yang dikirim jadi stiker otomatis"""
    try:
        msg = await update.message.reply_text("🧩 Sedang ubah gambar jadi stiker...")

        photo_file = await update.message.photo[-1].get_file()
        img_bytes = BytesIO()
        await photo_file.download_to_memory(out=img_bytes)
        img_bytes.seek(0)

        image = Image.open(img_bytes).convert("RGBA")
        image.thumbnail((512, 512))  # ukuran wajib stiker

        bio = BytesIO()
        image.save(bio, format="WEBP")
        bio.seek(0)

        await update.message.reply_sticker(sticker=InputFile(bio, filename="sticker.webp"))
        await msg.edit_text("✅ Gambar berhasil diubah jadi stiker!")

    except Exception as e:
        logger.error(traceback.format_exc())
        await update.message.reply_text(f"⚠️ Gagal ubah gambar ke stiker: {e}")

# ========================================
# CHESS HANDLERS
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
# TEXT HANDLER (GEMINI)
# ========================================

async def handle_message(update, context):
    user_id = update.effective_user.id
    text = update.message.text
    chat_type = update.message.chat.type

    # Balasan hanya kalau disebut di grup
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
    app.add_handler(MessageHandler(filters.PHOTO, photo_to_sticker))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 Bot aktif (Gemini 2.5 Flash + Gambar + Stiker + Catur)")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

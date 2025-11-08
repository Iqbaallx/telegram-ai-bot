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

📌 Perintah:
/start - Mulai bot
/help - Bantuan
/clear - Hapus riwayat chat
/mode - Ganti mode AI
/image <prompt> - Buat gambar dari deskripsi
"""
    await update.message.reply_text(message, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
🆘 *Bantuan Bot AI*

💡 Cara penggunaan:
1️⃣ Kirim pesan biasa untuk chat dengan AI  
2️⃣ Gunakan /clear untuk reset percakapan  
3️⃣ Tag bot di grup: `@bot_username pesan`
4️⃣ Gunakan `/image <prompt>` untuk buat gambar

⚙️ Commands:
/start - Mulai bot
/help - Bantuan
/clear - Hapus chat
/mode - Ganti mode
/image - Buat gambar
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
1️⃣ Creative - Lebih imajinatif  
2️⃣ Balanced - Seimbang (default)  
3️⃣ Precise - Lebih faktual dan akurat  

Gunakan: `/mode creative` | `/mode balanced` | `/mode precise`
"""
    await update.message.reply_text(text, parse_mode="Markdown")

# ========================================
# IMAGE GENERATION HANDLER
# ========================================

async def image_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate gambar dari prompt teks menggunakan Gemini 2.5"""
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("📸 Gunakan format: `/image <deskripsi gambar>`", parse_mode="Markdown")
        return

    await update.message.reply_text("🎨 Sedang membuat gambar, tunggu sebentar...")

    try:
        model = genai.GenerativeModel(MODEL_IMAGE)
        response = model.generate_content([f"Buatkan gambar dengan deskripsi: {prompt}"])

        # Periksa apakah model mendukung image output
        if hasattr(response, "images") and response.images:
            image_data = response.images[0]
            img_bytes = base64.b64decode(image_data)
            image = Image.open(io.BytesIO(img_bytes))

            bio = io.BytesIO()
            image.save(bio, format="PNG")
            bio.seek(0)

            await update.message.reply_photo(photo=InputFile(bio, filename="generated.png"), caption=f"🖼️ {prompt}")
        else:
            await update.message.reply_text("⚠️ Model tidak mendukung generate gambar. Fallback ke teks deskripsi.")
            await text_fallback_image(update, prompt)

    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"🔥 Error generate gambar:\n{err}")
        await update.message.reply_text(f"⚠️ Terjadi error saat membuat gambar:\n{str(e)}")


async def text_fallback_image(update, prompt):
    """Fallback kalau model gambar tidak aktif"""
    try:
        text_model = genai.GenerativeModel(MODEL_TEXT)
        response = text_model.generate_content([f"Buatkan deskripsi visual untuk: {prompt}"])
        await update.message.reply_text(f"📝 Deskripsi (fallback):\n{response.text}")
    except Exception as e:
        await update.message.reply_text(f"❌ Gagal melakukan fallback: {str(e)}")

# ========================================
# MESSAGE HANDLER
# ========================================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    message_text = update.message.text
    chat_type = update.message.chat.type

    # Hanya balas di grup jika di-mention atau reply
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
        # Simpan riwayat user
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        conversation_history[user_id].append({"role": "user", "content": message_text})

        # Hanya simpan 10 pesan terakhir
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]

        # Buat konteks percakapan
        context_text = ""
        for msg in conversation_history[user_id]:
            role = "User" if msg["role"] == "user" else "AI"
            context_text += f"{role}: {msg['content']}\n"

        # 🔥 Generate response dari Gemini
        model = genai.GenerativeModel(MODEL_TEXT)
        response = model.generate_content(
            contents=[{"role": "user", "parts": [context_text]}]
        )
        ai_response = response.text or "⚠️ Tidak ada respon dari AI."

        # Tambah ke riwayat
        conversation_history[user_id].append({"role": "assistant", "content": ai_response})

        # Batasi panjang agar tidak error Telegram
        MAX_LENGTH = 4000
        if len(ai_response) > MAX_LENGTH:
            for i in range(0, len(ai_response), MAX_LENGTH):
                await update.message.reply_text(ai_response[i:i + MAX_LENGTH])
        else:
            await update.message.reply_text(ai_response)

        logger.info(f"User {user_name} ({user_id}): {message_text}")
        logger.info(f"AI Response: {ai_response[:100]}...")

    except Exception as e:
        err = traceback.format_exc()
        logger.error(f"🔥 Full error traceback:\n{err}")
        await update.message.reply_text(f"⚠️ Terjadi error internal:\n\n{str(e)}")

# ========================================
# MAIN FUNCTION
# ========================================

def main():
    if not TELEGRAM_BOT_TOKEN or not GEMINI_API_KEY:
        logger.error("❌ Pastikan TELEGRAM_BOT_TOKEN dan GEMINI_API_KEY tersedia di .env")
        return

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("clear", clear_command))
    application.add_handler(CommandHandler("mode", mode_command))
    application.add_handler(CommandHandler("image", image_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error {context.error}"))

    logger.info("🤖 Bot started successfully (Gemini 2.5 Flash + Image Generator)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ========================================
# RUN
# ========================================

if __name__ == "__main__":
    main()

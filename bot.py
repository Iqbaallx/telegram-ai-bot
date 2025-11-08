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
import chess  # <-- Ditambahkan untuk catur

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
chess_games = {}  # <-- Ditambahkan untuk menyimpan status game catur per chat

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
/image <prompt> - Buat gambar
/chess_start - Mulai main catur
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
5️⃣ Gunakan `/chess_start` untuk main catur

⚙️ Commands:
/start - Mulai bot
/help - Bantuan
/clear - Hapus chat
/mode - Ganti mode
/image - Buat gambar
/chess_start - Mulai catur
/chess_stop - Hentikan catur
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
# CHESS GAME HANDLERS (FITUR BARU)
# ========================================

async def chess_start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memulai permainan catur baru."""
    chat_id = update.effective_chat.id
    if chat_id in chess_games:
        await update.message.reply_text(
            "⚠️ Permainan catur sudah berjalan di chat ini.\n"
            "Gunakan /move <langkah> untuk bermain atau /chess_stop untuk berhenti."
        )
        return

    chess_games[chat_id] = chess.Board()
    board = chess_games[chat_id]
    board_str = f"```\n{board}\n```"  # Papan catur versi teks ASCII

    await update.message.reply_text(
        f"♟️ *Permainan Catur Dimulai!* ♟️\n\n{board_str}\n\n"
        "Giliran: *Putih*.\n"
        "Gunakan /move <langkah> (misal: `/move e4` atau `/move Nf3`).\n"
        "Gunakan /chess_stop untuk mengakhiri game.",
        parse_mode="Markdown"
    )

async def chess_stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Menghentikan permainan catur yang sedang berjalan."""
    chat_id = update.effective_chat.id
    if chat_id in chess_games:
        del chess_games[chat_id]
        await update.message.reply_text("✅ Permainan catur telah dihentikan.")
    else:
        await update.message.reply_text("ℹ️ Tidak ada permainan catur yang sedang berjalan.")

async def chess_move_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Memproses langkah catur."""
    chat_id = update.effective_chat.id
    if chat_id not in chess_games:
        await update.message.reply_text("ℹ️ Tidak ada permainan catur yang berjalan. Mulai dengan /chess_start.")
        return

    board = chess_games[chat_id]
    move_str = " ".join(context.args)

    if not move_str:
        await update.message.reply_text("Gunakan format: `/move <langkah>` (misal: `/move e4`)")
        return

    try:
        # Mencoba mem-parsing langkah (misal: "e4", "Nf3", "e8=Q")
        board.push_san(move_str)
    except (chess.IllegalMoveError, chess.InvalidMoveError, chess.AmbiguousMoveError, ValueError) as e:
        # Jika gagal, coba parsing sebagai UCI (misal: "e2e4", "e7e8q")
        try:
            board.push_uci(move_str)
        except (chess.IllegalMoveError, chess.InvalidMoveError, ValueError):
            await update.message.reply_text(f"❌ Langkah tidak valid: `{move_str}`\n{e}", parse_mode="Markdown")
            return

    # Buat string papan catur versi baru
    board_str = f"```\n{board}\n```"
    giliran = "Putih" if board.turn == chess.WHITE else "Hitam"

    # Cek apakah game selesai
    if board.is_game_over():
        result = "Game Selesai!"
        if board.is_checkmate():
            result = f"♟️ *SKAKMAT!* Pemenangnya adalah {'Putih' if board.turn == chess.BLACK else 'Hitam'}."
        elif board.is_stalemate():
            result = "♟️ *STALEMATE!* Hasil seri."
        elif board.is_insufficient_material():
            result = "♟️ *SERI!* Materi tidak cukup."
        else:
            result = f"♟️ *SERI!* ({board.result()})"

        await update.message.reply_text(
            f"Langkah: `{move_str}`\n\n{board_str}\n\n"
            f"🎉 *{result}*",
            parse_mode="Markdown"
        )
        del chess_games[chat_id]  # Hapus game dari memori

    else:
        # Jika game belum selesai
        status = "Skak!" if board.is_check() else ""
        await update.message.reply_text(
            f"Langkah: `{move_str}`\n\n{board_str}\n\n"
            f"Giliran: *{giliran}*. {status}",
            parse_mode="Markdown"
        )

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
    
    # --- Handler Catur (BARU) ---
    application.add_handler(CommandHandler("chess_start", chess_start_command))
    application.add_handler(CommandHandler("chess_stop", chess_stop_command))
    application.add_handler(CommandHandler("move", chess_move_command))
    # --- Akhir Handler Catur ---

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    application.add_error_handler(lambda update, context: logger.error(f"Update {update} caused error {context.error}"))

    logger.info("🤖 Bot started successfully (Gemini 2.5 Flash + Image Generator + Chess)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# ========================================
# RUN
# ========================================

if __name__ == "__main__":
    main()
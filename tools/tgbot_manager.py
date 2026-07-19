import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# KONFIGURASI
TOKEN = ''
INPUT_DIR = '../RESUME'
MAX_FILE_SIZE = 1 * 1024 * 1024  # 1 MB dalam bytes
ALLOWED_EXTENSIONS = {'.pdf', '.doc', '.docx', '.txt'}

# Pastikan folder input ada
if not os.path.exists(INPUT_DIR):
    os.makedirs(INPUT_DIR)

logging.basicConfig(level=logging.INFO)

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    file_name = doc.file_name.lower()
    file_size = doc.file_size
    
    # 1. Validasi Ukuran (1 MB)
    if file_size > MAX_FILE_SIZE:
        await update.message.reply_text(
            f"❌ File ditolak! Ukuran file {file_name} ({file_size/1024/1024:.2f} MB) "
            "melebihi batas maksimal 1 MB."
        )
        return

    # 2. Validasi Tipe File (Ekstensi)
    _, ext = os.path.splitext(file_name)
    if ext not in ALLOWED_EXTENSIONS:
        await update.message.reply_text(
            f"❌ File ditolak! Ekstensi '{ext}' tidak didukung. "
            "Hanya izinkan: .pdf, .doc, .docx, .txt"
        )
        return

    # 3. Proses Download
    file = await doc.get_file()
    file_path = os.path.join(INPUT_DIR, doc.file_name)
    
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"✅ Berhasil! File '{doc.file_name}' telah diproses.")
    logging.info(f"File diterima & tersimpan: {doc.file_name}")

# FUNGSI BARU: Untuk menangani file yang bukan dokumen
async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Cek apakah user mengirim sesuatu yang bukan dokumen (gambar, video, teks)
    await update.message.reply_text(
        "❌ Maaf, saya hanya menerima file dokumen (PDF, Doc, Docx, Txt).\n"
        "Tolong kirimkan file tersebut sebagai 'File' atau 'Dokumen', bukan sebagai 'Foto' atau 'Gambar'."
    )

if __name__ == '__main__':
    application = ApplicationBuilder().token(TOKEN).build()
    
    # 1. Handler untuk Dokumen (Yang kita inginkan)
    doc_handler = MessageHandler(filters.Document.ALL, handle_document)
    
    # 2. Handler untuk SEMUA hal lain (Foto, Video, Sticker, Text, dll)
    # Tanda '~' artinya "BUKAN" (NOT)
    unknown_handler = MessageHandler(~filters.Document.ALL, handle_unknown)
    
    application.add_handler(doc_handler)
    application.add_handler(unknown_handler) # Tambahkan ini di bawah doc_handler
    
    print("Bot Telegram berjalan (dengan sistem feedback)...")
    application.run_polling()
from datetime import datetime
import shutil
import sqlite3

from core_agent.registry import ToolRegistry
from core_agent.config import temp_dir, knowledge_dir, sqlite_db_path
from database.knowledgeprocessor import process_hr_knowledge


@ToolRegistry.register(is_sensitive=False)
def update_catatan_tugas(catatan_baru: str) -> str:
    """
    GUNAKAN ALAT INI jika ada instruksi pengguna yang terpaksa ditunda (karena butuh data tambahan/otorisasi).
    Tuliskan pengingat singkat di parameter 'catatan_baru' (misal: 'Tunggu jam interview ID 8 dari HR, lalu jadwalkan').
    """
    # Di LangGraph, output dari tool ini bisa diparsing untuk mengupdate state 'pending_tasks'
    return f"SISTEM: Catatan tugas berhasil disimpan di memori -> {catatan_baru}"

@ToolRegistry.register(is_sensitive=False)
def cek_kalender_server() -> str:
    """
    GUNAKAN ALAT INI HANYA JIKA user menanyakan tanggal hari ini, waktu saat ini, 
    atau acuan kalender sistem.
    """
    waktu_sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"Tanggal dan waktu server saat ini adalah: {waktu_sekarang}"

@ToolRegistry.register(is_sensitive=False)
def simpan_dokumen_ke_knowledge(nama_file: str, start_page: int = 1) -> str:
    """
    Tools untuk memproses dokumen PDF panduan HR yang diunggah lewat chat.
    Tools ini mengambil file dari temp_uploads, memindahkannya ke knowledge_docs, 
    dan memprosesnya ke Vector DB (ChromaDB) dan SQLite.
    """
    # 1. Validasi Ekstensi
    if not nama_file.lower().endswith('.pdf'):
        return "Gagal: Dokumen panduan HR mutlak harus berformat .pdf!"

    file_asal = temp_dir / nama_file
    file_tujuan = knowledge_dir / nama_file

    # 2. Cek apakah file ada di Staging Area
    if not file_asal.exists():
        return f"Gagal: File fisik '{nama_file}' tidak ditemukan. Pastikan Anda sudah melampirkan file dengan benar di chat."

    try:
        # 3. Pindahkan file secara permanen ke folder knowledge
        shutil.move(str(file_asal), str(file_tujuan))
        
        # 4. Ingest file ke ChromaDB via knowledgeprocessor
        is_success = process_hr_knowledge(str(file_tujuan), start_page=start_page)
        
        if is_success:
            # 5. Rekam ke SQLite dengan mode WAL agar muncul di UI Tab 3
            with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute('''
                    INSERT OR REPLACE INTO hr_knowledge (filename, upload_date, uploaded_by)
                    VALUES (?, ?, ?)
                ''', (nama_file, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "HR via Chat"))
                conn.commit()
                
            return f"Sukses! Dokumen panduan '{nama_file}' berhasil dimasukkan ke Knowledge Base dan dipelajari AI."
        else:
            return "Gagal memproses dokumen ke Vector Database. File mungkin rusak atau start_page melebihi batas."
            
    except Exception as e:
        return f"Gagal: Terjadi error internal saat sistem memindahkan file -> {str(e)}"

@ToolRegistry.register(is_sensitive=True)
def kirim_pesan_kandidat(nama_kandidat: str, pesan: str) -> str:
    """
    GUNAKAN ALAT INI UNTUK MENGIRIM PESAN ATAU EMAIL KE KANDIDAT.
    Tool ini akan mengeksekusi pengiriman notifikasi eksternal.
    """
    print(f"-> [SISTEM MENGIRIM PESAN] Ke: {nama_kandidat} | Isi: {pesan}")
    return f"Pesan berhasil dikirim ke {nama_kandidat}."
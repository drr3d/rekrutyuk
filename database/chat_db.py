import sqlite3
import json

# 1. Mengambil path secara terpusat dari config
from core_agent.config import sqlite_db_path

def init_chat_db():
    """Membuat tabel riwayat chat jika belum ada dan melakukan migrasi."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        # Gunakan WAL mode agar aman jika dibaca/ditulis bersamaan oleh UI dan Agent
        conn.execute("PRAGMA journal_mode=WAL;")
        
        # [UPDATE]: Menambahkan kolom thread_id dan username untuk mengisolasi memori percakapan
        conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                thread_id TEXT,
                role TEXT,
                content TEXT,
                metadata TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # [MIGRASI OTOMATIS]: Tambahkan kolom username jika menggunakan database versi lama
        try:
            conn.execute("ALTER TABLE chat_history ADD COLUMN username TEXT DEFAULT 'Guest'")
        except sqlite3.OperationalError:
            pass # Kolom sudah ada, abaikan error

def load_chat_history(thread_id="Sesi Utama (Default)", username="Guest"):
    """Memuat riwayat chat dari database berdasarkan thread_id dan username."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        
        # [UPDATE]: Hanya memanggil chat milik user tertentu di ruangan yang sedang aktif
        cursor.execute(
            "SELECT role, content, metadata FROM chat_history WHERE thread_id = ? AND username = ? ORDER BY id ASC",
            (thread_id, username)
        )
        
        messages = []
        for row in cursor.fetchall():
            msg = {"role": row["role"], "content": row["content"]}
            if row["metadata"]:
                msg["download_file"] = json.loads(row["metadata"])
            messages.append(msg)
        return messages

def save_chat_message(role, content, metadata=None, thread_id="Sesi Utama (Default)", username="Guest"):
    """Menyimpan satu pesan baru ke database terikat pada user dan thread tertentu."""
    meta_str = json.dumps(metadata) if metadata else None
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        # [UPDATE]: Memasukkan username ke dalam database saat pesan disimpan
        conn.execute(
            "INSERT INTO chat_history (username, thread_id, role, content, metadata) VALUES (?, ?, ?, ?, ?)",
            (username, thread_id, role, content, meta_str)
        )

def clear_chat_history(thread_id=None, username="Guest"):
    """Menghapus riwayat obrolan khusus milik user tersebut."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        if thread_id:
            # Hapus chat HANYA untuk user ini di thread ini
            conn.execute("DELETE FROM chat_history WHERE thread_id = ? AND username = ?", (thread_id, username))
        else:
            # Hapus SEMUA chat HANYA untuk user ini (tidak mengganggu user lain)
            conn.execute("DELETE FROM chat_history WHERE username = ?", (username,))
            
    # LANGKAH 2: Lakukan VACUUM di koneksi terpisah tanpa transaksi (autocommit)
    with sqlite3.connect(sqlite_db_path, timeout=30.0, isolation_level=None) as conn:
        conn.execute("VACUUM")
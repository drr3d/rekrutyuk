import sqlite3
import json
from pathlib import Path

# Konfigurasi Path Database
app_dir = Path(__file__).resolve().parent
sqlite_db_path = app_dir / "hr_database.db"

def init_chat_db():
    """Membuat tabel riwayat chat jika belum ada."""
    with sqlite3.connect(sqlite_db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS chat_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT,
                content TEXT,
                metadata TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

def load_chat_history():
    """Memuat riwayat chat dari database saat aplikasi dibuka."""
    with sqlite3.connect(sqlite_db_path) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT role, content, metadata FROM chat_history ORDER BY id ASC")
        
        messages = []
        for row in cursor.fetchall():
            msg = {"role": row["role"], "content": row["content"]}
            if row["metadata"]:
                msg["download_file"] = json.loads(row["metadata"])
            messages.append(msg)
        return messages

def save_chat_message(role, content, metadata=None):
    """Menyimpan satu pesan baru ke database."""
    meta_str = json.dumps(metadata) if metadata else None
    with sqlite3.connect(sqlite_db_path) as conn:
        conn.execute(
            "INSERT INTO chat_history (role, content, metadata) VALUES (?, ?, ?)",
            (role, content, meta_str)
        )

def clear_chat_history():
    """Menghapus semua riwayat obrolan."""
    with sqlite3.connect(sqlite_db_path) as conn:
        # Hapus tabel chat_history jika ada, untuk membersihkan data
        conn.execute("DROP TABLE IF EXISTS chat_history")
    # Buat ulang tabel kosong
    init_chat_db()
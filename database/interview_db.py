import sqlite3
from core_agent.config import sqlite_db_path

def init_interview_db():
    """Inisialisasi tabel interview_schedule jika belum ada."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute('''
            CREATE TABLE IF NOT EXISTS interview_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kandidat_id INTEGER,
                nama_kandidat TEXT,
                posisi TEXT,
                tanggal_interview TEXT,
                jam_interview TEXT,
                pewawancara TEXT,
                created_by TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(kandidat_id) REFERENCES kandidat(id)
            )
        ''')

def get_upcoming_interviews():
    """Mengambil semua jadwal interview yang akan datang."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM interview_schedule ORDER BY tanggal_interview ASC, jam_interview ASC")
        return [dict(row) for row in cursor.fetchall()]

def insert_single_schedule(kandidat_id, nama_kandidat, posisi, tanggal, jam, pewawancara, username):
    """Menyimpan satu jadwal interview."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute('''
            INSERT INTO interview_schedule (kandidat_id, nama_kandidat, posisi, tanggal_interview, jam_interview, pewawancara, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (kandidat_id, nama_kandidat, posisi, tanggal, jam, pewawancara, username))
    return True

def delete_schedule(schedule_id):
    """Menghapus jadwal interview tertentu."""
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("DELETE FROM interview_schedule WHERE id = ?", (schedule_id,))
    return True
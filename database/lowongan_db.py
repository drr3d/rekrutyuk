import sqlite3
from core_agent.config import sqlite_db_path

# inisialisasi tabel lowongan
def init_lowongan_db():
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS lowongan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                posisi TEXT,
                deskripsi TEXT,
                keyword_wajib TEXT,
                is_aktif INTEGER DEFAULT 1
            )
        ''')

        # 2. FIX UNTUK GUI: Pastikan tabel kandidat ada (meskipun masih kosong) 
        # agar operasi LEFT JOIN di Streamlit tidak crash "no such table: kandidat"
        # 2. FIX UNTUK GUI: Buat tabel kandidat kosong mengikuti skema TERBARU 
        # dari textprocessor.py agar operasi LEFT JOIN di Streamlit tidak crash
        conn.execute('''
            CREATE TABLE IF NOT EXISTS kandidat (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nama_kandidat TEXT, 
                nik TEXT, 
                email TEXT, 
                no_hp TEXT, 
                gender TEXT, 
                usia INTEGER, 
                asal_daerah TEXT,
                pekerjaan_aktif_saat_ini TEXT, 
                status_kalkulasi TEXT, 
                pendidikan_terakhir TEXT,
                jurusan TEXT, 
                ipk REAL, 
                skill_utama TEXT, 
                lama_bekerja_tahun REAL,
                file_cv TEXT UNIQUE, 
                tanggal_masuk TEXT, 
                source INTEGER,
                status_screening TEXT, 
                alasan_screening TEXT
            )
        ''')

        conn.commit()
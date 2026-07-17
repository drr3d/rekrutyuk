import os
import json
import re
from pathlib import Path
from datetime import datetime
import sqlite3

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
# KEMBALI KE OLLAMA EMBEDDINGS (Tanpa HuggingFace Transformers)
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

# --- 1. SETUP PATH & DATABASE ---
app_dir = Path(__file__).resolve().parent
db_path = (app_dir / "../chroma_db").resolve()
json_path = app_dir / "kandidat_profil.json"
config_path = app_dir / "config.json"

# --- KONFIGURASI PATH DATABASE SQLITE ---
sqlite_db_path = app_dir / "hr_database.db"

embeddings = OllamaEmbeddings(model="nomic-embed-text")
vector_db = Chroma(persist_directory=str(db_path), embedding_function=embeddings)

# --- 2. PROMPT EXTRACTION ---
# Kita gunakan "riwayat_periode_kerja" agar AI tidak bingung.
# [NEW UPGRADE]: Menambahkan flag 'pekerjaan_aktif_saat_ini' dan 'status_kalkulasi' untuk transparansi HR.
# [PERBAIKAN]: Komentar double-slash (//) DIHAPUS dari dalam struktur JSON agar tidak membuat Qwen error.
extraction_prompt = ChatPromptTemplate.from_messages([
    ("system", 
     "Kamu adalah Senior HR Data Extractor. Tugasmu mengekstrak informasi dari teks CV "
     "(CV bisa berbahasa Indonesia atau English) ke dalam format JSON yang presisi.\n\n"
    
     "}}\n"
     "PENTING: Jangan mengarang informasi. Jika data tidak ditemukan, gunakan string kosong \"\" untuk teks, angka 0 untuk nominal, atau array kosong []."
    ),
    ("human", "Teks CV:\n{text_cv}")
])

def auto_screening_cv(profil_kandidat: dict, model_name: str) -> tuple[str, str]:
    """
    Fungsi otonom untuk mengevaluasi kandidat terhadap lowongan aktif 
    langsung setelah proses ekstraksi CV selesai.
    """
    try:
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            cursor = conn.cursor()

            # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
            cursor.execute("PRAGMA journal_mode=WAL;")

            # 1. Pastikan tabel lowongan ada agar tidak crash saat pertama kali jalan
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS lowongan (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    posisi TEXT,
                    deskripsi TEXT,
                    keyword_wajib TEXT,
                    is_aktif INTEGER DEFAULT 1
                )
            ''')
            # 2. Ambil 1 lowongan yang statusnya masih aktif (paling baru ditambahkan)
            cursor.execute("SELECT posisi, keyword_wajib FROM lowongan WHERE is_aktif = 1 ORDER BY id DESC LIMIT 1")
            lowongan = cursor.fetchone()
            
        # Jika belum ada lowongan yang dibuat HR, kembalikan status netral
        if not lowongan:
            return "UNSCREENED", "Menunggu evaluasi. Belum ada data lowongan aktif di sistem saat CV ini masuk."
            
        posisi_lowongan, keyword_lowongan = lowongan
        
        # 3. Merakit Prompt Evaluasi Otomatis (Format Wajib JSON)
        prompt_screening = ChatPromptTemplate.from_messages([
            ("system", 
             "Kamu adalah AI Senior HR Screener otomatis yang bekerja di balik layar.\n"
             "Tugasmu: Evaluasi kecocokan data JSON kandidat terhadap kriteria lowongan aktif.\n\n"
             
            ),
            ("human", 
             f"Posisi Lowongan: {posisi_lowongan}\n"
             f"Keyword Wajib: {keyword_lowongan}\n\n"
             f"Data Ekstraksi CV Kandidat:\n{json.dumps(profil_kandidat, indent=2)}"
            )
        ])
        
        print(f"-> [Auto-Screening] Mencocokkan dengan lowongan aktif: {posisi_lowongan}...")
        
        # Panggil LLM dengan format JSON agar tidak melantur
        llm_screener = ChatOllama(model=model_name, temperature=0.0, format="json")
        raw_result = (prompt_screening | llm_screener).invoke({}).content
        
        # Bersihkan format jika LLM menambahkan markdown ```json
        cleaned_output = re.sub(r'```json\s*|```', '', raw_result, flags=re.IGNORECASE).strip()
        hasil_json = json.loads(cleaned_output)
        
        status = hasil_json.get("status_screening", "CAUTION").upper()
        alasan = hasil_json.get("alasan_screening", "Terjadi kesalahan ekstraksi alasan dari respon AI.")
        
        # Beri tag posisi pada alasan agar HR tahu CV ini dievaluasi untuk posisi apa
        alasan_lengkap = f"[Evaluasi: {posisi_lowongan}] {alasan}"
        return status, alasan_lengkap
        
    except Exception as e:
        print(f"-> [Auto-Screening] Error saat proses screening: {e}")
        return "ERROR", f"Sistem gagal melakukan screening otomatis: {str(e)}"

def hitung_total_tahun_kerja(periode_list):
    """Fungsi ajaib pengubah teks tanggal menjadi angka (tahun) presisi"""
    if not isinstance(periode_list, list) or not periode_list:
        return 0.0
        
    # [PERBAIKAN]: Mengambil tahun dan bulan secara dinamis dari sistem (bukan hardcode 2026)
    now = datetime.now()
    tahun_sekarang = now.year
    bulan_sekarang = now.month
    
    bulan_map = {
        'jan':1, 'feb':2, 'mar':3, 'apr':4, 'may':5, 'jun':6, 
        'jul':7, 'aug':8, 'sep':9, 'oct':10, 'nov':11, 'dec':12
    }
    
    def parse_tgl(tgl_str):
        tgl_str = tgl_str.strip().lower()
        if any(word in tgl_str for word in ['current', 'present', 'now', 'sekarang']):
            return tahun_sekarang, bulan_sekarang
            
        thn_match = re.search(r'\b(19|20)\d{2}\b', tgl_str)
        thn = int(thn_match.group(0)) if thn_match else tahun_sekarang
        
        bln = 1
        for b_name, b_num in bulan_map.items():
            if b_name in tgl_str:
                bln = b_num
                break
        return thn, bln

    # [NEW UPGRADE]: ALGORITMA PENGGABUNGAN RENTANG (INTERVAL MERGING)
    # Tujuannya agar jika pelamar kerja di 2 perusahaan pada bulan yang sama (tumpang tindih),
    # bulan tersebut hanya dihitung 1 kali, tidak di-double count.
    intervals = []
    
    for periode in periode_list:
        try:
            parts = re.split(r'\bto\b|\buntil\b|-|–', periode)
            if len(parts) >= 2:
                thn_mulai, bln_mulai = parse_tgl(parts[0])
                thn_selesai, bln_selesai = parse_tgl(parts[-1]) # Ambil part terakhir
                
                # Ubah ke bulan absolut (contoh: tahun 2010 bulan 2 = 2010*12 + 2)
                start_abs = (thn_mulai * 12) + bln_mulai
                end_abs = (thn_selesai * 12) + bln_selesai
                
                # Masukkan ke daftar interval jika start lebih kecil dari end
                if start_abs < end_abs:
                    intervals.append([start_abs, end_abs])
        except Exception:
            continue
            
    if not intervals:
        return 0.0

    # 1. Urutkan semua periode kerja berdasarkan waktu mulai (tanggal paling jadul ke paling baru)
    intervals.sort(key=lambda x: x[0])
    
    # 2. Proses penggabungan rentang (Merging)
    merged_intervals = [intervals[0]]
    
    for current in intervals[1:]:
        last_merged = merged_intervals[-1]
        
        # Jika kerjaan baru mulai sebelum kerjaan lama selesai (ada TUMPANG TINDIH)
        if current[0] <= last_merged[1]:
            # Gabungkan rentang waktunya ke waktu terjauh
            last_merged[1] = max(last_merged[1], current[1])
        else:
            # Jika tidak ada tumpang tindih, masukkan sebagai periode kerja baru (independen)
            merged_intervals.append(current)
            
    # 3. Hitung total bulan dari interval yang sudah dibersihkan dari tumpang tindih
    total_bulan = sum(interval[1] - interval[0] for interval in merged_intervals)
            
    return round(total_bulan / 12, 1)

def update_database_catalog(filename: str, text_cv: str, model_name: str, recreate_db: bool=False):
    """Fungsi untuk mengekstrak, mengevaluasi, dan menyimpan data terstruktur ke SQLite"""
    print(f"-> [AI Extractor] Menganalisis profil dari {filename} menggunakan model: {model_name}...")
    try:
        llm_extractor = ChatOllama(model=model_name, temperature=0.0, format="json")
        raw_output = (extraction_prompt | llm_extractor).invoke({"text_cv": text_cv}).content
        cleaned_output = re.sub(r'```json\s*|Markup|```', '', raw_output, flags=re.IGNORECASE).strip()
        
        match = re.search(r'\{.*\}', cleaned_output, re.DOTALL)
        if match:
            cleaned_output = match.group(0)
            
        profil_baru = json.loads(cleaned_output)
        
        # --- [PROSES BARU]: JALANKAN SCREENING OTOMATIS ---
        status_screening, alasan_screening = auto_screening_cv(profil_baru, model_name)
        
        # Kalkulasi tahun kerja
        list_periode = profil_baru.get("riwayat_periode_kerja", [])
        lama_bekerja = hitung_total_tahun_kerja(list_periode)
        
        nama = profil_baru.get("nama_kandidat", "Tidak Diketahui")
        # --- SANITASI NIK DENGAN REGEX ---
        nik_raw = str(profil_baru.get("nik", ""))
        # Hanya sisakan digit/angka (Hapus titik, strip, spasi, huruf typo, dll)
        nik_bersih = re.sub(r'\D', '', nik_raw)
        
        # Opsi Validasi: Jika ingin ketat, kosongkan jika tidak pas 16 digit. 
        # Jika ingin mentolerir typo pelamar (misal cuma 15 digit), biarkan saja tersimpan apa adanya.
        nik = nik_bersih if len(nik_bersih) >= 14 else "" 
        # ----------------------------------
        email = profil_baru.get("email", "")
        no_hp = profil_baru.get("no_hp", "")
        pekerjaan_aktif = json.dumps(profil_baru.get("pekerjaan_aktif_saat_ini", []))
        skill_utama = json.dumps(profil_baru.get("skill_utama", []))
        tgl_masuk = datetime.now().strftime("%Y-%m-%d")
        
        # Simpan ke SQLite menggunakan UPSERT (Insert or Replace)
        with sqlite3.connect(sqlite_db_path , timeout=30.0) as conn:
            cursor = conn.cursor()

            # === SEMENTARA: Hapus tabel kandidat lama agar skema baru terbentuk bersih ===
            # (Hapus baris ini setelah program dijalankan sekali agar tidak menghapus data terus-menerus)
            if recreate_db:
                cursor.execute("DROP TABLE IF EXISTS kandidat")
            
            # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
            cursor.execute("PRAGMA journal_mode=WAL;")

            # [SAFE MIGRATION]: Tambahkan kolom baru jika ini adalah database lama yang belum di-reset
            try:
                cursor.execute("ALTER TABLE kandidat ADD COLUMN status_screening TEXT")
                cursor.execute("ALTER TABLE kandidat ADD COLUMN alasan_screening TEXT")
                cursor.execute("ALTER TABLE kandidat ADD COLUMN nik TEXT")
                cursor.execute("ALTER TABLE kandidat ADD COLUMN email TEXT")
                cursor.execute("ALTER TABLE kandidat ADD COLUMN no_hp TEXT")
            except sqlite3.OperationalError:
                pass # Mengabaikan error jika kolom sudah ada
                
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS kandidat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nama_kandidat TEXT, nik TEXT, email TEXT, no_hp TEXT, gender TEXT, usia INTEGER, asal_daerah TEXT,
                    pekerjaan_aktif_saat_ini TEXT, status_kalkulasi TEXT, pendidikan_terakhir TEXT,
                    jurusan TEXT, ipk REAL, skill_utama TEXT, lama_bekerja_tahun REAL,
                    file_cv TEXT UNIQUE, tanggal_masuk TEXT, source INTEGER,
                    status_screening TEXT, alasan_screening TEXT
                )
            ''')
            
            cursor.execute('''
                INSERT OR REPLACE INTO kandidat (
                    nama_kandidat, nik, email, no_hp, gender, usia, asal_daerah, pekerjaan_aktif_saat_ini,
                    status_kalkulasi, pendidikan_terakhir, jurusan, ipk, skill_utama,
                    lama_bekerja_tahun, file_cv, tanggal_masuk, source,
                    status_screening, alasan_screening
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                nama, nik, email, no_hp, profil_baru.get("gender", ""), profil_baru.get("usia", 0),
                profil_baru.get("asal_daerah", ""), pekerjaan_aktif,
                profil_baru.get("status_kalkulasi", "Bersih"),
                profil_baru.get("pendidikan_terakhir", ""), profil_baru.get("jurusan", ""),
                profil_baru.get("ipk", 0.0), skill_utama, lama_bekerja, filename, tgl_masuk, 0,
                status_screening, alasan_screening
            ))
            conn.commit()

        status_calc = profil_baru.get('status_kalkulasi', 'Bersih')
        print(f"-> [AI Extractor] Sukses! Profil {nama} tersimpan ke SQLite.")
        print(f"   [Summary] Pengalaman: {lama_bekerja} Thn | Keputusan Screening: {status_screening}")
        
    except Exception as e:
        print(f"-> [AI Extractor] Gagal mengekstrak/menyimpan profil ke database: {e}")

# --- 3. FUNGSI UTAMA PEMROSESAN ---
def process_cv(file_path):
    filename = os.path.basename(file_path)
    print(f"\n=== Memproses file: {filename} ===")
    
    # [NEW UPGRADE]: Validasi Jumlah Halaman di Detik Pertama
    # Ini mencegah aplikasi macet (hang) jika kandidat melampirkan CV yang kepanjangan
    try:
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        jumlah_halaman = len(documents)
        
        if jumlah_halaman > 5:
            print(f"❌ [DITOLAK] File {filename} memiliki {jumlah_halaman} halaman (Maksimal 5).")
            print("=== Selesai (Dibatalkan) ===\n")
            return 
            
        print(f"-> [Validasi Lolos] CV terdiri dari {jumlah_halaman} halaman.")
        
    except PermissionError as e:
        # [PERBAIKAN KRUSIAL]: Tangkap PermissionError spesifik dan lemparkan (raise) 
        # kembali ke atas agar worker di resume_wdog.py bisa menangkapnya untuk melakukan Retry.
        raise e
        
    except Exception as e:
        # Error lain selain PermissionError akan dihentikan di sini agar tidak membebani sistem
        print(f"❌ [ERROR] Gagal membaca PDF {filename}: {e}")
        return
    
    # --- [DYNAMIC CONFIG] MEMBACA SETTING MODEL UNTUK EXTRACTOR ---
    model_extractor_name = "qwen3.5:4b" 
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                model_extractor_name = config_data.get("model_extractor", "qwen3.5:4b")
        except Exception:
            pass
            
    try:
        vector_db.delete(where={"source": filename})
    except Exception:
        pass 
    
    full_text = "\n".join(doc.page_content for doc in documents)
    
    # [OPTIMASI 3]: KOMPRESI SPASI EKSTREM UNTUK MERINGANKAN VRAM
    # Meratakan teks dengan menghapus semua \n, tab, dan spasi ganda menjadi 1 spasi.
    # Teks tetap utuh 100% sampai ujung bawah dokumen, tapi jumlah total karakternya 
    # berkurang drastis sehingga GPU lebih cepat mengevaluasinya tanpa kehilangan akurasi kalender.
    teks_untuk_json = re.sub(r'\s+', ' ', full_text).strip()
    
    # [PROSES 1: STRUCTURED RAG] - Ekstrak JSON menggunakan teks yang sudah dikompresi
    #update_json_catalog(filename, teks_untuk_json, model_extractor_name)
    # JANGAN LUPA SET KEMBALI recreate_db = False ketika sudah selesai
    update_database_catalog(filename, teks_untuk_json, model_extractor_name, False)
    
    # [PROSES 2: UNSTRUCTURED RAG] - Split & Simpan ke ChromaDB
    # Untuk vektor, TETAP gunakan full_text mentah agar tidak ada format (seperti list) yang rusak untuk Retrieval
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    chunks = text_splitter.split_documents(documents)
    
    ids = []
    for i, chunk in enumerate(chunks):
        chunk.metadata["source"] = filename
        chunk.metadata["type"] = "resume"
        unique_id = f"{filename}_{i}"
        ids.append(unique_id)
    
    vector_db.add_documents(chunks, ids=ids)
    print(f"-> [ChromaDB] Berhasil menyimpan {len(chunks)} chunk teks untuk {filename}!")
    print("=== Selesai ===\n")
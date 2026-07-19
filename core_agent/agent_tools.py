import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Annotated, TypedDict
import sqlite3
import importlib
import pkgutil

from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig

# --- TAMBAHKAN IMPORT INI ---
from tools.freeform_calculation import calculate_age_from_entry_year
from database.knowledgeprocessor import generate_interview_questions, process_hr_knowledge

class ToolRegistry:
    """Registry agar kontributor bisa inject tools dari luar tanpa merubah file ini."""
    safe_tools = []
    sensitive_tools = []

    @classmethod
    def register(cls, is_sensitive=False):
        def decorator(func):
            # Ubah fungsi python biasa menjadi Langchain @tool
            langchain_tool = tool(func)
            if is_sensitive:
                cls.sensitive_tools.append(langchain_tool)
            else:
                cls.safe_tools.append(langchain_tool)
            return langchain_tool
        return decorator

# --- KONFIGURASI DATABASE & LLM ---
app_dir = Path(__file__).resolve().parent.parent

db_path = (app_dir / "APPDB/chroma_db").resolve()
json_path = app_dir / "kandidat_profil.json" # considered to be remove
config_path = app_dir / "config.json"
sqlite_db_path = app_dir / "APPDB/hr_database.db"
knowledge_dir = app_dir / "knowledge_docs"
temp_dir = app_dir / "temp_uploads"

# --- [DYNAMIC CONFIG] MEMBACA SETTING MODEL UNTUK CHAT AGENT ---
model_chat_name = "qwen2.5:1.5b" # Default fallback jika config tidak ada
if config_path.exists():
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            # Mengambil model_chat_agent, jika tidak diset otomatis pakai qwen2.5:1.5b
            model_chat_name = config_data.get("model_chat_agent", "qwen2.5:1.5b")
    except Exception:
        pass

embeddings = OllamaEmbeddings(model="nomic-embed-text")
vector_db = Chroma(persist_directory=str(db_path), embedding_function=embeddings)

# [PERBAIKAN KRUSIAL]: 'k' dinaikkan jadi 10 agar AI bisa membaca seluruh halaman CV
retriever = vector_db.as_retriever(search_kwargs={"k": 10}) 

# LLM sebagai "Otak" Agent dinamis berdasarkan konfigurasi.
# beberapa setting num_ctx: 4086, 8192, 12288, 16384
llm = ChatOllama(model=model_chat_name, temperature=0.1, num_ctx=16384)

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

init_lowongan_db()

# --- FUNGSI BACA CONFIG ---
analytics_config_path = app_dir / "analytics_config.json"

def get_analytics_config():
    """Membaca konfigurasi analitik tingkat lanjut."""
    default_config = {
        "query_limits": {"max_group_by_results": 10, "enable_fuzzy_matching": False},
        "data_integrity": {
            "exclude_nulls_in_aggregation": True,
            "handle_outliers": {"min_valid_age": 17, "max_valid_age": 60},
            "deduplicate_by": ""
        },
        "security": {"mask_pii_for_staff": True}
    }
    if analytics_config_path.exists():
        try:
            with open(analytics_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return default_config

# --- 2. DEFINISI TOOLS (KEMAMPUAN AGENT) ---
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

@ToolRegistry.register(is_sensitive=False)
def pencarian_web_umum(query: str) -> str:
    """
    GUNAKAN ALAT INI UNTUK MENCARI INFORMASI APAPUN DI INTERNET.
    Gunakan jika user menanyakan info umum, profil perusahaan, standar gaji, regulasi, 
    atau data yang tidak ada di dalam database internal kandidat.
    """
    print(f"-> [Web Search] Mencari di internet: {query}...")
    try:
        # Melakukan pencarian ke internet (Otomatis bebas HTML)
        search = DuckDuckGoSearchAPIWrapper(max_results=3)
        hasil_web = search.run(query) 
        
        # Simpan hasil riset ini ke ChromaDB agar jadi ingatan permanen (General Knowledge)
        teks_memori = f"Informasi Web (Hasil pencarian untuk '{query}'):\n{hasil_web}"
        vector_db.add_texts(
            texts=[teks_memori],
            metadatas=[{"source": "web_search", "type": "general_knowledge", "query": query}]
        )
        print(f"-> [Memory] Info '{query}' berhasil disimpan ke Vector Database.")
        
        return f"Berikut adalah data dari internet: {hasil_web}"
    except Exception as e:
        return f"Gagal mencari di web: {e}"

@ToolRegistry.register(is_sensitive=False)
def cari_info_perusahaan_di_web(nama_perusahaan: str) -> str:
    """
    GUNAKAN ALAT INI UNTUK MENCARI LATAR BELAKANG, PROFIL, ATAU REPUTASI SEBUAH PERUSAHAAN DI INTERNET.
    Hanya gunakan jika HR bertanya spesifik tentang perusahaan tempat kandidat bekerja.
    """
    print(f"-> [Web Search] Mencari info tentang perusahaan: {nama_perusahaan}...")
    try:

        # Melakukan pencarian ke internet
        search = DuckDuckGoSearchAPIWrapper(max_results=3)
        hasil_web = search.run(f"profil perusahaan {nama_perusahaan} bergerak di bidang apa")
        
        # [KUNCI RAHASIA]: Simpan hasil riset ini ke ChromaDB agar jadi ingatan permanen!
        teks_memori = f"Informasi Latar Belakang Perusahaan {nama_perusahaan}:\n{hasil_web}"
        vector_db.add_texts(
            texts=[teks_memori],
            metadatas=[{"source": "web_search", "type": "company_info", "company": nama_perusahaan}]
        )
        print(f"-> [Memory] Info {nama_perusahaan} berhasil disimpan ke database.")
        
        return f"Hasil riset web: {hasil_web}"
    except Exception as e:
        return f"Gagal mencari di web: {e}"

@ToolRegistry.register(is_sensitive=False)
def cari_detail_kualitatif_cv(query: str) -> str:
    """
    GUNAKAN ALAT INI UNTUK MENCARI ISI TEKS RESUME SECARA MENDALAM.
    Jika kamu ingin mencari detail spesifik seseorang, pastikan kamu memasukkan nama kandidat ke dalam query ini (contoh: 'Pengalaman kerja Aulia Normansyah').
    """
    docs = retriever.invoke(query)
    if not docs:
        return "Tidak ditemukan informasi mendetail di dalam dokumen CV."
    
    hasil = "\n\n".join(f"[Sumber: {doc.metadata.get('source')}]:\n{doc.page_content}" for doc in docs)
    return hasil

@ToolRegistry.register(is_sensitive=True)
def kirim_pesan_kandidat(nama_kandidat: str, pesan: str) -> str:
    """
    GUNAKAN ALAT INI UNTUK MENGIRIM PESAN ATAU EMAIL KE KANDIDAT.
    Tool ini akan mengeksekusi pengiriman notifikasi eksternal.
    """
    print(f"-> [SISTEM MENGIRIM PESAN] Ke: {nama_kandidat} | Isi: {pesan}")
    return f"Pesan berhasil dikirim ke {nama_kandidat}."

# --- AUTO-DISCOVERY PLUGIN ---
# Sistem akan membaca otomatis semua file python di folder 'plugins'
# Memanfaatkan app_dir yang sudah dideklarasikan di atas
plugin_folder = app_dir / "plugins"

if plugin_folder.exists():
    # pkgutil.iter_modules membutuhkan list of string path
    for _, module_name, _ in pkgutil.iter_modules([str(plugin_folder)]):
        importlib.import_module(f"plugins.{module_name}")

# Kumpulkan tools untuk diexport ke agent_nodes.py
safe_tools = ToolRegistry.safe_tools
sensitive_tools = ToolRegistry.sensitive_tools
tools = safe_tools + sensitive_tools
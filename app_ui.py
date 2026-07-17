import streamlit as st
import json, sqlite3
import pandas as pd
from pathlib import Path
import os
from datetime import datetime

# --- IMPORT MODUL KUSTOM ---
from agent_graph import proses_chat_agent 
from chat_db import init_chat_db, load_chat_history, save_chat_message, clear_chat_history

# [NEW UPGRADE]: Import fungsi dari knowledge_processor yang baru kita buat sebelumnya
try:
    from knowledgeprocessor import process_hr_knowledge, knowledge_db
    KNOWLEDGE_PROCESSOR_AVAILABLE = True
except ImportError:
    KNOWLEDGE_PROCESSOR_AVAILABLE = False
    st.sidebar.error("Modul knowledge_processor.py tidak ditemukan. Fitur Tab 3 mungkin terbatas.")

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="HR Talent AI", page_icon="🤖", layout="wide")
st.markdown("<style>.stChatMessage { padding-bottom: 20px; }</style>", unsafe_allow_html=True)
st.title("🤖 HR Talent Acquisition Workspace")

app_dir = Path(__file__).resolve().parent
sqlite_db_path = app_dir / "hr_database.db"

# [NEW UPGRADE]: Folder untuk menyimpan dokumen fisik HR Knowledge
knowledge_dir = app_dir / "knowledge_docs"
knowledge_dir.mkdir(parents=True, exist_ok=True)

# --- TAMBAHAN BARU: Folder Staging Area untuk Chat ---
temp_dir = app_dir / "temp_uploads"
temp_dir.mkdir(parents=True, exist_ok=True)

# ==========================================
# --- SIDEBAR: SIMULASI LOGIN & HAK AKSES ---
# ==========================================
st.sidebar.title("🔒 Keamanan & Akun")
st.sidebar.markdown("Simulasi otorisasi lokal di dalam jaringan:")
user_role = st.sidebar.selectbox(
    "Pilih Role Anda:", 
    ["Staff", "HR Admin"],
    help="Role 'HR Admin' diperlukan untuk mengunduh dokumen fisik CV asli dan mengelola Knowledge Base."
)
st.session_state.user_role = user_role
st.sidebar.info(f"Aktif sebagai: **{st.session_state.user_role}**")

# ==========================================
# --- INISIALISASI SESSION STATE & DB ---
# ==========================================
if "messages" not in st.session_state:
    init_chat_db()
    st.session_state.messages = load_chat_history()

if "menunggu_approval" not in st.session_state:
    st.session_state.menunggu_approval = False
if "data_approval" not in st.session_state:
    st.session_state.data_approval = None

# [NEW UPGRADE]: Inisialisasi tabel hr_knowledge di SQLite
def init_knowledge_db():
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        cursor = conn.cursor()

        # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
        cursor.execute("PRAGMA journal_mode=WAL;")

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS hr_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filename TEXT UNIQUE,
                upload_date TEXT,
                uploaded_by TEXT
            )
        ''')
        conn.commit()

init_knowledge_db()

# ==========================================
# --- LAYOUTING TABS ---
# ==========================================
# [NEW UPGRADE]: Menambahkan Tab 3 untuk Knowledge Base
tab1, tab2, tab3= st.tabs(["💬 AI Assistant", "🗂️ Database Kandidat", "📢 Lowongan & Screening"])

# ------------------------------------------
# TAB 1: AI ASSISTANT
# ------------------------------------------
with tab1:
    st.subheader("💬 AI Recruitment Assistant")
    
    if st.button("🗑️ Bersihkan Riwayat Chat"):
        clear_chat_history()
        st.session_state.messages = []
        st.session_state.menunggu_approval = False
        st.session_state.data_approval = None
        st.rerun()

    chat_container = st.container(height=500)
    
    # 1. Render Histori Chat
    with chat_container:
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
                
                if "download_file" in message and message["download_file"]:
                    file_info = message["download_file"]
                    file_path = Path(file_info["path"])
                    
                    if st.session_state.user_role == "HR Admin":
                        if file_path.exists():
                            with open(file_path, "rb") as f:
                                st.download_button(
                                    label=f"📥 Unduh CV Asli: {file_info['nama_file']}",
                                    data=f.read(),
                                    file_name=file_info["nama_file"],
                                    mime="application/octet-stream",
                                    key=f"dl_{file_path.name}_{message['content'][:10]}"
                                )
                        else:
                            st.error("📁 Berkas fisik tidak ditemukan di harddisk server.")
                    else:
                        st.error("🔒 Akses Dihentikan: Anda tidak memiliki wewenang mengunduh dokumen asli.")

    # 2. Logika Chat & Approval (HITL)
    if st.session_state.menunggu_approval:
        approval_ui = st.empty()
        with approval_ui.container():
            st.warning("⚠️ **Sistem Membutuhkan Persetujuan Anda**")
            st.info(st.session_state.data_approval["pesan"])
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Setujui & Lanjutkan", use_container_width=True):
                    approval_ui.empty()
                    with chat_container:
                        with st.chat_message("assistant"):
                            with st.spinner("AI sedang mengeksekusi tindakan..."):
                                hasil = proses_chat_agent(is_approval=True, user_role=st.session_state.user_role)
                                st.markdown(hasil["pesan"])
                                
                                save_chat_message("assistant", hasil["pesan"], hasil.get("download_info"))
                                st.session_state.messages.append({
                                    "role": "assistant", 
                                    "content": hasil["pesan"],
                                    "download_file": hasil.get("download_info")
                                })
                    st.session_state.menunggu_approval = False
                    st.session_state.data_approval = None
                    st.rerun()
                
            with col2:
                if st.button("❌ Batalkan", use_container_width=True):
                    st.session_state.menunggu_approval = False
                    st.session_state.data_approval = None
                    st.rerun()

    # --- JIKA TIDAK ADA APPROVAL, TAMPILKAN INPUT CHAT & DRAG DROP ---
    elif not st.session_state.menunggu_approval:
        
        # INISIALISASI KEY UNTUK RESET UPLOADER
        if "file_uploader_key" not in st.session_state:
            st.session_state.file_uploader_key = 0

        # MENGGUNAKAN POPOVER AGAR UPLOADER TERSEMBUNYI (Lebih elegan)
        with st.popover("📎 Lampirkan Dokumen (Opsional)"):
            st.markdown("Hanya menerima file `.txt` dan `.pdf` (Maks: 2MB | 5 Halaman).")
            lampiran_dokumen = st.file_uploader(
                "Pilih File (Draft Lowongan / CV Pelamar)", # [PERBAIKAN 1]: Label UI dinetralkan
                type=["txt", "pdf"],
                accept_multiple_files=False,
                key=f"uploader_{st.session_state.file_uploader_key}", 
                label_visibility="collapsed" 
            )

        prompt = st.chat_input("Tanya seputar kandidat atau minta AI memproses file di atas...")
        
        if prompt:
            teks_prompt_ke_ai = prompt
            info_lampiran_ui = ""
            
            if lampiran_dokumen is not None:
                # ==========================================
                # 🛡️ LAPISAN VALIDASI UPFRONT (SEBELUM PROSES)
                # ==========================================
                ext = lampiran_dokumen.name.split('.')[-1].lower()
                if ext not in ['txt', 'pdf']:
                    st.error("❌ Akses Ditolak: Sistem hanya menerima file berekstensi .txt atau .pdf.")
                    st.stop()
                
                if lampiran_dokumen.size > 2097152:
                    st.error(f"❌ File terlalu besar! Ukuran file Anda: {round(lampiran_dokumen.size/1024/1024, 2)}MB. (Maksimal 2MB)")
                    st.stop()

                # --- TAMBAHAN BARU: SIMPAN KE FOLDER SEMENTARA (STAGING AREA) ---
                lokasi_simpan_sementara = temp_dir / lampiran_dokumen.name
                with open(lokasi_simpan_sementara, "wb") as f:
                    f.write(lampiran_dokumen.getbuffer())

                # ==========================================
                # ⚙️ EKSTRAKSI TEKS
                # ==========================================
                isi_teks = ""
                try:
                    if ext == 'txt':
                        isi_teks = lampiran_dokumen.getvalue().decode('utf-8')
                        
                    elif ext == 'pdf':
                        import PyPDF2 
                        pdf_reader = PyPDF2.PdfReader(lampiran_dokumen)
                        
                        if len(pdf_reader.pages) > 5:
                            st.error(f"❌ Dokumen terlalu panjang! PDF Anda memiliki {len(pdf_reader.pages)} halaman. (Maksimal 5 Halaman)")
                            st.stop()
                            
                        for page in pdf_reader.pages:
                            teks_halaman = page.extract_text()
                            if teks_halaman:
                                isi_teks += teks_halaman + "\n"
                                
                    if not isi_teks.strip():
                        st.error("❌ Dokumen kosong atau teks tidak dapat diekstrak.")
                        st.stop()

                    # [PERBAIKAN 2]: Hapus label (Isi Draft Lowongan) agar AI menebak sendiri isinya
                    teks_prompt_ke_ai += f"\n\n--- DOKUMEN LAMPIRAN: {lampiran_dokumen.name} ---\n{isi_teks}"
                    info_lampiran_ui = f"\n\n> 📎 *Membaca dokumen yang dilampirkan: {lampiran_dokumen.name}*"
                    
                except Exception as e:
                    st.error(f"Gagal memproses file: {e}")
                    st.stop()

            teks_tampil_di_ui = prompt + info_lampiran_ui
            with chat_container:
                with st.chat_message("user"):
                    st.markdown(teks_tampil_di_ui)
            
            save_chat_message("user", teks_tampil_di_ui)
            st.session_state.messages.append({"role": "user", "content": teks_tampil_di_ui})

            # === LOGIKA RESET UPLOADER ===
            # Naikkan angka key agar Streamlit merender uploader baru yang kosong
            st.session_state.file_uploader_key += 1

            # === [PERBAIKAN] PESAN SPINNER DINAMIS ===
            pesan_spinner = "AI sedang membaca lampiran dan mengeksekusi..." if lampiran_dokumen is not None else "AI sedang memproses instruksi Anda..."
            with chat_container:
                with st.chat_message("assistant"):
                    with st.spinner(pesan_spinner):
                        hasil = proses_chat_agent(user_input=teks_prompt_ke_ai, user_role=st.session_state.user_role)
                        
                        if hasil["status"] == "butuh_persetujuan":
                            st.session_state.menunggu_approval = True
                            st.session_state.data_approval = hasil
                            st.rerun()
                        else:
                            st.markdown(hasil["pesan"])
                            save_chat_message("assistant", hasil["pesan"], hasil.get("download_info"))
                            st.session_state.messages.append({
                                "role": "assistant", 
                                "content": hasil["pesan"],
                                "download_file": hasil.get("download_info")
                            })
                            st.rerun() # Refresh halaman untuk memastikan uploader benar-benar bersih

    elif prompt := st.chat_input("Tanya seputar kandidat di sini..."):
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)
        
        save_chat_message("user", prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        with chat_container:
            with st.chat_message("assistant"):
                with st.spinner("AI sedang menganalisis data..."):
                    hasil = proses_chat_agent(user_input=prompt, user_role=st.session_state.user_role)
                    
                    if hasil["status"] == "butuh_persetujuan":
                        st.session_state.menunggu_approval = True
                        st.session_state.data_approval = hasil
                        st.rerun()
                    else:
                        st.markdown(hasil["pesan"])
                        save_chat_message("assistant", hasil["pesan"], hasil.get("download_info"))
                        st.session_state.messages.append({
                            "role": "assistant", 
                            "content": hasil["pesan"],
                            "download_file": hasil.get("download_info")
                        })

# ------------------------------------------
# TAB 2: DATABASE KANDIDAT (INTERAKTIF)
# ------------------------------------------
with tab2:
    st.markdown("### 🗂️ Katalog Kandidat (Interaktif & Real-time)")
    
    if sqlite_db_path.exists():
        try:
            with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
                conn.execute("PRAGMA journal_mode=WAL;")
                df = pd.read_sql_query("SELECT * FROM kandidat", conn)
            
            if not df.empty:
                col1, col2, col3 = st.columns(3)
                col1.metric("Total Kandidat", len(df))
                
                if "usia" in df.columns:
                    mean_usia = df[df["usia"] > 0]["usia"].mean()
                    col2.metric("Rata-rata Usia", round(mean_usia, 1) if pd.notna(mean_usia) else 0)
                    
                if "lama_bekerja_tahun" in df.columns:
                    mean_pengalaman = df["lama_bekerja_tahun"].mean()
                    col3.metric("Rata-rata Pengalaman", f"{round(mean_pengalaman, 1)} Thn")
                
                column_config = {
                    "id": st.column_config.NumberColumn("ID", disabled=True), 
                    "file_cv": st.column_config.TextColumn("File CV", disabled=True), 
                    "gender": st.column_config.SelectboxColumn(
                        "Gender", help="Pilih jenis kelamin", options=["Male", "Female"], required=False
                    ),
                    "pekerjaan_aktif_saat_ini": st.column_config.TextColumn("Pekerjaan Aktif", disabled=True),
                    "skill_utama": st.column_config.TextColumn("Skill Utama", disabled=True)
                }

                st.markdown("💡 *Anda dapat mengedit data langsung pada tabel di bawah ini (klik dua kali pada sel).*")
                
                edited_df = st.data_editor(
                    df, use_container_width=True, column_config=column_config,
                    hide_index=True, num_rows="fixed"
                )
                
                if st.button("💾 Simpan Perubahan ke Database", type="primary"):
                    try:
                        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                            cursor = conn.cursor()
                            # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
                            cursor.execute("PRAGMA journal_mode=WAL;")
                            for index, row in edited_df.iterrows():
                                cursor.execute('''
                                    UPDATE kandidat 
                                    SET nama_kandidat=?, gender=?, usia=?, asal_daerah=?,
                                        status_kalkulasi=?, pendidikan_terakhir=?, jurusan=?, ipk=?, 
                                        lama_bekerja_tahun=?
                                    WHERE id=?
                                ''', (
                                    row['nama_kandidat'], row['gender'], row['usia'], row['asal_daerah'],
                                    row['status_kalkulasi'], row['pendidikan_terakhir'], row['jurusan'], row['ipk'],
                                    row['lama_bekerja_tahun'], row['id']
                                ))
                            conn.commit()
                        st.success("✅ Perubahan data berhasil disimpan!")
                    except Exception as e:
                        st.error(f"❌ Gagal menyimpan data: {e}")
                        
            else:
                st.warning("Database SQLite sudah dibuat, tetapi belum ada data kandidat.")
        except Exception as e:
            st.error(f"Gagal membaca atau memproses database SQLite: {e}")
    else:
        st.info("Sistem menunggu database SQLite dibuat.")

with tab3:
    st.header("📢 Dashboard Lowongan & Karantina")
    
    # ==========================================
    # BAGIAN 1: MANAJEMEN LOWONGAN
    # ==========================================
    st.subheader("📋 Daftar Lowongan Aktif")
    
    # [MIGRASI OTOMATIS]: Pastikan struktur tabel lowongan sudah versi terbaru sebelum dibaca
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        cursor = conn.cursor()

        # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
        cursor.execute("PRAGMA journal_mode=WAL;")

        # Buat tabel jika belum ada sama sekali
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS lowongan (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                posisi TEXT,
                deskripsi TEXT,
                keyword_wajib TEXT,
                is_aktif INTEGER DEFAULT 1
            )
        ''')
        # Suntikkan kolom tanggal jika menggunakan tabel versi lama
        try:
            cursor.execute("ALTER TABLE lowongan ADD COLUMN tanggal_mulai TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE lowongan ADD COLUMN tanggal_selesai TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    # Form Tambah Lowongan Manual
    with st.expander("➕ Tambah Lowongan Baru (Manual)"):
        with st.form("form_tambah_lowongan"):
            posisi = st.text_input("Posisi Pekerjaan")
            deskripsi = st.text_area("Deskripsi Pekerjaan")
            keyword = st.text_area("Keywords Wajib (pisahkan dengan koma)")
            
            col1, col2 = st.columns(2)
            tgl_mulai = col1.date_input("Tanggal Mulai")
            tgl_selesai = col2.date_input("Tanggal Selesai")
            
            submitted = st.form_submit_button("Simpan Lowongan")
            if submitted:
                if posisi and keyword:
                    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                        # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
                        conn.execute("PRAGMA journal_mode=WAL;")

                        conn.execute('''
                            INSERT INTO lowongan (posisi, deskripsi, keyword_wajib, tanggal_mulai, tanggal_selesai, is_aktif) 
                            VALUES (?, ?, ?, ?, ?, 1)
                        ''', (posisi, deskripsi, keyword, str(tgl_mulai), str(tgl_selesai)))
                    st.success(f"Lowongan '{posisi}' berhasil disimpan!")
                    st.rerun()
                else:
                    st.warning("Posisi dan Keyword Wajib harus diisi!")
    
    # Menampilkan Tabel List Lowongan dengan Statistik
    try:
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            query_statistik = """
                SELECT 
                    l.id, l.posisi, l.deskripsi, l.keyword_wajib, l.tanggal_mulai, l.tanggal_selesai,
                    COUNT(CASE WHEN k.status_screening = 'MATCH' THEN 1 END) as total_match,
                    COUNT(CASE WHEN k.status_screening = 'CAUTION' THEN 1 END) as total_caution,
                    COUNT(CASE WHEN k.status_screening = 'REJECT' THEN 1 END) as total_reject
                FROM lowongan l
                LEFT JOIN kandidat k ON k.alasan_screening LIKE '%[Evaluasi: ' || l.posisi || ']%'
                GROUP BY l.id
                ORDER BY l.id DESC
            """
            # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
            conn.execute("PRAGMA journal_mode=WAL;")
            df_low = pd.read_sql(query_statistik, conn)
        
        if not df_low.empty:
            st.write("Centang kotak pada kolom paling kiri untuk melihat detail atau menghapus data.")
            
            # 1. Tambahkan kolom Checkbox buatan ke DataFrame
            df_low.insert(0, "Pilih", False) 
            
            # 2. Render sebagai tabel interaktif (Data Editor)
            # Kita kunci (disabled) semua kolom agar tidak bisa diedit teksnya, KECUALI kolom "Pilih"
            kolom_dikunci = [col for col in df_low.columns if col != "Pilih"]
            
            edited_df = st.data_editor(
                df_low,
                column_config={
                    "Pilih": st.column_config.CheckboxColumn("Pilih", help="Centang untuk memilih lowongan"),
                    "id": st.column_config.NumberColumn("ID", width="small"),
                    "deskripsi": None, # Tetap sembunyikan kolom panjang
                    "keyword_wajib": None,
                    "total_match": st.column_config.ProgressColumn("✅ MATCH", format="%d", max_value=50),
                    "total_caution": st.column_config.ProgressColumn("⚠️ CAUTION", format="%d", max_value=50),
                    "total_reject": st.column_config.ProgressColumn("❌ REJECT", format="%d", max_value=50)
                },
                disabled=kolom_dikunci, # Kunci teks agar tidak berantakan
                use_container_width=True,
                hide_index=True
            )

            # 3. Tangkap baris mana saja yang sedang dicentang oleh HR
            baris_terpilih = edited_df[edited_df["Pilih"] == True]
            
            # 4. Tampilkan Detail dan Tombol Hapus HANYA JIKA ada baris yang dicentang
            if not baris_terpilih.empty:
                st.divider()
                st.subheader("🔍 Aksi untuk Lowongan Terpilih")
                
                # Jika HR mencentang lebih dari 1, kita bisa buat tombol Hapus Massal (Bulk Delete)
                if len(baris_terpilih) > 1:
                    list_id_hapus = baris_terpilih['id'].tolist()
                    st.warning(f"Anda memilih {len(list_id_hapus)} lowongan sekaligus.")
                    if st.button("🗑️ Hapus Semua yang Dicentang", type="primary"):
                        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                            # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
                            conn.execute("PRAGMA journal_mode=WAL;")

                            placeholders = ",".join("?" * len(list_id_hapus))
                            conn.execute(f"DELETE FROM lowongan WHERE id IN ({placeholders})", list_id_hapus)
                        st.success("Data massal berhasil dihapus!")
                        st.rerun()
                
                # Jika HR hanya mencentang 1, tampilkan detail lengkapnya (seperti dropdown tadi, tapi lebih canggih)
                elif len(baris_terpilih) == 1:
                    data_detail = baris_terpilih.iloc[0]
                    with st.container(border=True):
                        st.markdown(f"#### {data_detail['posisi']} (ID: {data_detail['id']})")
                        st.markdown(f"**Keyword Wajib:** {data_detail['keyword_wajib']}")
                        st.info(data_detail['deskripsi'])
                        
                        if st.button("🗑️ Hapus Lowongan Ini", type="primary"):
                            with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                                # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
                                conn.execute("PRAGMA journal_mode=WAL;")

                                conn.execute("DELETE FROM lowongan WHERE id = ?", (int(data_detail['id']),))
                            st.success("Data berhasil dihapus!")
                            st.rerun()
        else:
            st.info("Belum ada lowongan pekerjaan yang tercatat di database.")
            
    except Exception as e:
        st.error(f"Gagal memuat data lowongan: {e}")

    st.divider()

    # ==========================================
    # BAGIAN 2: REVIEW KANDIDAT (KARANTINA)
    # ==========================================
    st.subheader("⚠️ Tinjauan Kandidat (Caution & Reject)")
    st.markdown("Berikut adalah daftar CV kandidat yang tidak lolos standar otomatis AI atau memerlukan tinjauan manual dari HR.")
    
    # [MIGRASI OTOMATIS]: Pastikan tabel kandidat juga punya kolom screening terbaru
    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
        cursor = conn.cursor()
        # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
        cursor.execute("PRAGMA journal_mode=WAL;")

        try:
            cursor.execute("ALTER TABLE kandidat ADD COLUMN status_screening TEXT")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE kandidat ADD COLUMN alasan_screening TEXT")
        except sqlite3.OperationalError:
            pass
        conn.commit()

    try:
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
            conn.execute("PRAGMA journal_mode=WAL;")

            df_review = pd.read_sql("""
                SELECT id, nama_kandidat, file_cv, status_screening, alasan_screening 
                FROM kandidat 
                WHERE status_screening IN ('CAUTION', 'REJECT', 'UNSCREENED')
                ORDER BY id DESC
            """, conn)
            
        if not df_review.empty:
            st.dataframe(
                df_review, 
                column_config={
                    "id": st.column_config.NumberColumn("ID", width="small"),
                    "nama_kandidat": st.column_config.TextColumn("Nama Kandidat"),
                    "file_cv": st.column_config.TextColumn("Nama File CV"),
                    "status_screening": st.column_config.TextColumn("Status"),
                    "alasan_screening": st.column_config.TextColumn("Analisis AI", width="large")
                },
                use_container_width=True,
                hide_index=True
            )
        else:
            st.success("🎉 Luar biasa! Saat ini tidak ada kandidat di daftar karantina.")
            
    except Exception as e:
        st.info("Menunggu data masuk. Pastikan ada CV baru yang diproses oleh sistem.")
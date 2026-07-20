import os
import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime

# [NEW UPGRADE]: Import fungsi dari knowledge_processor yang baru kita buat sebelumnya
try:
    from database.knowledgeprocessor import process_hr_knowledge, knowledge_db
    KNOWLEDGE_PROCESSOR_AVAILABLE = True
except ImportError:
    KNOWLEDGE_PROCESSOR_AVAILABLE = False
    st.sidebar.error("Modul knowledge_processor.py tidak ditemukan. Fitur Tab 3 mungkin terbatas.")

# ------------------------------------------
# [NEW UPGRADE]: TAB 3: HR KNOWLEDGE BASE
# ------------------------------------------
def render(sqlite_db_path, knowledge_dir):
    st.markdown("### 📚 Kelola Pustaka Panduan HR (SOP, Teori, Peraturan)")
    st.write("Unggah dokumen PDF seperti buku panduan wawancara, regulasi BPJS, atau SOP perusahaan. AI akan menggunakan dokumen ini sebagai referensi utama (Single Source of Truth).")

    if st.session_state.user_role != "HR Admin":
        st.warning("🔒 Anda memerlukan akses **HR Admin** untuk mengelola Knowledge Base.")
    else:
        # --- BAGIAN UPLOAD DOKUMEN (DENGAN VALIDASI KETAT) ---
        with st.form("upload_knowledge_form", clear_on_submit=True):
            uploaded_file = st.file_uploader("Unggah File PDF Baru", type=["pdf"])

            # [NEW UPGRADE]: Input untuk menentukan halaman awal pemrosesan
            start_page = st.number_input(
                "Mulai Proses dari Halaman:", 
                min_value=1, 
                value=1, 
                step=1,
                help="Lewati halaman awal (seperti cover, kata pengantar, atau daftar isi) untuk menghemat ruang memori database."
            )

            submit_upload = st.form_submit_button("🚀 Unggah & Proses ke Vector Database")
            
            if submit_upload:
                # Validasi 1: Cek apakah user klik submit tanpa memasukkan file sama sekali
                if uploaded_file is None:
                    st.error("❌ Gagal: Anda belum memilih file, atau file yang diunggah tidak sesuai format (.pdf)!")
                
                else:
                    file_name = uploaded_file.name
                    
                    # Validasi 2: Proteksi ganda ekstensi file secara programmatif
                    if not file_name.lower().endswith('.pdf'):
                        st.error("❌ Gagal: Keamanan sistem menolak file ini. Hanya ekstensi .pdf yang diizinkan!")
                    
                    else:
                        # Jalur aman, file valid dan siap diproses
                        save_path = knowledge_dir / file_name
                        
                        # 1. Simpan file fisik ke direktori lokal
                        with open(save_path, "wb") as f:
                            f.write(uploaded_file.getbuffer())
                        
                        # 2. Proses ke Vector Database (ChromaDB)
                        if KNOWLEDGE_PROCESSOR_AVAILABLE:
                            with st.spinner(f"Memproses {file_name} mulai dari hal. {start_page}..."):
                                # [NEW UPGRADE]: Mengirimkan parameter start_page ke fungsi processor
                                is_success = process_hr_knowledge(str(save_path), start_page=start_page)
                                
                                if is_success:
                                    try:
                                        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                                            cursor = conn.cursor()

                                            # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
                                            cursor.execute("PRAGMA journal_mode=WAL;")
                                            cursor.execute('''
                                                INSERT OR REPLACE INTO hr_knowledge (filename, upload_date, uploaded_by)
                                                VALUES (?, ?, ?)
                                            ''', (file_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), st.session_state.user_role))
                                            conn.commit()
                                        st.success(f"✅ Dokumen '{file_name}' (Hal. {start_page}+) berhasil masuk ke otak AI!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Gagal menyimpan ke SQLite: {e}")
                                else:
                                    st.error("Gagal memproses dokumen ke Vector Database.")
                        else:
                            st.error("Modul knowledge_processor.py tidak tersedia untuk melakukan Vectoring.")

        st.divider()

        # --- BAGIAN MANAJEMEN DOKUMEN & HAPUS ---
        st.markdown("#### 📂 Daftar Dokumen Tersimpan")
        
        # Ambil data dari SQLite
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            # 1. PASANG PRAGMA WAL DI SINI (Baris pertama operasi)
            conn.execute("PRAGMA journal_mode=WAL;")

            df_knowledge = pd.read_sql_query("SELECT * FROM hr_knowledge", conn)
            
        if df_knowledge.empty:
            st.info("Belum ada dokumen panduan yang diunggah.")
        else:
            st.dataframe(df_knowledge, use_container_width=True, hide_index=True)
            
            st.markdown("**🗑️ Hapus Dokumen Usang**")
            st.write("Pastikan untuk menghapus dokumen lama agar AI tidak berhalusinasi dengan kebijakan yang saling tumpang tindih.")
            
            col_del1, col_del2 = st.columns([3, 1])
            with col_del1:
                file_to_delete = st.selectbox("Pilih file yang ingin dihapus dari otak AI:", df_knowledge['filename'].tolist())
            with col_del2:
                st.write("") # Spacer agar tombol sejajar
                st.write("")
                if st.button("🗑️ Hapus Permanen", type="primary", use_container_width=True):
                    
                    # 1. Hapus dari ChromaDB
                    if KNOWLEDGE_PROCESSOR_AVAILABLE:
                        try:
                            knowledge_db.delete(where={"source": file_to_delete})
                        except Exception as e:
                            st.warning(f"File vektor mungkin sudah tidak ada di ChromaDB. Lanjut menghapus... ({e})")
                            
                    # 2. Hapus fisik dari folder
                    file_path = knowledge_dir / file_to_delete
                    if file_path.exists():
                        os.remove(file_path)
                        
                    # 3. Hapus dari SQLite
                    with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
                        cursor = conn.cursor()

                        # AKTIFKAN MODE WAL (Write-Ahead Logging) AGAR MULTI-PROCESS AMAN
                        cursor.execute("PRAGMA journal_mode=WAL;")

                        cursor.execute("DELETE FROM hr_knowledge WHERE filename = ?", (file_to_delete,))
                        conn.commit()
                        
                    st.success(f"✅ File {file_to_delete} berhasil dihapus dari semua database.")
                    st.rerun() # Refresh halaman agar tabel terupdate
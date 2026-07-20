import streamlit as st
import sqlite3
import pandas as pd

def render(sqlite_db_path):
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
import streamlit as st
import sqlite3
import pandas as pd

from database.interview_db import get_upcoming_interviews, insert_single_schedule, delete_schedule

# ------------------------------------------
# TAB 5: MANAGEMENT INTERVIEW
# ------------------------------------------
def render(sqlite_db_path):
    st.markdown("### 📅 Jadwal & Papan Wawancara Pelamar")
    st.write("Kelola linimasa wawancara secara manual di bawah ini atau perintahkan AI Assistant di Tab 1 untuk melakukan penjadwalan cerdas/massal.")
    
    # Grid Sistem: Form Input Kiri, Data Live Kanan
    col_input, col_table = st.columns([1, 2])
    
    with col_input:
        st.markdown("#### ➕ Buat Jadwal Manual")
        
        # Tarik data kandidat dan lowongan terupdate untuk pilihan Dropdown
        with sqlite3.connect(sqlite_db_path, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Ambil id, nama_kandidat, dan file_cv
            cursor.execute("SELECT id, nama_kandidat, file_cv FROM kandidat ORDER BY id DESC")
            kandidat_rows = cursor.fetchall()
            
            # Ambil posisi dari tabel lowongan yang aktif
            cursor.execute("SELECT id, posisi FROM lowongan WHERE is_aktif = 1 ORDER BY id DESC")
            lowongan_rows = cursor.fetchall()
            
        # Format label kandidat: "Nama (Jika Ada) - Nama File CV"
        options_kandidat = {}
        for row in kandidat_rows:
            nama = row['nama_kandidat'] if row['nama_kandidat'] else "Tanpa Nama"
            label_kandidat = f"{nama} - {row['file_cv']}"
            options_kandidat[label_kandidat] = {
                "id": row['id'], 
                "nama_asli": nama # Kita simpan nama ini untuk dimasukkan ke DB Interview
            }
            
        # Format opsi lowongan
        options_lowongan = [row['posisi'] for row in lowongan_rows]
        
        # 1. Dropdown Kandidat (Bisa diketik untuk mencari / Searchable)
        if not options_kandidat:
            st.warning("⚠️ Belum ada data kandidat di database pelamar.")
            kandidat_terpilih = None
        else:
            kandidat_terpilih = st.selectbox(
                "Pilih Kandidat (Ketik untuk mencari):", 
                list(options_kandidat.keys())
            )
            
        # 2. Dropdown Posisi Lowongan
        if not options_lowongan:
            st.warning("⚠️ Belum ada lowongan aktif. Silakan tambah lowongan di Tab 4.")
            posisi_terpilih = None
        else:
            posisi_terpilih = st.selectbox(
                "Pilih Posisi Lowongan:", 
                options_lowongan
            )
            
        pewawancara_int = st.text_input("Nama Pewawancara / User:", placeholder="Contoh: Bpk Rian (Head of IT)")
        
        col_d, col_t = st.columns(2)
        tgl_int = col_d.date_input("Tanggal Wawancara:")
        jam_int = col_t.time_input("Jam Mulai:")
        
        btn_simpan_jadwal = st.button("💾 Kunci Jadwal", type="primary", use_container_width=True)
        
        if btn_simpan_jadwal:
            if kandidat_terpilih and posisi_terpilih and pewawancara_int:
                # Ambil ID dan Nama Asli dari dictionary yang kita buat
                kandidat_id_fix = options_kandidat[kandidat_terpilih]["id"]
                nama_kandidat_fix = options_kandidat[kandidat_terpilih]["nama_asli"]
                
                insert_single_schedule(
                    kandidat_id=kandidat_id_fix,
                    nama_kandidat=nama_kandidat_fix, # Tetap simpan namanya (atau "Tanpa Nama")
                    posisi=posisi_terpilih,          # Ambil langsung dari tabel lowongan
                    tanggal=str(tgl_int),
                    jam=jam_int.strftime("%H:%M"),
                    pewawancara=pewawancara_int,
                    username=st.session_state.username
                )
                st.success(f"✅ Jadwal bersama {pewawancara_int} berhasil dikunci!")
                st.rerun()
            else:
                st.error("❌ Mohon lengkapi seluruh field formulir di atas.")
                
    with col_table:
        st.markdown("#### 📅 Agenda Mendatang (Real-time)")
        data_jadwal = get_upcoming_interviews()
        
        if not data_jadwal:
            st.info("💡 Belum ada agenda wawancara terdaftar untuk waktu dekat.")
        else:
            df_jadwal = pd.DataFrame(data_jadwal)
            
            # Tampilkan ke dalam Data Editor interaktif dengan seleksi hapus
            df_jadwal.insert(0, "Batalkan", False)
            
            edited_sched_df = st.data_editor(
                df_jadwal,
                column_config={
                    "Batalkan": st.column_config.CheckboxColumn("Batalkan?", help="Centang untuk menghapus jadwal"),
                    "id": None, # Sembunyikan ID internal
                    "kandidat_id": None,
                    "nama_kandidat": "Kandidat",
                    "posisi": "Posisi Jabatan",
                    "tanggal_interview": "Tanggal",
                    "jam_interview": "Waktu",
                    "pewawancara": "Interviewer",
                    "created_by": "Dibuat Oleh",
                    "created_at": None
                },
                use_container_width=True,
                hide_index=True,
                disabled=[col for col in df_jadwal.columns if col != "Batalkan"]
            )
            
            # Aksi Hapus Massal jika dicentang
            jadwal_dihapus = edited_sched_df[edited_sched_df["Batalkan"] == True]
            if not jadwal_dihapus.empty:
                if st.button("🗑️ Eksekusi Pembatalan Terpilih", type="primary"):
                    for idx, row in jadwal_dihapus.iterrows():
                        delete_schedule(int(row['id']))
                    st.success("Jadwal terpilih berhasil dihapus dari agenda.")
                    st.rerun()
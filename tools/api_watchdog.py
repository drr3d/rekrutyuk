import os
import time
import threading
from queue import Queue
from pathlib import Path

from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

import sys
from pathlib import Path

# 1. Dapatkan path dari root folder proyek (naik 1 tingkat dari folder 'tools')
root_dir = Path(__file__).resolve().parent.parent

# 2. Masukkan root folder ke sistem path Python jika belum terdaftar
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from database.textprocessor import process_cv
from core_agent.config import app_dir

# --- SETUP DIREKTORI ---
# Menggunakan acuan app_dir dari textprocessor Anda agar path selalu konsisten
UPLOAD_DIR = (app_dir / "../RESUME").resolve()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# --- 1. SETUP ANTREAN (QUEUE) & WORKER ---
cv_queue = Queue()
# Tambahkan key "current_file" untuk melacak file yang sedang jalan
SERVICE_STATE = {"status": "RUNNING", "processed": 0, "failed": 0, "current_file": "-"}

def queue_worker():
    """Worker tunggal untuk mengeksekusi textprocessor agar database aman dari bentrok"""
    print(f"[Worker] Thread pemrosesan berjalan...")
    while SERVICE_STATE["status"] == "RUNNING":
        try:
            # Gunakan timeout agar while loop tidak freeze jika antrean kosong
            file_path = cv_queue.get(timeout=2)
        except:
            continue
            
        filename = os.path.basename(file_path)
        
        # ---> UPDATE STATUS: Beritahu UI bahwa file ini sedang dikerjakan <---
        SERVICE_STATE["current_file"] = filename 
        
        success = False
        
        # Retry mechanism
        for retry in range(5):
            try:
                hasil = process_cv(file_path)
                
                if hasil:
                    SERVICE_STATE["processed"] += 1
                else:
                    SERVICE_STATE["failed"] += 1
                    
                success = True
                break
            except PermissionError:
                print(f"[Worker] File {filename} sedang dikunci OS. Retry {retry+1}/5...")
                time.sleep(2)
            except Exception as e:
                print(f"[Worker] Kesalahan fatal saat memproses {filename}: {e}")
                SERVICE_STATE["failed"] += 1
                break
                
        if not success:
            print(f"[Worker] Menyerah memproses {filename} setelah 5 kali percobaan.")
            
        # ---> UPDATE STATUS: Kosongkan lagi karena sudah selesai <---
        SERVICE_STATE["current_file"] = "-" 
        cv_queue.task_done()

# Mulai worker thread
worker_thread = threading.Thread(target=queue_worker, daemon=True)
worker_thread.start()

# --- 2. SETUP WATCHDOG ---
class HandlerWatchdog(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory and event.src_path.lower().endswith(".pdf"):
            print(f"[Watchdog] Terdeteksi file baru: {os.path.basename(event.src_path)}")
            # Langsung masukkan ke dalam Queue
            cv_queue.put(event.src_path)

observer = Observer()
observer.schedule(HandlerWatchdog(), path=str(UPLOAD_DIR), recursive=False)
observer.start()
print(f"[System] Watchdog memantau direktori: {UPLOAD_DIR}")

# --- 3. SETUP FLASK API ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_DIR)

@app.route('/api/status', methods=['GET'])
def get_status():
    """Endpoint untuk aplikasi web lain memantau status RAG ingestion"""
    return jsonify({
        "status": SERVICE_STATE["status"],
        "antrean_tersisa": cv_queue.qsize(),
        "total_berhasil": SERVICE_STATE["processed"],
        "total_gagal": SERVICE_STATE["failed"],
        "pantauan_folder": str(UPLOAD_DIR)
    })

@app.route('/api/upload', methods=['POST'])
def api_upload_cv():
    """Endpoint untuk menerima CV dari HTTP Request (misal dari React/Vue JS)"""
    if 'file' not in request.files:
        return jsonify({"error": "Key 'file' tidak ditemukan di request"}), 400
        
    file = request.files['file']
    if file.filename == '' or not file.filename.lower().endswith('.pdf'):
        return jsonify({"error": "File tidak valid atau bukan PDF"}), 400
        
    filename = secure_filename(file.filename)
    save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    
    # 1. Simpan File ke lokal
    file.save(save_path)
    
    # 2. SELESAI. Watchdog otomatis mendeteksi file yang baru disave ini
    #    dan memasukannya ke Queue. API tidak perlu memanggil prosesnya.
    
    return jsonify({
        "message": "Dokumen berhasil diunggah",
        "file": filename,
        "posisi_antrean": cv_queue.qsize() + 1
    }), 202

@app.route('/', methods=['GET'])
def halaman_monitor():
    """Halaman UI Web sederhana untuk memantau Watchdog dan Antrean"""
    html_dashboard = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Monitor RAG HR</title>
        <style>
            body {{ font-family: Arial, sans-serif; padding: 20px; background-color: #f4f7f6; }}
            .card {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); max-width: 500px; margin: auto; }}
            h2 {{ text-align: center; color: #333; }}
            .status {{ font-size: 18px; margin: 10px 0; padding: 8px; border-radius: 5px; }}
            .processing-box {{ background-color: #fff3cd; color: #856404; border: 1px solid #ffeeba; }}
            .btn-refresh {{ display: block; width: 100%; padding: 10px; background: #007bff; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; margin-top: 15px; }}
            .btn-refresh:hover {{ background: #0056b3; }}
        </style>
        <!-- Auto refresh setiap 3 detik agar lebih responsif -->
        <meta http-equiv="refresh" content="3">
    </head>
    <body>
        <div class="card">
            <h2>📊 RAG HR Monitor</h2>
            <div class="status">🟢 <b>Status Layanan:</b> {SERVICE_STATE['status']}</div>
            <div class="status" style="font-size: 14px; color: gray;">📂 <b>Pantauan Folder:</b><br>{app.config['UPLOAD_FOLDER']}</div>
            <hr>
            
            <!-- INDIKATOR BARU -->
            <div class="status processing-box">
                🔄 <b>Sedang Diproses:</b> <br>
                <span style="font-weight: bold; font-size: 20px;">{SERVICE_STATE['current_file']}</span>
            </div>
            <hr>

            <div class="status">⏳ <b>Menunggu di Antrean:</b> {cv_queue.qsize()} file</div>
            <div class="status">✅ <b>Selesai (Sukses):</b> {SERVICE_STATE['processed']}</div>
            <div class="status">❌ <b>Selesai (Gagal):</b> {SERVICE_STATE['failed']}</div>
            
            <button class="btn-refresh" onclick="location.reload()">Refresh Manual</button>
            <p style="font-size: 12px; text-align: center; color: gray;">*Halaman ini akan auto-refresh setiap 3 detik</p>
        </div>
    </body>
    </html>
    """
    return html_dashboard

if __name__ == '__main__':
    print("[System] Server API Flask dimulai pada port 5000...")
    try:
        # use_reloader=False PENTING agar thread Queue/Watchdog tidak diduplikasi Flask
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    finally:
        # Graceful exit
        SERVICE_STATE["status"] = "OFF"
        observer.stop()
        observer.join()
        print("[System] Layanan dimatikan.")
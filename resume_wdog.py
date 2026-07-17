import time
import json
import logging
import threading
from queue import Queue
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from textprocessor import process_cv

# --- LOAD CONFIG ---
def load_config():
    # Pengaturan default jika file config.json rusak atau tidak ditemukan
    default_config = {
        "RESUME_WATCH_PATH": "../RESUME",
        "SUPPORTED_EXTENSIONS": [".pdf"],
        "model_extractor": "qwen3.5:4b",
        "model_chat_agent": "qwen3.5:4b"
    }
    
    script_dir = Path(__file__).resolve().parent
    config_path = script_dir / "config.json"
    
    if not config_path.exists():
        logging.warning(f"[CONFIG] config.json tidak ditemukan di {config_path}. Menggunakan pengaturan default.")
        return default_config
        
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logging.error(f"[CONFIG] Format config.json rusak/salah syntax: {e}")
        logging.warning("[CONFIG] Menggunakan pengaturan default agar sistem tetap berjalan.")
        return default_config
    except Exception as e:
        logging.error(f"[CONFIG] Gagal membaca config.json: {e}")
        return default_config

config = load_config()

# --- PENENTUAN PATH ---
app_dir = Path(__file__).resolve().parent
watch_path = (app_dir / config["RESUME_WATCH_PATH"]).resolve()

# --- LOGGING SETUP ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# =====================================================================
# SISTEM ANTREAN (QUEUE) & WORKER
# =====================================================================
# Buat antrean yang bisa menampung tugas tanpa batas
cv_queue = Queue()

def cv_worker():
    """Pekerja di balik layar yang memproses antrean CV satu per satu"""
    while True:
        # Menunggu sampai ada file di dalam antrean
        file_path = cv_queue.get()
        
        logging.info(f"[WORKER] Mulai mengeksekusi AI Pipeline untuk: {Path(file_path).name}")
        
        # Retry Logic dipindah ke sini agar tidak memblokir Watchdog
        success = False
        max_retries = 5
        for i in range(max_retries):
            try:
                process_cv(file_path)
                success = True
                break 
            except PermissionError:
                logging.warning(f"[WORKER] File dikunci OS, mencoba lagi dalam 2 detik (Percobaan {i+1})...")
                time.sleep(2)
            except Exception as e:
                logging.error(f"[WORKER] Gagal memproses CV: {e}")
                break
        
        if not success:
            logging.error(f"[WORKER] Menyerah pada {Path(file_path).name} setelah {max_retries} percobaan.")
            
        logging.info(f"[WORKER] Selesai memproses: {Path(file_path).name}. Sisa antrean: {cv_queue.qsize()}")
        
        # Beritahu sistem bahwa tugas ini sudah selesai
        cv_queue.task_done()

# Nyalakan Worker di thread terpisah (berjalan di background)
worker_thread = threading.Thread(target=cv_worker, daemon=True)
worker_thread.start()

# =====================================================================
# LOGIKA HANDLER (WATCHDOG / MANDOR)
# =====================================================================
class CVHandler(FileSystemEventHandler):
    def on_created(self, event):
        if not event.is_directory:
            ext = Path(event.src_path).suffix.lower()
            if ext in config["SUPPORTED_EXTENSIONS"]:
                logging.info(f"[WATCHDOG] File baru terdeteksi: {Path(event.src_path).name}. Memasukkan ke antrean...")
                # Watchdog hanya menaruh file ke antrean, lalu langsung kembali berjaga (sangat cepat)
                cv_queue.put(event.src_path)
            else:
                logging.info(f"[WATCHDOG] File diabaikan (ekstensi tidak didukung): {Path(event.src_path).name}")

# --- START OBSERVER ---
if not watch_path.exists():
    logging.info(f"Folder {watch_path} tidak ditemukan, membuat folder baru...")
    watch_path.mkdir(parents=True, exist_ok=True)

observer = Observer()
observer.schedule(CVHandler(), path=str(watch_path), recursive=False)
observer.start()

logging.info(f"Monitoring folder: {watch_path}")
logging.info("Sistem Antrean Aktif. Siap menerima banyak file sekaligus!")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    logging.info("Menghentikan sistem...")
    observer.stop()
    observer.join()
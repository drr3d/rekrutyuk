# --- KONFIGURASI DATABASE & LLM ---
from pathlib import Path
app_dir = Path(__file__).resolve().parent.parent

db_path = (app_dir / "APPDB/chroma_db").resolve()
json_path = app_dir / "kandidat_profil.json" # considered to be remove
config_path = app_dir / "config.json"
sqlite_db_path = app_dir / "APPDB/hr_database.db"
knowledge_dir = app_dir / "knowledge_docs"
temp_dir = app_dir / "temp_uploads"
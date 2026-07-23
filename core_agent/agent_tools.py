import json

import pickle
import numpy as np
import importlib
import pkgutil
from pathlib import Path

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.retrievers import BM25Retriever
from langchain_classic.retrievers import EnsembleRetriever

# --- TAMBAHKAN IMPORT INI ---
from .config import app_dir, config_path, db_path, sqlite_db_path
from .registry import ToolRegistry

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

# =====================================================================
# WAJIB IDENTIK DENGAN TEXTPROCESSOR AGAR DIMENSI VEKTOR COCOK (256)
# =====================================================================
class OptimizedCPUEmbeddings(HuggingFaceEmbeddings):
    target_dimensions: int = 256

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        prefixed_texts = [f"search_document: {t}" for t in texts]
        embs = super().embed_documents(prefixed_texts)
        return self._truncate_and_normalize(embs)
        
    def embed_query(self, text: str) -> list[float]:
        prefixed_text = f"search_query: {text}"
        emb = super().embed_query(prefixed_text)
        return self._truncate_and_normalize([emb])[0]
        
    def _truncate_and_normalize(self, embeddings: list[list[float]]) -> list[list[float]]:
        arr = np.array(embeddings)[:, :self.target_dimensions]
        norms = np.linalg.norm(arr, axis=1, keepdims=True)
        normalized = np.divide(arr, norms, out=np.zeros_like(arr), where=norms!=0)
        return normalized.tolist()

ollamaembedding = False
if ollamaembedding:
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vector_db = Chroma(persist_directory=str(db_path), embedding_function=embeddings)

    # [PERBAIKAN KRUSIAL]: 'k' dinaikkan jadi 10 agar AI bisa membaca seluruh halaman CV
    retriever = vector_db.as_retriever(search_kwargs={"k": 10}) 
else:
    bge_xmatroyshka = OptimizedCPUEmbeddings(
        model_name="BAAI/bge-m3",
        model_kwargs={'device': 'cpu'},
        encode_kwargs={'normalize_embeddings': False}
    )

    # Load VectorDB dengan Class yang identik
    vector_db = Chroma(
        persist_directory=str(db_path), 
        embedding_function=bge_xmatroyshka,
        collection_metadata={"hnsw:space": "cosine"}
    )

# LLM sebagai "Otak" Agent dinamis berdasarkan konfigurasi.
# beberapa setting num_ctx: 4086, 8192, 12288, 16384
llm = ChatOllama(model=model_chat_name, temperature=0.1, num_ctx=16384)

# =====================================================================
# [HYBRID RETRIEVER EXPORT] Gantikan `retriever` lama Anda dengan ini
# =====================================================================
def get_hybrid_retriever(top_k: int = 10):
    chroma_retriever = vector_db.as_retriever(search_kwargs={"k": top_k})
    
    bm25_corpus_path = Path(str(db_path)) / "bm25_corpus.pkl"
    bm25_retriever = None
    
    if bm25_corpus_path.exists():
        try:
            with open(bm25_corpus_path, "rb") as f:
                corpus_docs = pickle.load(f)
            if corpus_docs:
                bm25_retriever = BM25Retriever.from_documents(corpus_docs)
                bm25_retriever.k = top_k
        except Exception as e:
            print(f"[Warning] Gagal meload BM25: {e}")

    # Gabungkan Makna (Vector) dan Kata Kunci (BM25)
    if bm25_retriever:
        return EnsembleRetriever(
            retrievers=[chroma_retriever, bm25_retriever],
            weights=[0.5, 0.5]
        )
    return chroma_retriever



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
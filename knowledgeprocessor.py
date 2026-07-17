import os
import re
import json
from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_chroma import Chroma
from langchain_core.prompts import ChatPromptTemplate

# --- 1. SETUP PATH & DATABASE (Sinkron dengan textprocessor.py) ---
app_dir = Path(__file__).resolve().parent
db_path = (app_dir / "../chroma_db").resolve()
config_path = app_dir / "config.json"

# Menggunakan model embedding yang sama agar vektornya kompatibel
embeddings = OllamaEmbeddings(model="nomic-embed-text")

# --- KUNCI UTAMA: Menggunakan collection_name terpisah ---
knowledge_db = Chroma(
    persist_directory=str(db_path), 
    embedding_function=embeddings,
    collection_name="hr_knowledge"  # Dipisah agar tidak bercampur dengan CV
)


# --- 2. PROMPT GENERATOR INTERVIEW (DIPISAH DUA JALUR) ---
# PROMPT A: Jalur RAG (Jika buku panduan ADA)
prompt_dengan_buku = ChatPromptTemplate.from_messages([
    ("system", 
     "Kamu adalah Senior HR Assessor dan Psikolog Industri. Tugasmu menyusun pertanyaan interview "
     "berdasarkan PANDUAN ACUAN HR, lalu MENGEMBANGKANNYA sesuai dengan posisi yang dilamar.\n\n"
     
    ),
    ("human", 
     "PANDUAN ACUAN HR (Teori Dasar):\n{context}\n\n"
     "PERMINTAAN USER:\n{user_request}"
    )
])

# PROMPT B: Jalur Fallback (Jika buku panduan KOSONG)
prompt_tanpa_buku = ChatPromptTemplate.from_messages([
    ("system", 
     "Kamu adalah Senior HR Assessor dan Psikolog Industri. "
     "Gunakan pengetahuan terbaikmu dan standar industri global untuk menyusun pertanyaan interview "
    
     "3. Sesuaikan tingkat kesulitan dan gaya bahasa dengan posisi yang diminta user.\n\n"
     "FORMAT OUTPUT:\n"
     "- [Tahap/Tujuan]\n"
     "- [Pertanyaan]\n"
     "- [Ekspektasi Jawaban]"
    ),
    ("human", 
     "PERMINTAAN USER:\n{user_request}"
    )
])

# --- 3. FUNGSI UNTUK INGEST BUKU/DOKUMEN HR (Ratusan Halaman) ---
def process_hr_knowledge(file_path: str, start_page: int = 1) -> bool:
    """
    Fungsi untuk membaca buku panduan HR (PDF), memotongnya menjadi chunks, 
    dan menyimpannya ke dalam collection 'hr_knowledge'.
    Dilengkapi dengan fitur skip halaman (start_page) untuk efisiensi komputasi.
    """
    filename = os.path.basename(file_path)
    print(f"\n=== Memproses Dokumen Knowledge: {filename} ===")
    
    try:
        # Load PDF dokumen HR
        loader = PyPDFLoader(file_path)
        documents = loader.load()
        print(f"-> [Load Sukses] Dokumen terdiri dari {len(documents)} halaman.")
        
        # [NEW LOGIC]: Filter dokumen untuk skip halaman awal (cover, daftar isi, dll)
        # Note: documents[i].metadata["page"] adalah 0-indexed dari PyPDFLoader
        # Jadi doc.metadata.get("page", 0) + 1 adalah halaman aktual yang sesuai dengan mata manusia
        filtered_documents = [
            doc for doc in documents 
            if doc.metadata.get("page", 0) + 1 >= start_page
        ]
        
        # Validasi jika user memasukkan start_page yang melebihi jumlah halaman PDF
        if not filtered_documents:
            print(f"-> [Warning] Tidak ada halaman yang diproses karena start_page ({start_page}) melebihi total halaman PDF.")
            return False
            
        print(f"-> [Filter] Akan memproses {len(filtered_documents)} halaman (mulai dari halaman {start_page}).")
        
        # Hapus data lama untuk file yang sama agar tidak ada duplikasi vector (Vector Overwrite Protection)
        try:
            knowledge_db.delete(where={"source": filename})
            print(f"-> [Clean Up] Menghapus data vector lama untuk file: {filename}")
        except Exception:
            pass
            
        # Split dokumen menjadi potongan kecil (chunk_size sedikit lebih besar untuk buku panduan agar dapet konteks utuh)
        # Menambahkan length_function=len untuk akurasi penghitungan karakter bawaan Python 3
        # Chunk itu sederhananya ibaratkan 1 lemari besar, jika dibawa dalam kondisi semua tersusun partnya, maka akan sulit.
        #  jadi dengan Chunking itu kita potong 1 lemari besar itu menjadi potongan2 kecil, mirip puzzle gambar yg terpecah2,
        #  ketika semua nempel di papan puzzle, maka akan jadi besar, tapi ketika diambil setiap partnya, bisa dikumpulkan lebih kecil
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1200, 
            chunk_overlap=250,
            length_function=len
        )
        chunks = text_splitter.split_documents(filtered_documents)
        
        # Berikan metadata khusus pada setiap chunk
        ids = []
        for i, chunk in enumerate(chunks):
            chunk.metadata["source"] = filename
            chunk.metadata["type"] = "hr_knowledge"
            # Pastikan format page untuk RAG transparan mulai dari index 1
            chunk.metadata["page"] = chunk.metadata.get("page", 0) + 1 
            
            # Pembuatan ID unik untuk kemudahan manajemen database (Delete/Update)
            unique_id = f"knowledge_{filename}_{i}"
            ids.append(unique_id)
            
        # Simpan ke ChromaDB khusus collection 'hr_knowledge'
        knowledge_db.add_documents(chunks, ids=ids)
        print(f"-> [ChromaDB] Berhasil menyimpan {len(chunks)} chunk knowledge untuk {filename}!")
        print("=== Selesai ===\n")
        return True
        
    except Exception as e:
        print(f"❌ [ERROR] Gagal memproses dokumen HR Knowledge: {e}")
        return False


# --- 4. FUNGSI RAG UNTUK MEMBUAT SOAL INTERVIEW ---
def generate_interview_questions(user_request: str) -> str:
    """
    Fungsi RAG yang dipanggil saat user meminta dibuatkan pertanyaan interview.
    Mengambil konteks dari database knowledge, lalu melemparnya ke Qwen.
    Dilengkapi dengan fallback Zero-Shot jika database kosong.
    """
    # 1. Baca konfigurasi model aktif
    model_name = "qwen3.5:4b"
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = json.load(f)
                model_name = config_data.get("model_extractor", "qwen3.5:4b")
        except Exception:
            pass
            
    print(f"-> [RAG] Mencari panduan relevan untuk request: '{user_request}'...")
    
    # 2. Cari 4 chunk paling relevan dari database knowledge
    docs = knowledge_db.similarity_search(user_request, k=4)
    
    # 3. Panggil LLM Qwen (dengan temperature rendah agar patuh pada buku panduan/instruksi)
    try:
        llm = ChatOllama(model=model_name, temperature=0.2)
        print(f"-> [AI Generator] Menyusun pertanyaan menggunakan model: {model_name}...")
        
        # [PERBAIKAN]: Fallback ke pengetahuan bawaan AI jika DB kosong atau tidak relevan
        # Menggunakan logika percabangan prompt (If-Else Sederhana) yang lebih bersih
        if not docs:
            print("-> [RAG] Database HR kosong. Beralih ke pengetahuan bawaan (Zero-Shot)...")
            # Langsung panggil Prompt B (tanpa buku), variabel context tidak diperlukan
            response = (prompt_tanpa_buku | llm).invoke({
                "user_request": user_request
            })
        else:
            print("-> [RAG] Menemukan panduan relevan. Memakai prompt dengan buku acuan.")
            # Gabungkan dokumen yang relevan beserta informasi halaman untuk transparansi
            context_list = []
            for doc in docs:
                source_file = doc.metadata.get("source", "Unknown")
                page_num = doc.metadata.get("page", "?")
                context_list.append(f"[Sumber: {source_file} - Hal. {page_num}]\n{doc.page_content}")
                
            context = "\n\n---\n\n".join(context_list)
            
            # Panggil Prompt A (dengan buku) yang menerima suntikan variabel context
            response = (prompt_dengan_buku | llm).invoke({
                "context": context,
                "user_request": user_request
            })
            
        return response.content
        
    except Exception as e:
        # Menangkap dan mengembalikan pesan error dengan anggun (graceful degradation)
        return f"Gagal menghasilkan pertanyaan interview karena error: {e}"
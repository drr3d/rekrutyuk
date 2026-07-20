from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from core_agent.registry import ToolRegistry
from core_agent.agent_tools import vector_db

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
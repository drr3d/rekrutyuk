from typing import Dict, Any
import json

from .agent_graph import ToolFormatterRegistry

# ==========================================
# UI ADAPTER (Penterjemah State Mentah Graf -> Kebutuhan Frontend)
# ==========================================
class StreamlitAgentAdapter:
    """Adapter untuk menerjemahkan State Graf ke format UI Streamlit."""
    
    @staticmethod
    def process_state_to_ui(state) -> Dict[str, Any]:
        # PERUBAHAN DI SINI: Deteksi status butuh persetujuan secara universal
        if state.next:
            pesan_terakhir = state.values["messages"][-1]
            tool_calls = getattr(pesan_terakhir, "tool_calls", [])
            
            if tool_calls:
                detail_pesan = []
                for idx, tc in enumerate(tool_calls, 1):
                    nama_tool = tc["name"]
                    argumen_tool = tc["args"]
                    
                    formatted_arg = ToolFormatterRegistry.format(nama_tool, argumen_tool)
                    detail_pesan.append(f"{idx}. Tool: **{nama_tool}**\n{formatted_arg}")
                
                # Menampilkan nama Node yang sedang ditahan (opsional untuk info debug UI)
                node_tertahan = ", ".join(state.next)
                
                pesan_gabungan = (
                    f"### ⚠️ KONFIRMASI TINDAKAN (Menunggu di: {node_tertahan})\n"
                    "AI memerlukan konfirmasi persetujuan Anda untuk melakukan tindakan berikut:\n\n" + 
                    "\n\n".join(detail_pesan)
                )
                return {
                    "status": "butuh_persetujuan",
                    "tool": tool_calls[0]["name"] if len(tool_calls) == 1 else "multiple_tools",
                    "args": tool_calls[0]["args"] if len(tool_calls) == 1 else tool_calls,
                    "pesan": pesan_gabungan
                }

        # Skenario 2: Ekstraksi Link Download
        download_info = None
        if "messages" in state.values:
            for msg in reversed(state.values["messages"]):
                if getattr(msg, "name", None) == "ambil_tautan_download_cv":
                    try:
                        res_data = json.loads(msg.content)
                        if res_data.get("status") == "tersedia":
                            download_info = {
                                "nama_file": res_data["nama_file"],
                                "path": res_data["path"]
                            }
                        break
                    except Exception:
                        pass

        # Skenario 3: Ambil Jawaban Akhir
        jawaban_final = "Maaf, tidak ada respons yang valid dari agen."
        if "messages" in state.values:
            messages = state.values["messages"]
            
            # 1. Cari index pesan Human (User) terakhir
            last_human_idx = -1
            for i in range(len(messages) - 1, -1, -1):
                if messages[i].type == "human":
                    last_human_idx = i
                    break
            
            # 2. Gabungkan SEMUA teks dari AI setelah pesan User terakhir
            if last_human_idx != -1:
                kumpulan_teks_ai = []
                for msg in messages[last_human_idx + 1:]:
                    # Hanya ambil pesan dari AI yang memiliki isi teks
                    if msg.type == "ai" and msg.content and msg.content.strip():
                        # --- PERBAIKAN: FILTER "INNER MONOLOGUE" ---
                        # Jika pesan AI ini dibarengi dengan pemanggilan tool, 
                        # itu berarti teksnya cuma "pengantar" sebelum tool dieksekusi.
                        # Kita abaikan agar UI tidak menampilkan teks double/gumaman AI.
                        if not getattr(msg, "tool_calls", []):
                            kumpulan_teks_ai.append(msg.content.strip())
                
                # Jika ada teks yang terkumpul, gabungkan dengan pembatas
                if kumpulan_teks_ai:
                    jawaban_final = "\n\n---\n\n".join(kumpulan_teks_ai)

        return {
            "status": "selesai",
            "pesan": jawaban_final,
            "download_info": download_info
        }
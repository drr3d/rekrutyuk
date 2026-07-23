from typing import List, Any
from .agent_nodes import AgentState

# ==========================================
# --- 3. DEFINISI ROUTER (PENGATUR JALUR) ---
# ==========================================
class DecisionRouter:
    """
    Router Kelas untuk graf AI. Menggunakan prinsip modularitas agar
    mekanisme utama dapat dengan mudah dimodifikasi atau diperluas.
    """
    def __init__(self, sensitive_tools: List[Any], logger=None):
        self._sensitive_tools = sensitive_tools
        self._logger = logger or print

    def _is_sensitive(self, tool_name: str) -> bool:
        """Metode khusus untuk mengecek sensitivitas tool."""
        return any(tool_name == getattr(t, 'name', t) for t in self._sensitive_tools)

    def _tentukan_rute_tool(self, pesan_terakhir) -> str:
        """
        MEKANISME UTAMA: Di sinilah otak penentuan cabang berada.
        Jika nanti ada percabangan baru (misal: otorisasi), ubah di sini.
        """
        if hasattr(pesan_terakhir, "tool_calls") and pesan_terakhir.tool_calls:
            nama_tool = pesan_terakhir.tool_calls[0]['name']
            
            if self._is_sensitive(nama_tool):
                self._logger(f"[Log Router] AI memutuskan memakai Tool SENSITIF -> {nama_tool}")
                return "lanjut_ke_sensitive"
            else:
                self._logger(f"[Log Router] AI memutuskan memakai Tool AMAN -> {nama_tool}")
                return "lanjut_ke_safe"
                
        self._logger("[Log Router] Draf selesai. Langsung kirim jawaban ke User!")
        return "langsung_selesai"

    def __call__(self, state: AgentState) -> str:
        """
        PINTU MASUK (Entry Point): LangGraph hanya memanggil ini.
        Tugasnya hanya mengekstrak state dan mendelegasikan tugas ke mekanisme utama.
        """
        if not state.get("messages"):
            return "langsung_selesai"

        pesan_terakhir = state["messages"][-1]
        
        # Mendelegasikan logika ke fungsi terpisah sesuai ide Anda
        return self._tentukan_rute_tool(pesan_terakhir)
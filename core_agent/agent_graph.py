import json
import streamlit as st
import sqlite3

from typing import Dict, Any, Type, Callable
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
#from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver

from .agent_nodes import (
    AgentState,
    panggil_otak_llm,
    eksekutor_safe,
    eksekutor_sensitive,
    router_keputusan
)
from .agent_tools import sqlite_db_path

# ==========================================
# 1. UI REGISTRY (Agar Kontributor Bisa Menambah Custom View Tool)
# ==========================================
class ToolFormatterRegistry:
    """Registry untuk memformat tampilan Tool di UI secara dinamis (Plugin System)."""
    _registry: Dict[str, Callable[[Dict[str, Any]], str]] = {}

    @classmethod
    def register(cls, tool_name: str):
        """Decorator untuk mendaftarkan parser tampilan tool baru."""
        def decorator(func: Callable[[Dict[str, Any]], str]):
            cls._registry[tool_name] = func
            return func
        return decorator

    @classmethod
    def format(cls, tool_name: str, args: Dict[str, Any]) -> str:
        """Format argumen tool berdasarkan formatter yang terdaftar."""
        if tool_name in cls._registry:
            return cls._registry[tool_name](args)
        # Default fallback formatter
        return f"   Argumen: `{json.dumps(args, ensure_ascii=False)}`"


# --- Contoh Kontributor Mendaftarkan Formatter khusus Lowongan Bulk ---
@ToolFormatterRegistry.register("posting_lowongan_bulk")
def format_bulk_lowongan(args: Dict[str, Any]) -> str:
    data_lowongan = args.get("daftar_lowongan", [])
    sub_detail = []
    for idx, lw in enumerate(data_lowongan, 1):
        sub_detail.append(
            f"  {idx}. **{lw.get('posisi')}**\n"
            f"     • Periode: {lw.get('tanggal_mulai')} s/d {lw.get('tanggal_selesai')}\n"
            f"     • Keyword: {lw.get('keyword_wajib')}"
        )
    return f"Menyimpan {len(data_lowongan)} Lowongan Sekaligus:\n" + "\n".join(sub_detail)


# ==========================================
# 2. CORE AGENT ENGINE
# ==========================================
class HRAgentEngine:
    """Core Engine yang merakit dan mengeksekusi Graph LangGraph."""
    def __init__(self, state_schema: Type = AgentState):
        self.state_schema = state_schema
        
        # === OPSI A: MENGAKTIFKAN PERSISTENT CHECKPOINTER VIA SQLITE ===
        # Gunakan check_same_thread=False agar tidak bentrok saat diakses multi-thread oleh Streamlit
        self.db_conn = sqlite3.connect(sqlite_db_path, check_same_thread=False)
        self.memory = SqliteSaver(self.db_conn)
        # ===============================================================
        
        self.workflow = StateGraph(self.state_schema)
        self._build_graph()
        self.executor = self.workflow.compile(
            checkpointer=self.memory,
            interrupt_before=["node_sensitive"]
        )

    def _build_graph(self):
        """Membangun topologi graf secara internal."""
        # 1. Daftarkan Nodes
        self.workflow.add_node("node_ai", panggil_otak_llm)
        self.workflow.add_node("node_safe", eksekutor_safe)
        self.workflow.add_node("node_sensitive", eksekutor_sensitive)

        # 2. Rangkai Alur Edges
        self.workflow.add_edge(START, "node_ai")
        self.workflow.add_conditional_edges(
            "node_ai", 
            router_keputusan, 
            {
                "lanjut_ke_safe": "node_safe",
                "lanjut_ke_sensitive": "node_sensitive",
                "langsung_selesai": END
            }
        )
        self.workflow.add_edge("node_safe", "node_ai")
        self.workflow.add_edge("node_sensitive", "node_ai")

    def run(self, user_input: str = None, thread_id: str = "hr_session_001", is_approval: bool = False, user_role: str = "Staff") -> Dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id, "user_role": user_role}}
        current_state = self.executor.get_state(config)
        
        # Jika graf sedang PAUSED (menunggu persetujuan tool sensitif)
        if current_state.next and "node_sensitive" in current_state.next:
            if is_approval:
                self.executor.invoke(None, config=config)
            else:
                # HR MEREVISI: Hancurkan rencana tool_call AI sebelumnya agar tidak halusinasi
                last_message = current_state.values["messages"][-1]
                inputs_to_send = []
                
                if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                    for tc in last_message.tool_calls:
                        inputs_to_send.append(
                            ToolMessage(
                                tool_call_id=tc["id"], 
                                name=tc["name"], 
                                content="SYSTEM ABORT: User membatalkan aksi ini dan memberikan instruksi baru. Abaikan tool ini."
                            )
                        )
                
                # Masukkan chat revisi dari HR
                inputs_to_send.append(HumanMessage(content=user_input))
                self.executor.invoke({"messages": inputs_to_send}, config=config)
                
        else:
            if not is_approval and user_input:
                self.executor.invoke({"messages": [HumanMessage(content=user_input)]}, config=config)
            
        return self.executor.get_state(config)
# ==========================================
# 3. UI ADAPTER (Penterjemah State Mentah Graf -> Kebutuhan Frontend)
# ==========================================
class StreamlitAgentAdapter:
    """Adapter untuk menerjemahkan State Graf ke format UI Streamlit."""
    
    @staticmethod
    def process_state_to_ui(state) -> Dict[str, Any]:
        # Skenario 1: Butuh Persetujuan (HITL)
        if state.next and "node_sensitive" in state.next:
            pesan_terakhir = state.values["messages"][-1]
            tool_calls = getattr(pesan_terakhir, "tool_calls", [])
            
            if tool_calls:
                detail_pesan = []
                for idx, tc in enumerate(tool_calls, 1):
                    nama_tool = tc["name"]
                    argumen_tool = tc["args"]
                    
                    # Memanggil Formatter dinamis dari Registry
                    formatted_arg = ToolFormatterRegistry.format(nama_tool, argumen_tool)
                    detail_pesan.append(f"{idx}. Tool: **{nama_tool}**\n{formatted_arg}")
                
                pesan_gabungan = (
                    "### ⚠️ KONFIRMASI TINDAKAN SENSITIF\n"
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
            for msg in reversed(state.values["messages"]):
                if msg.type == "ai" and not getattr(msg, "tool_calls", None):
                    if msg.content and msg.content.strip():
                        jawaban_final = msg.content
                        break

        return {
            "status": "selesai",
            "pesan": jawaban_final,
            "download_info": download_info
        }


# ==========================================
# 4. IMPLEMENTASI SEHAT (Fungsi Bersih yang Dipanggil Frontend)
# ==========================================
# Gunakan cache agar Engine dan MemorySaver TIDAK hancur saat UI me-reload
@st.cache_resource
def get_agent_engine():
    return HRAgentEngine()

engine = get_agent_engine()

def proses_chat_agent(user_input: str = None, thread_id: str = "hr_session_001", is_approval: bool = False, user_role: str = "Staff") -> dict:
    try:
        # 1. Jalankan core engine (Memori kini akan abadi selama server menyala)
        state_terbaru = engine.run(user_input, thread_id, is_approval, user_role)
        # 2. Terjemahkan hasilnya menggunakan Adapter untuk UI Streamlit
        return StreamlitAgentAdapter.process_state_to_ui(state_terbaru)
    except Exception as e:
        return {"status": "error", "pesan": str(e)}
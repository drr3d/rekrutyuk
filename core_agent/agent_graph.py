import os
import importlib
import json
import streamlit as st
import sqlite3

from typing import Dict, Any, List, Type, Callable
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite import SqliteSaver

from .agent_nodes import (
    AgentState
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
class AgenticEngine:
    """Core Engine yang merakit dan mengeksekusi Graph LangGraph."""
    def __init__(self, state_schema: Type = AgentState, graph_config: List[Dict[str, Any]] = None):
        self.state_schema = state_schema
        self.db_conn = sqlite3.connect(sqlite_db_path, check_same_thread=False)
        self.memory = SqliteSaver(self.db_conn)
        
        self.workflow = StateGraph(self.state_schema)
        
        # Proteksi mutlak: Tolak inisialisasi jika config kosong
        if graph_config is None:
            raise ValueError("Gagal memuat arsitektur AI! Pastikan file graph_config.py valid dan terbaca oleh Dynamic Loader.")
            
        self.graph_config = graph_config
        
        # Penampung daftar node mana saja yang butuh Persetujuan (HITL)
        self.interrupt_before_nodes = []
        self.interrupt_after_nodes = []
        
        # 1. Rakit Topologi Graf
        self._build_graph()
        
        # 2. Compile Graf dengan Interrupt Dynamic dari Konfigurasi
        self.executor = self.workflow.compile(
            checkpointer=self.memory,
            interrupt_before=self.interrupt_before_nodes,
            interrupt_after=self.interrupt_after_nodes
        )

    def _build_graph(self):
        """Membangun topologi graf dengan dukungan penuh seluruh fitur LangGraph."""
        for item in self.graph_config:
            item_type = item.get("type")

            # --- A. PENDAFTARAN NODE (Bisa Fungsi Biasa ATAU Subgraph) ---
            if item_type == "node":
                # item["func"] bisa berupa fungsi biasa ATAU Compiled StateGraph (Subgraph)
                self.workflow.add_node(item["name"], item["func"])
                
                # Cek apakah node ini butuh Interrupt (Human-in-the-Loop)
                if item.get("interrupt_before", False):
                    self.interrupt_before_nodes.append(item["name"])
                if item.get("interrupt_after", False):
                    self.interrupt_after_nodes.append(item["name"])

            # --- B. EDGES BERSAMBUNG (Bisa Single target atau Parallel/Fan-Out) ---
            elif item_type == "edge":
                # item["end"] bisa berupa "node_b" ATAU list ["node_b", "node_c"] untuk PARALEL
                self.workflow.add_edge(item["start"], item["end"])

            # --- C. CONDITIONAL EDGES ---
            elif item_type == "conditional_edge":
                kwargs = {}
                if "path_map" in item:
                    kwargs["path_map"] = item["path_map"]
                if "then" in item:
                    kwargs["then"] = item["then"]
                
                self.workflow.add_conditional_edges(
                    item["source"], 
                    item["router"], 
                    **kwargs
                )

            # --- D. BACKWARDS COMPATIBILITY ---
            elif item_type == "entry_point":
                self.workflow.set_entry_point(item["node"])
            elif item_type == "finish_point":
                self.workflow.set_finish_point(item["node"])

            else:
                print(f"⚠️ PERINGATAN: Tipe konfigurasi '{item_type}' tidak dikenali.")

    def run(self, user_input: str = None, thread_id: str = "default_thread", is_approval: bool = False, user_role: str = "Staff") -> Dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id, "user_role": user_role}}
        current_state = self.executor.get_state(config)
        
        # PERUBAHAN DI SINI: Deteksi Pause secara dinamis tanpa hardcode nama node
        if current_state.next:
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

#@st.cache_resource
#def get_agent_engine():
#    return AgenticEngine()

@st.cache_resource
def get_agent_engine():
    """
    Memuat engine dan mencari config graf secara dinamis 
    dari folder 'agentgraph_config'.
    """
    
    # 1. Baca Environment Variable. 
    # Jika tidak diset, default-nya akan mengambil file 'default_graph' di dalam folder agentgraph_config
    config_name = os.getenv("ACTIVE_AGENT_CONFIG", "graph_config")
    
    konfigurasi_aktif = None
    
    try:
        # 2. Path dinamis menunjuk ke folder 'agentgraph_config'
        # Format import module path: .agentgraph_config.<nama_file>
        module_path = f".agentgraph_config.{config_name}"
        
        # 3. Import modul secara dinamis
        modul = importlib.import_module(module_path, package=__package__)
        
        # 4. Ambil variabel skema graf di dalam file tersebut
        if hasattr(modul, "GRAPH_CONFIG"):
            konfigurasi_aktif = getattr(modul, "GRAPH_CONFIG")
        elif hasattr(modul, "DEFAULT_GRAPH_CONFIG"):
            konfigurasi_aktif = getattr(modul, "DEFAULT_GRAPH_CONFIG")
        else:
            raise AttributeError(f"File config '{config_name}.py' tidak memiliki variabel 'GRAPH_CONFIG' atau 'DEFAULT_GRAPH_CONFIG'.")
            
        print(f"✅ [Auto-Load] Berhasil memuat arsitektur graf dari: agentgraph_config/{config_name}.py")
        
    except ImportError as e:
        print(f"⚠️ [Error] Gagal memuat config '{config_name}' dari folder agentgraph_config: {e}")
    except Exception as e:
        print(f"⚠️ [Error] Kesalahan pada konfigurasi graf: {e}")

    # 5. Kembalikan instansiasi AgenticEngine dengan config terpilih
    return AgenticEngine(graph_config=konfigurasi_aktif)

engine = get_agent_engine()

def proses_chat_agent(user_input: str = None, thread_id: str = "hr_session_001", is_approval: bool = False, user_role: str = "Staff") -> dict:
    try:
        # 1. Jalankan core engine (Memori kini akan abadi selama server menyala)
        state_terbaru = engine.run(user_input, thread_id, is_approval, user_role)
        # 2. Terjemahkan hasilnya menggunakan Adapter untuk UI Streamlit
        return StreamlitAgentAdapter.process_state_to_ui(state_terbaru)
    except Exception as e:
        return {"status": "error", "pesan": str(e)}
import operator
from typing import Annotated, TypedDict

# Import LangChain & LangGraph components
from langchain_core.messages import SystemMessage
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

# Import dari file Anda yang lain
from .systemprompt_collection import system_prompt
from .agent_tools import (
    llm,
    tools,
    safe_tools,
    sensitive_tools
)

# ==========================================
# --- 1. ARSITEKTUR CUSTOM STATEGRAPH ---
# ==========================================
class AgentState(TypedDict):
    """
    Representasi memori sentral untuk AI Agent.
    - messages: Menyimpan riwayat obrolan (ditumpuk).
    - revision_count: Menghitung berapa kali AI sudah direvisi.
    """
    messages: Annotated[list, add_messages]
    revision_count: Annotated[int, operator.add]

def optimasi_konteks_langchain(messages):
    """
    Optimasi berbasis 'Sliding Window':
    Menjaga data tool tetap utuh untuk pertanyaan saat ini, 
    namun mengompres data tool dari masa lalu untuk menghemat VRAM.
    """
    from langchain_core.messages import ToolMessage
    
    cleaned_messages = []
    total_msgs = len(messages)
    
    # Batas Jendela Memori: Pertahankan isi penuh dari 8 pesan terakhir (sekitar 2-3 turn tanya jawab)
    BATAS_PESAN_AKTIF = 8 
    
    for idx, msg in enumerate(messages):
        # 1. System Prompt WAJIB aman
        if msg.type == "system":
            cleaned_messages.append(msg)
            continue
            
        # 2. Cek apakah ini pesan dari obrolan masa lalu
        is_pesan_lama = (total_msgs - idx) > BATAS_PESAN_AKTIF
        
        if msg.type == "tool":
            # Jika pesan tool sudah usang (di luar batas aktif) DAN isinya panjang, baru dikompres!
            if is_pesan_lama and len(msg.content) > 300:
                # Membuat obyek baru yang aman (bukan .copy() yang berbahaya)
                pesan_kompresi = ToolMessage(
                    content=f"[Log memori: Data teknis '{msg.name}' dikompresi karena percakapan telah berlalu. Jika butuh, panggil ulang tool-nya.]",
                    name=msg.name,
                    tool_call_id=msg.tool_call_id
                )
                cleaned_messages.append(pesan_kompresi)
            else:
                # Tool di percakapan SAAT INI (baik JSON maupun RAG) akan lolos 100% utuh!
                cleaned_messages.append(msg)
        else:
            # Pesan Human dan AI dibiarkan utuh agar obrolan tidak amnesia
            cleaned_messages.append(msg)
            
    return cleaned_messages

# ==========================================
# --- 2. DEFINISI NODE (KOMPONEN AI) ---
# ==========================================
def panggil_otak_llm(state: AgentState):
    """NODE 1: Mengevaluasi pesan dan memutuskan tindakan (menjawab atau memanggil tool)."""
    messages = state.get("messages", [])
    
    # Injeksi System Prompt di posisi paling awal jika belum ada
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_prompt)] + messages

    # Bind tools agar LLM tahu dia punya kemampuan tambahan
    llm_with_tools = llm.bind_tools(tools) 
    
    # [PERBAIKAN DI SINI]: Panggil fungsi optimasi untuk memangkas ToolMessage usang!
    messages_dioptimalkan = optimasi_konteks_langchain(messages)
    
    print("\n[Log Sistem] AI Utama sedang menganalisis input atau menyusun jawaban...")
    
    # [PERBAIKAN DI SINI]: Kirim `messages_dioptimalkan`, BUKAN `messages` mentah
    response = llm_with_tools.invoke(messages_dioptimalkan)
    
    print("\n--- [DAPUR AGENT: APA YANG DIPIKIRKAN LLM?] ---")
    print(f"Content: {response.content}") 
    print(f"Tool Calls: {response.tool_calls}") 
    print("----------------------------------------------\n")
    
    return {"messages": [response]}

# ==========================================
# --- 3. DEFINISI ROUTER (PENGATUR JALUR) ---
# ==========================================
def router_keputusan(state: AgentState) -> str:
    """
    Router AI Utama: Sangat sederhana dan anti-error.
    Jika AI butuh tool, arahkan ke tool. Jika tidak, langsung selesai (ke User).
    """
    pesan_terakhir = state["messages"][-1]
    
    # Cek apakah AI Utama memanggil fungsi/tools
    if pesan_terakhir.tool_calls:
        nama_tool = pesan_terakhir.tool_calls[0]['name']
        
        # Pengecekan tool sensitif (seperti kirim email/pesan)
        if any(nama_tool == t.name for t in sensitive_tools):
            print(f"[Log Sistem] AI memutuskan memakai Tool SENSITIF -> {nama_tool}")
            return "lanjut_ke_sensitive"
        else:
            print(f"[Log Sistem] AI memutuskan memakai Tool AMAN -> {nama_tool}")
            return "lanjut_ke_safe"
            
    # Jika tidak ada pemanggilan tool, berarti AI sudah selesai menyusun jawaban final
    print("[Log Sistem] Draf selesai. Langsung kirim jawaban ke User!")
    return "langsung_selesai"

# NODE 3 & 4: Tangan Eksekutor Tool
eksekutor_safe = ToolNode(safe_tools)
eksekutor_sensitive = ToolNode(sensitive_tools)
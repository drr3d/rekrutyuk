from langchain_core.tools import tool

class ToolRegistry:
    """Registry agar kontributor bisa inject tools dari luar tanpa merubah file ini."""
    safe_tools = []
    sensitive_tools = []

    @classmethod
    def register(cls, is_sensitive=False):
        def decorator(func):
            # Ubah fungsi python biasa menjadi Langchain @tool
            langchain_tool = tool(func)
            if is_sensitive:
                cls.sensitive_tools.append(langchain_tool)
            else:
                cls.safe_tools.append(langchain_tool)
            return langchain_tool
        return decorator
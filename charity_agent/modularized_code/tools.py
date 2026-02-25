import json
import requests
from typing import Dict
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient

def build_node_stats_tool():
    BASE_URL = "http://localhost:3000"
    CANONICAL_TOOLS = [
        "charity_donor_count", "charity_impactlife", "charity_donor_amount",
        "charity_total_donation", "charity_items_category",
        "charity_product_price_description", "charity_blogs",
        "charity_address", "charity_country_availability", "charity_contact_info",
    ]

    def call_node_stats(tool_name: str) -> str:
        tool_name = (tool_name or "").strip()
        if not tool_name:
            return json.dumps({"ok": False, "error": "Tool name is required.", "valid_tools": CANONICAL_TOOLS})
        if tool_name not in CANONICAL_TOOLS:
            return json.dumps({"ok": False, "error": "Invalid tool name", "provided": tool_name, "valid_tools": CANONICAL_TOOLS})
        try:
            r = requests.get(f"{BASE_URL}/api/stats", params={"q": tool_name}, timeout=10)
            r.raise_for_status()
            return json.dumps(r.json())
        except requests.RequestException as e:
            return json.dumps({"ok": False, "error": str(e), "tool": tool_name})

    class CharityStatsInput(BaseModel):
        tool_name: str = Field(..., description="Exact one tool name from the CANONICAL_TOOLS list above")

    return StructuredTool.from_function(
        func=call_node_stats,
        name="get_charity_stats",
        description=(
            "Fetch internal charity data from Node-js server.\n"
            "IMPORTANT: The ONLY callable tool is 'get_charity_stats'.\n"
            "The following are NOT tools; they are allowed VALUES for the argument 'tool_name':\n"
            + "\n".join([f"- {t}" for t in CANONICAL_TOOLS])
        ),
        args_schema=CharityStatsInput,
    )

async def setup_tools():
    local_tools = [build_node_stats_tool(), PythonREPLTool()]
    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    mcp_tools = await client.get_tools()
    return [*local_tools, *mcp_tools]

def build_tool_context(tools_by_name: dict):
    blocks = []
    for tool in tools_by_name.values():
        name = tool.name
        description = (getattr(tool, "description", "") or "No description.").strip()
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            arg_lines = []
            for k, v in fields.items():
                req = getattr(v, "is_required", lambda: False)()
                arg_lines.append(f"- {k} ({'required' if req else 'optional'})")
            args_text = "\n".join(arg_lines) if arg_lines else "No parameters"
        else:
            args_text = "- input (required string). For Python_REPL, this must be python code."
        blocks.append(f"""
{name}
Description:
{description}

Arguments:
{args_text}
""")
    return "\n\n".join(blocks)
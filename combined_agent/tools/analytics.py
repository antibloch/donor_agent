import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from .tool_helpers import _ok, _fail, _get



CHARITY_BASE_URL = "http://localhost:3030"
DEFAULT_AUTH_TOKEN = "charity-demo-token-2026"





def build_node_stats_tool(base_url: str = CHARITY_BASE_URL) -> StructuredTool:
    CANONICAL_TOOLS = [
        "charity_donor_count", "charity_impactlife", "charity_donor_amount",
        "charity_total_donation", "charity_items_category",
        "charity_product_price_description", "charity_blogs",
        "charity_address", "charity_country_availability", "charity_contact_info",
    ]

    def call_node_stats(tool_name: str) -> str:
        tool_name = (tool_name or "").strip()
        if not tool_name:
            return _fail("Tool name is required.", valid_tools=CANONICAL_TOOLS)
        if tool_name not in CANONICAL_TOOLS:
            return _fail("Invalid tool name.", provided=tool_name, valid_tools=CANONICAL_TOOLS)

        try:
            out = _get(f"{base_url}/api/stats", params={"q": tool_name})
            # /api/stats returns {ok: true/false, tool, query, data, ...}
            return _ok(out["json"], endpoint="/api/stats", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), tool=tool_name, endpoint="/api/stats")

    class CharityStatsInput(BaseModel):
        tool_name: str = Field(..., description="Exact tool name from the allowed list in the tool description")

    return StructuredTool.from_function(
        func=call_node_stats,
        name="get_charity_stats",
        description=(
            "Fetch internal charity data from Node-js server via /api/stats.\n"
            "Argument tool_name must be one of:\n" + "\n".join([f"- {t}" for t in CANONICAL_TOOLS])
        ),
        args_schema=CharityStatsInput,
    )



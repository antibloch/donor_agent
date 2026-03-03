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



#=======================Adding Meta Data for Tool Guidance=======================
metadata_analytics = {
    "Python_REPL": {
        "domain": "analytics",
        "type": "compute",
        "when_to_use": (
            "- If the user asks for ANY numeric aggregation (e.g: median, mean, average, avg, std, min, max, sum, total)"
            "- User asks about entities/items in plural/group form and has not explicitly disabled analysis"
            "- User asks for insights/recommendations/comparison/ranking/trends"
            
        ),
        "do_not_use": "Do not use for external web/page fetches, or for performing transactions",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "",
        "hint": (
                    "- Python_REPL must NEVER have empty args.\n"
                    "- Python_REPL argument format: {{ \"input\": \"<python code that performs analysis, whose final line of code is ONLY print statement that prints the final numeric result>\" }}"
                    "- ALWAYS start with proper imports: `import statistics`"
                    "- Use the CORRECT statistical function, e.g:"
                    "        • median → statistics.median(your_list)"
                    "        • mean   → statistics.mean(your_list)"
                    "        • sum, min, max, etc. → built-in functions"
                    "- The code must END with ONE clean `print(…)` statement that outputs ONLY the final numeric result (no lists, no extra text)."
                    "- Avoid leading indentation on lines unless inside a block (IndentationError risk)."
                )
    },
    "get_charity_stats": {
        "domain": "charity",
        "type": "stats",
        "when_to_use": "When user asks for donor counts, impact metrics, rankings, blogs, products, addresses, or any numeric summary per charity",
        "do_not_use": "Never use for wallet, bids, payments, or auctions -- those belong to transaction/auction tools",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=charity_donor_count",
        "hint": "none"
    },
    "fetch_url": {
        "domain": "web",
        "type": "action",
        "when_to_use": "When a specific URL is already known and you need page content.",
        "do_not_use": "Do not use when you need discovery/search over unknown URLs.",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=fetch_url",
        "hint": "none"
    },
    "fetch_urls": {
        "domain": "web",
        "type": "paginate",
        "when_to_use": "When multiple known URLs should be fetched in one operation.",
        "do_not_use": "Do not use for keyword search/discovery over the open web.",
        "supports_pagination": True,
        "requires_auth": False,
        "example_usage": "tool_name=fetch_urls",
        "hint": "none"
    },
}
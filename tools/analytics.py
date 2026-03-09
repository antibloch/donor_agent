import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from .tool_helpers import _ok, _fail, _get
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient


# From your message / deployment:
CHARITY_BASE_URL = "https://giverr-api.verior.co"
DEFAULT_AI_API_KEY = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"

# Postman collection base path:
# GET /api/v3/agent/charities/discovery?page=&limit=&search=
# GET /api/v3/agent/charities/{charityId}/detail
AGENT_BASE_PATH = "/api/v3/agent"


def _headers(api_key: str) -> dict:
    api_key = (api_key or "").strip()
    if not api_key:
        # Keep the error payload consistent with your other tools
        raise ValueError("X-API-KEY is required (api_key).")
    return {"X-API-KEY": api_key}


def build_charity_discovery_tool(
    base_url: str = CHARITY_BASE_URL,
    api_key: str = DEFAULT_AI_API_KEY,
) -> StructuredTool:
    """
    Coarse-grained endpoint:
      GET {baseUrl}/api/v3/agent/charities/discovery?page=1&limit=1000&search=...
    """

    def discover_charities(page: int = 1, limit: int = 1000) -> str:
        try:
            page_i = int(page)
            limit_i = int(limit)
            if page_i < 1:
                return _fail("page must be >= 1", provided=page)
            if limit_i < 1 or limit_i > 2000:
                return _fail("limit must be between 1 and 2000", provided=limit)

            params = {"page": page_i, "limit": limit_i}

            url = f"{base_url}{AGENT_BASE_PATH}/charities/discovery"
            # Using requests directly so headers are guaranteed to be sent
            resp = requests.get(url, params=params, headers=_headers(api_key), timeout=30)
            # Normalize success/error into your tool envelope
            if resp.status_code >= 400:
                return _fail(
                    f"HTTP {resp.status_code}",
                    endpoint="/api/v3/agent/charities/discovery",
                    http_status=resp.status_code,
                    response_text=resp.text[:2000],
                    params=params,
                )
            return _ok(
                resp.json(),
                endpoint="/api/v3/agent/charities/discovery",
                http_status=resp.status_code,
                params=params,
            )
        except ValueError as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/discovery")
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/discovery")

    class CharityDiscoveryInput(BaseModel):
        page: int = Field(1, description="1-based page index (default 1).")
        limit: int = Field(1000, description="Page size (default 1000, max 2000).")

    return StructuredTool.from_function(
        func=discover_charities,
        name="discover_charities",
        description = """
        PURPOSE:
        Discover charities by name or search text and return candidate charity records.

        MUST_CALL_FIRST:
        - for vague, fuzzy, partial, or misspelled charity-name requests

        DEFAULT_CHAIN:
        - discover_charities -> charity_details -> fetch_url

        WHEN TO USE:
        - user asks about a charity by name but exact identity is uncertain
        - user wants listing, ranking, or comparison
        - charity_id is not yet known

        RETURNS:
        - candidate charities including _id and name

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - output of this tool should supply the charity_id for charity_details
        - if planning before execution, planner should use placeholder:
        "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"

        DO NOT STOP HERE WHEN:
        - user asks for general information about a specific charity
        - deeper charity details are needed
        """,
        args_schema=CharityDiscoveryInput,
    )


def build_charity_detail_tool(
    base_url: str = CHARITY_BASE_URL,
    api_key: str = DEFAULT_AI_API_KEY,
) -> StructuredTool:
    """
    Fine-grained endpoint:
      GET {baseUrl}/api/v3/agent/charities/{charityId}/detail
    """

    def charity_details(charity_id: str) -> str:
        charity_id = (charity_id or "").strip()
        if not charity_id:
            return _fail("charity_id is required.", endpoint="/api/v3/agent/charities/{charityId}/detail")

        try:
            url = f"{base_url}{AGENT_BASE_PATH}/charities/{charity_id}/detail"
            resp = requests.get(url, headers=_headers(api_key), timeout=30)
            if resp.status_code >= 400:
                return _fail(
                    f"HTTP {resp.status_code}",
                    endpoint="/api/v3/agent/charities/{charityId}/detail",
                    http_status=resp.status_code,
                    charity_id=charity_id,
                    response_text=resp.text[:2000],
                )
            return _ok(
                resp.json(),
                endpoint="/api/v3/agent/charities/{charityId}/detail",
                http_status=resp.status_code,
                charity_id=charity_id,
            )
        except ValueError as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/{charityId}/detail", charity_id=charity_id)
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v3/agent/charities/{charityId}/detail", charity_id=charity_id)

    class CharityDetailInput(BaseModel):
        charity_id: str = Field(..., description="MongoDB ObjectId (_id) of the charity to fetch detail for.")

    return StructuredTool.from_function(
        func=charity_details,
        name="charity_details",
        description = """
        PURPOSE:
        Retrieve full details for one charity using charity_id.

        MUST_FOLLOW:
        - discover_charities for vague or fuzzy charity-name queries

        DEFAULT_CHAIN:
        - discover_charities -> charity_details -> fetch_url

        REQUIRES:
        - charity_id

        WHEN charity_id IS NOT YET AVAILABLE AT PLANNING TIME:
        - planner must still include this tool in the chain
        - use placeholder:
        "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"

        RETURNS:
        - detailed charity fields
        - website/contact information if available

        CHAIN_OUTPUT_FOR_NEXT_TOOL:
        - output of this tool should supply the website URL for fetch_url
        - if planning before execution, planner should use placeholder:
        "<WEBSITE_URL_FROM_CHARITY_DETAILS>"

        DO NOT USE ALONE WHEN:
        - the charity was not yet resolved from a fuzzy name
        """,
        args_schema=CharityDetailInput,
    )




def Python_tool():
    python_tool = PythonREPLTool()
    python_tool.name = "Python_REPL"
    python_tool.description = """
    PURPOSE:
    Run Python code to compute, transform, aggregate, sort, filter, compare, or summarize structured data that was already obtained from other tools.

    MUST_NOT_CALL_FIRST:
    - Never use this tool as the first tool for a charity-information request.
    - Never use this tool to search for charities, identify a charity, fetch charity details, or fetch website content.

    REQUIRED_PREDECESSOR:
    - This tool must use data already returned by discover_charities and/or charity_details.
    - It may also use data returned by fetch_url only if the website text has already been fetched and needs structured processing.

    WHEN TO USE:
    - when the user asks for calculations
    - when the user asks for mean, median, max, min, count, ranking, sorting, grouping, filtering, percentages, or comparisons
    - when multiple charity records from discover_charities need numeric/statistical analysis
    - when charity_details output needs structured extraction or computation
    - when tool output is too large and needs deterministic post-processing

    WHEN NOT TO USE:
    - when the needed information can be answered directly from discover_charities or charity_details without computation
    - when no prior tool output exists yet
    - when the task is entity resolution, search, lookup, or website retrieval
    - when the model can answer directly without code execution

    INPUT SOURCE POLICY:
    - Prefer discover_charities output for list-level analytics across many charities
    - Prefer charity_details output for deep analysis of one resolved charity
    - Prefer fetch_url output only after the webpage has already been fetched and only if code-based parsing/counting is actually useful
    - Do not fabricate data; only operate on prior tool outputs from chat history

    DEFAULT DEPENDENCY CHAINS:
    - discover_charities -> Python_REPL
    - discover_charities -> charity_details -> Python_REPL
    - discover_charities -> charity_details -> fetch_url -> Python_REPL

    CHAIN POSITION:
    - post-processing tool
    - usually final tool in a chain, after retrieval tools have produced data

    EXAMPLES:
    - 'Which charity has the highest donor count?' -> discover_charities -> Python_REPL
    - 'What are the mean and median donor counts across charities?' -> discover_charities -> Python_REPL
    - 'Compare donation fields for this charity and summarize totals' -> charity_details -> Python_REPL
    - 'Count how many times education is mentioned on the charity website' -> charity_details -> fetch_url -> Python_REPL
    """


    return python_tool


async def Crawler_tool():
    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    mcp_tools = await client.get_tools()
    crawler_tool = []
    for tool in mcp_tools:
        if tool.name in ['fetch_url']:
            description = """
                        PURPOSE:
                        Fetch webpage text/content from a known URL.

                        MUST_FOLLOW:
                        - charity_details when a website exists and the user asked for general info or website-enriched info

                        DEFAULT_CHAIN:
                        - discover_charities -> charity_details -> fetch_url

                        REQUIRES:
                        - url

                        WHEN url IS NOT YET AVAILABLE AT PLANNING TIME:
                        - planner must still include this tool if it is part of the required chain
                        - use placeholder:
                        "<WEBSITE_URL_FROM_CHARITY_DETAILS>"

                        USE WHEN:
                        - website content can enrich or complete the final answer

                        DO NOT USE:
                        - as a search tool
                        - before charity website is known or expected from charity_details
                        """
            setattr(tool, 'description', description)
            crawler_tool.append(tool)

    return crawler_tool




#=======================Adding Meta Data for Tool Guidance=======================
metadata_analytics = {
    "discover_charities": {
        "domain": "charity",
        "type": "discovery",
        "when_to_use": (
            "- When user asks to list available charities\n"
            "- When user asks to search charities by name/registration keyword\n"
            "- When user asks for comparisons/rankings across charities (e.g., highest donor count)\n"
            "- When you need a charity_id (_id) to fetch detailed information\n"
            "- When you need lightweight fields only: name, uniqueDonorCount, verification/active flags, location\n"
        ),
        "do_not_use": (
            "Do not use for per-charity deep details (products, blogs, address/contact, donation breakdown). "
            "Use charity_donation_stats_detail for that."
        ),
        "supports_pagination": True,
        "pagination_hints": (
            "- Response includes result.data.pagination.hasMore\n"
            "- If hasMore=true and the user needs a GLOBAL max/min/ranking across ALL charities, "
            "fetch additional pages until hasMore=false (or until you have enough data).\n"
            "- Use limit as high as allowed to reduce calls (e.g., 500-1000) if you need global ranking."
        ),
        "requires_auth": True,
        "auth_hints": (
            "- Requires X-API-KEY header\n"
            "- Implemented internally in the tool (agent does NOT pass the key as an argument)"
        ),
        "args": {
            "page": "int (default=1). 1-based page index.",
            "limit": "int (default=1000). Page size. Keep within server limits.",
            "search": "str (default=''). Optional filter by name/registration text.",
        },
        "output_schema": (
            "ok: bool\n"
            "result.success: bool\n"
            "result.data.items: list[{\n"
            "  _id: str,\n"
            "  name: str,\n"
            "  uniqueDonorCount: number,\n"
            "  isVerified: bool,\n"
            "  isActive: bool,\n"
            "  countryCode: str,\n"
            "  city: str\n"
            "}]\n"
            "result.data.pagination: { page:int, limit:int, total:int, hasMore:bool }\n"
            "meta: { endpoint:str, http_status:int, params:{...} }\n"
        ),
        "example_usage": (
            "page=1, limit=50, search='Al'\n"
            "Then read: result.data.items and result.data.pagination.hasMore"
        ),
        "hint": (
            "- For 'highest donor count' or 'top charities', sort items by uniqueDonorCount.\n"
            "- If hasMore=true, ranking across ALL charities may require fetching remaining pages.\n"
            "- Use this tool first in a 2-step flow, then call charity_donation_stats_detail with an _id."
        ),
    },

    "charity_details": {
        "domain": "charity",
        "type": "detail",
        "when_to_use": (
            "- When user asks for details of ONE charity (by name or by id)\n"
            "- When user asks for products, product categories, or product donation totals\n"
            "- When user asks for blogs/posts of a charity\n"
            "- When user asks for address/contact information\n"
            "- When user asks for donationAmount, impactLife, or other per-charity stats\n"
        ),
        "do_not_use": (
            "Do not use for listing or ranking across many charities. "
            "Use charity_discovery_list first to find/filter/rank and obtain charity_id."
        ),
        "supports_pagination": False,
        "requires_auth": True,
        "auth_hints": (
            "- Requires X-API-KEY header\n"
            "- Implemented internally in the tool (agent does NOT pass the key as an argument)"
        ),
        "args": {
            "charity_id": "str (required). Use the _id returned by charity_discovery_list.",
        },
        "output_schema": (
            "ok: bool\n"
            "result.success: bool\n"
            "result.data: {\n"
            "  impactLife: bool,\n"
            "  donationAmount: number,\n"
            "  totalDonationByProduct: number,\n"
            "  productCategories: list[str],\n"
            "  products: list[{\n"
            "    productName: str,\n"
            "    pricePerUnit: number,\n"
            "    description: str,\n"
            "    category: str,\n"
            "    totalDonated: number,\n"
            "    isActive: bool,\n"
            "    status: str\n"
            "  }],\n"
            "  blogs: list[{ title:str, description:str, file:str, hashtags:list[str] }],\n"
            "  address: { street:str, city:str, state:str, country:str, countryCode:str, postalCode:str },\n"
            "  contact: { email:str, phone:str, website:str }\n"
            "}\n"
            "meta: { endpoint:str, http_status:int, charity_id:str }\n"
        ),
        "example_usage": "charity_id='6957c567b7df149a6c552513'",
        "hint": (
            "- Typical flow: call charity_discovery_list → pick charity _id → call this tool.\n"
            "- If the user provides only a name, first search via charity_discovery_list to find matching _id.\n"
            "- Prefer summarizing: donationAmount, key categories, top 3 products, and contact/address when answering."
        ),
    },
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

if __name__ == "__main__":
    import json

    print("\n==============================")
    print("Testing charity tools")
    print("==============================\n")

    discovery_tool = build_charity_discovery_tool()
    detail_tool = build_charity_detail_tool()

    # -------------------------------------------------
    # Test 1: Discovery Endpoint (Coarse-grained)
    # -------------------------------------------------
    print("TEST 1: charity_discovery_list\n")

    discovery_result = discovery_tool.invoke({
        "page": 1,
        "limit": 7,
        "search": ""
    })

    print("Discovery Output:\n")
    print(json.dumps(discovery_result, indent=2) if isinstance(discovery_result, dict) else discovery_result)

    charity_id = None

    # Try extracting a charity_id for next test
    try:
        parsed = discovery_result
        if isinstance(discovery_result, str):
            parsed = json.loads(discovery_result)

        items = (
            parsed.get("result", {})
            .get("data", {})
            .get("items", [])
        )

        if items:
            charity_id = items[0].get("_id")
    except Exception:
        pass

    # -------------------------------------------------
    # Test 2: Detail Endpoint (Fine-grained)
    # -------------------------------------------------
    if charity_id:
        print("\nTEST 2: charity_donation_stats_detail\n")
        print(f"Using charity_id: {charity_id}\n")

        detail_result = detail_tool.invoke({
            "charity_id": charity_id
        })

        print("Detail Output:\n")
        print(json.dumps(detail_result, indent=2) if isinstance(detail_result, dict) else detail_result)

    else:
        print("\nSkipping detail test — no charity_id extracted from discovery response.\n")

    print("\n==============================")
    print("Tool Tests Finished")
    print("==============================\n")
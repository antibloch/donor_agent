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

        REQUIRES (Intuitive Schema):
        - no required arguments, but `page` and `limit` can be used for pagination

        REQUIRES (Detailed Schema):
            - page (int): page index starting from 1
            - limit (int): number of charities to return (recommended <= 1000)

        RETURNS (Intuitive Schema):
        - candidate charities including _id and name

        RETURNS (Detailed Schema):
            - result.data.items -> list of charities where each item contains:
              _id: unique charity identifier
              name: charity name
              uniqueDonorCount: number of unique donors
              isVerified: whether charity is verified
              isActive: whether charity is active
              countryCode: country code
              city: city of charity
            - result.data.pagination contains:
              page, limit, total, hasMore
            - If hasMore=true, additional pages exist and may need to be fetched to compute global rankings (e.g., highest donor count).
        

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

        REQUIRES (Intuitive Schema):
        - charity_id

        REQUIRES (Detailed Schema):
        - charity_id (str): the unique charity identifier obtained from discover_charities

        WHEN charity_id IS NOT YET AVAILABLE AT PLANNING TIME:
        - planner must still include this tool in the chain
        - use placeholder:
        "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"

        RETURNS (Intuitive Schema):
        - detailed charity fields
        - website/contact information if available

        RETURNS (Detailed Schema):
        - result.data contains:
            impactLife (bool): whether the charity supports impact-life donations
            donationAmount (number): total donation amount received
            totalDonationByProduct (number): donation amount linked to products
            productCategories (list[str]): categories of products offered
            products (list): each product includes:\n"
            productName, pricePerUnit, description, category,totalDonated, isActive, status
            blogs (list): blog posts with title, description, hashtags, and media
            address: charity location (street, city, state, country, postalCode)
            contact: charity contact information (email, phone, website)

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
    Leverages pandas, numpy, and scipy for statistical analysis, optimization, and data transformation.

    MUST_NOT_CALL_FIRST:
    - Never use this tool as the first tool for a charity-information request.
    - Never use this tool to search for charities, identify a charity, fetch charity details, or fetch website content.

    REQUIRED_PREDECESSOR:
    - This tool must use data already returned by discover_charities and/or charity_details.
    - It may also use data returned by get_transaction_history, list_charity_products, list_charity_grants, list_charity_active_campaigns.
    - It may also use data returned by get_active_auctions, get_my_bid_history, or fetch_url only after data has been fetched.

    LIBRARIES AVAILABLE:
    - pandas: DataFrame manipulation for multi-charity analysis, filtering, grouping, aggregation
    - numpy: Array operations for numerical computations
    - scipy.stats: Statistical distributions, hypothesis testing, correlations
    - statistics: Built-in module for mean, median, stdev on simple lists
    - import statistics; statistics.mean(list), statistics.median(list), statistics.stdev(list)

    WHEN TO USE:
    ✓ Aggregate queries: 'average donation across charities', 'total funds raised', 'mean/median/stdev of donor counts'
    ✓ Ranking & sorting: 'top 5 charities by donor count', 'sort grants by completion %', 'highest bid amounts'
    ✓ Filtering & grouping: 'charities in country X', 'active vs inactive charities', 'products by category'
    ✓ Comparative analysis: 'compare X charities side-by-side', 'which charity is most verified', 'auction bid patterns'
    ✓ Trend analysis: 'goal progress across campaigns', 'fundraising efficiency', 'product availability trends'
    ✓ Multi-step calculations: percentages, ratios, derived metrics (e.g., raised_amount / goal_amount)
    ✓ Recommendation / "best" / "analyse" queries: 'best charities for donation', 'which should I choose'
      → auto-detect ALL numeric columns from data, normalize each to 0-1, sum into total_score
      → MUST print full ranked table with all score components visible, NOT just a single-column sort
    ✓ Budget allocation / maximisation queries: 'donate maximum products with $X', 'best use of $X budget',
      'how many items can I donate', 'maximise count within budget', 'optimal strategy with $X'
      → ALWAYS use the LP TEMPLATE (linprog) even if the user does not say "linear programming" or "LP"

    DOMAIN-SPECIFIC USE CASES:
    ✓ DONOR ANALYSIS: transaction frequency, average donation amount, favorite causes (from transaction_history)
    ✓ CHARITY ANALYSIS: donor diversity, verification/activity status, product breadth, grant success rates
    ✓ AUCTION ANALYSIS: bid frequency per auction, average winning bids, bid amount distributions
    ✓ PRODUCT ANALYSIS: price ranges, quantity distributions, availability trends, donation impact
    ✓ CAMPAIGN ANALYSIS: goal achievement rates, funding velocity, milestone progress
    ✓ OPTIMIZATION: portfolio allocation (scipy.optimize), bid strategy ranking, charity ranking by impact-per-dollar

    WHEN NOT TO USE:
    ✗ when the needed information can be answered directly from tool output without computation
    ✗ when no prior tool output exists yet
    ✗ when the task is entity resolution, search, lookup, or website retrieval
    ✗ when the model can answer directly without code execution
    ✗ for simple counting/sorting that tools already provide

    INPUT SOURCE POLICY:
    - Prefer discover_charities output for list-level analytics across many charities (uses uniqueDonorCount, isVerified, isActive)
    - Prefer charity_details output for deep analysis of one resolved charity (uses donationAmount, products, blogs)
    - Prefer get_transaction_history for temporal donor behavior analysis (uses amount, type, status, createdAt)
    - Prefer list_charity_products for product-level analytics (uses pricePerUnit, availableQuantity, totalDonated)
    - Prefer list_charity_grants for fundraising progress (uses expectedAmount, raisedAmount, status)
    - Prefer list_charity_active_campaigns for campaign performance (uses goalAmount, receivedAmount)
    - Prefer get_my_bid_history for bid pattern analysis (uses bidAmount, status)
    - Do not fabricate data; only operate on prior tool outputs from chat history

    DEFAULT DEPENDENCY CHAINS:
    - discover_charities -> Python_REPL (charity comparison & ranking)
    - charity_details -> Python_REPL (single charity deep-dive)
    - get_transaction_history -> Python_REPL (donor behavior analysis)
    - list_charity_products -> Python_REPL (product analytics)
    - list_charity_grants -> Python_REPL (fundraising progress analysis)
    - list_charity_active_campaigns -> Python_REPL (campaign performance analysis)
    - get_my_bid_history -> Python_REPL (auction bid analysis)
    - Multiple tools combined -> Python_REPL (cross-domain analysis)

    CHAIN POSITION:
    - post-processing tool
    - usually final tool in a chain, after retrieval tools have produced data

    CODE EXAMPLES:

    ALL ANALYSIS QUERIES — use the GENERIC ANALYSIS TEMPLATE below.
    This template is data-agnostic: it works on any tabular tool output regardless of field names.

    ── GENERIC ANALYSIS TEMPLATE ──────────────────────────────────────────────────────
    import pandas as pd

    # STEP 1: Inline actual records from prior tool output as a Python list of dicts
    items = [
        # Include ONLY the label field (name/_id) and the numeric fields needed for analysis.
        # DO NOT copy nested objects, arrays, or boolean fields — they cause NameError (true/false).
    ]
    df = pd.DataFrame(items)

    # STEP 2: Cast ALL columns to numeric in one line — non-numeric columns become NaN
    # CRITICAL: use df.apply(...) NOT pd.to_numeric(df, ...) — the latter destroys the DataFrame
    num_df = df.apply(pd.to_numeric, errors="coerce")

    # STEP 3: Identify label column (first column whose numeric conversion is ALL NaN = it is text)
    label_col = next((c for c in df.columns if num_df[c].isna().all()), df.columns[0])

    # STEP 4: Keep only columns that converted successfully and are not the label
    num_cols = [c for c in num_df.columns if num_df[c].notna().any() and c != label_col]
    for col in num_cols:
        df[col] = num_df[col]

    # STEP 5: If a scalar constraint is available from another tool (e.g. wallet_balance, budget),
    # apply it as a filter HERE before scoring:
    #   constraint = <value from prior tool call, or None if unavailable>
    #   if constraint is not None:
    #       df = df[df["<constraint_col>"] <= constraint].copy()
    # If no constraint applies, skip this step.

    # STEP 6: Derive insight columns from available numeric data.
    # Do NOT just normalize raw columns — compute metrics that answer the user's question.
    # Examples of derived insight columns (use whichever apply to the data at hand):
    #   df["affordability"]   = constraint / df["minBidAmount"]   if constraint else None
    #   df["time_remaining"]  = (pd.to_datetime(df["endCol"]) - pd.Timestamp.now(tz="UTC")).dt.total_seconds() / 3600
    #   df["completion_pct"]  = df["raisedAmount"] / df["goalAmount"] * 100
    #   df["donor_density"]   = df["donorCount"] / df["donorCount"].max()
    # After deriving, collect only the new insight columns (not raw inputs) for scoring:
    insight_cols = []   # replace [] with list of derived column names you actually created

    # STEP 7: Compute total_score by normalizing each insight column to 0-1 and summing
    # Fall back to normalizing raw num_cols if no insight columns were derived
    score_src = insight_cols if insight_cols else num_cols
    for col in score_src:
        col_max = df[col].max()
        df[col + "_norm"] = (df[col] / col_max).round(3) if col_max and col_max != 0 else 0.0
    norm_cols = [c for c in df.columns if c.endswith("_norm")]
    df["total_score"] = df[norm_cols].sum(axis=1).round(3)

    # STEP 8: Print ranked table — label + insight columns + total_score
    out_cols = [label_col] + (insight_cols if insight_cols else num_cols) + ["total_score"]
    out_cols = [c for c in out_cols if c in df.columns]
    ranked = df[out_cols].sort_values("total_score", ascending=False).reset_index(drop=True)
    ranked.index += 1
    print(ranked.to_string())
    ── END TEMPLATE ────────────────────────────────────────────────────────────────────

    ── LINEAR PROGRAMMING (use when user asks to maximise/minimise subject to a budget) ──
    NEVER use greedy loops or manual iteration for optimisation — always use linprog.
    MUST NOT: c = -df[any_column].values   ← always produces wrong inflated output (e.g. 20000 instead of 20)
    MUST NOT: b_ub = \  or  b_ub = np.array()  ← budget missing → wrong answer
    MUST NOT: budget = X  then  b_ub = np.array([budget])  ← indirect reference is always forgotten; put the value directly
    MUST USE: b_ub = np.array([100])  ← substitute the literal number, e.g. np.array([100]) for a $100 budget

    NEVER use pandas/DataFrame/num_df for LP — always extract columns via list comprehension:
    from scipy.optimize import linprog
    import numpy as np
    items   = [{"pricePerUnit": 20, "availableQuantity": 800}, ...]   # inlined records
    prices  = np.array([p["pricePerUnit"]      for p in items], dtype=float)
    max_qty = np.array([p["availableQuantity"] for p in items], dtype=float)
    n       = len(items)
    c       = -np.ones(n)                   # MUST be -np.ones(n) — NEVER -prices, -max_qty, or any .values
    A_ub    = prices.reshape(1, n)          # shape must be (1, n)
    b_ub    = np.array([100])               # literal budget — NEVER np.array() or np.array([budget_var])
    bounds  = [(0, max_qty[i]) for i in range(n)]
    res     = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    print(res.message if not res.success else f"Max items: {-res.fun:.1f}, cost: {(res.x*prices).sum():.2f}")
    ── END LP TEMPLATE ─────────────────────────────────────────────────────────────────

    ANTI-PATTERNS — these cause NaN output or SyntaxError, never do them:
    ✗ pd.to_numeric(df, errors="coerce")              # operates on whole df → all string cols become NaN
    ✗ for col in df.columns: df = pd.to_numeric(...)  # same mistake, reassigns whole df
    ✗ (df['score'] = ...)                             # assignment inside parens → SyntaxError
    ✗ printing a plain sorted table with no derived metrics — that is NOT analysis

    RULES:
    ✓ Always use df.apply(pd.to_numeric, errors="coerce") for casting — never the loop form
    ✓ Always derive at least one insight column (Step 6) that directly answers the user's question
    ✓ Apply scalar constraints from other tool calls (balance, budget, limit) as filters before scoring
    ✓ For LP/optimisation queries: use the LP TEMPLATE above — never write linprog by hand from scratch
    ✓ For single-metric queries (mean, sum, max): Steps 1–4 only, then compute and print one value
    ✓ For groupby queries: Steps 1–4, then df.groupby(cat_col)[num_col].agg(...)
    ✓ Never reference a column name from memory — only use columns present in the inlined items

    INPUT FORMAT FOR CODE:
    There is NO pre-populated variable holding prior tool output. You MUST copy the actual data
    returned by prior tools directly into your Python code as a hardcoded Python list or dict literal.

    MANDATORY CODE STRUCTURE — always follow the GENERIC ANALYSIS TEMPLATE in CODE EXAMPLES above.
    Key rules:
    - Inline actual records from prior tool output as items = [{...}, ...]
    - Try pd.to_numeric(..., errors="coerce") on every column — auto-detect what is numeric
    - Convert boolean-like columns (True/False/Yes/No) to 0/1 so they contribute to scoring
    - For ranking/recommendation queries: compute total_score as sum of per-column normalized values
    - For simple aggregation: cast numeric columns first, then compute the single metric

    Do NOT write `output['data']['items']` or any other variable reference to prior tool output.
    Do NOT assume any variable (output, result, data, items, etc.) is pre-defined — it is not.
    Do NOT hardcode column names from memory — only use columns present in the inlined items list.

    Import at top: import pandas as pd, import numpy as np, import statistics
    Your final line MUST be a print() statement that outputs ONLY the final result (no lists, no extra text).

    CRITICAL - NEWLINES IN CODE:
    - Write code with real newline characters between statements.
    - Do NOT use `\\n` escape sequences inside the code string — that causes SyntaxError.

    CRITICAL - PYTHON BOOLEANS AND NULL:
    - NEVER use JSON literals in Python code. Python is NOT JSON.
    - JSON `true`  → Python `True`   (capital T)
    - JSON `false` → Python `False`  (capital F)
    - JSON `null`  → Python `None`   (capital N)
    - Using `true`, `false`, or `null` in Python code will always raise a NameError.
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
                        - planner only decides to use this tool as only step (unless user specifically asks about URL)
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
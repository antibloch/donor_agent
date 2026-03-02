import json
import os
from typing import Any, Dict, Optional

import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from langchain_experimental.tools import PythonREPLTool
# from langchain_mcp_adapters.client import MultiServerMCPClient


# --------------------------
# Common helpers
# --------------------------

DEFAULT_BASE_URL = "http://localhost:3000"


def _ok(result: Any, **meta) -> str:
    payload = {"ok": True, "result": result}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _fail(error: str, **meta) -> str:
    payload = {"ok": False, "error": error}
    if meta:
        payload["meta"] = meta
    return json.dumps(payload, ensure_ascii=False, default=str)


def _get(url: str, *, params: Optional[dict] = None, headers: Optional[dict] = None, timeout: int = 10) -> Dict[str, Any]:
    r = requests.get(url, params=params or {}, headers=headers or {}, timeout=timeout)
    # Your Node /api/stats always returns 200 even on errors,
    # but other endpoints return 4xx; handle both.
    try:
        data = r.json()
    except Exception:
        data = {"raw_text": r.text}
    return {"status": r.status_code, "json": data}


# --------------------------
# 1) Legacy stats tool (/api/stats?q=...)
# --------------------------

def build_node_stats_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
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


# --------------------------
# 2) Search charities (public)
# GET /api/v1/charity_organization/search?search=...
# --------------------------

def build_search_charities_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
    def search_charities(search: str) -> str:
        s = (search or "").strip()
        if not s:
            return _fail("search is required.")
        try:
            out = _get(f"{base_url}/api/v1/charity_organization/search", params={"search": s})
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}", endpoint="/api/v1/charity_organization/search")
            return _ok(out["json"], endpoint="/api/v1/charity_organization/search", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v1/charity_organization/search")

    class SearchInput(BaseModel):
        search: str = Field(..., description="Search term (charity name or email).")

    return StructuredTool.from_function(
        func=search_charities,
        name="search_charities",
        description=(
                "Search approved charities by name or email (PUBLIC).\n"
                "Endpoint: GET /api/v1/charity_organization/search?search=<term>\n"
                "Auth: None\n\n"
                "Args (JSON):\n"
                '- {"search": "<string>"}  (required)\n\n'
                "Response envelope (tool wrapper):\n"
                "- ok=true  -> { ok: true, result: <server_json>, meta?: {...} }\n"
                "- ok=false -> { ok: false, error: <string>, meta?: {...} }\n\n"
                "Server JSON (success):\n"
                "{ success: true, message: string, data: { searchQuery: string, totalResults: number, charities: ["
                "{ _id: string, name: string, email: string, logo: string|null, address: object, verificationStatus: string }"
                "] } }\n"
                "Server JSON (missing search): returns HTTP 400 { success:false, message:'Search query is required' }."
                ),
        args_schema=SearchInput,
    )


# --------------------------
# 3) Get charity profile by ID (public)
# GET /api/v1/charity_organization/get-charity-profile/:charityId
# --------------------------

def build_get_charity_profile_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
    def get_charity_profile(charity_id: str) -> str:
        cid = (charity_id or "").strip()
        if not cid:
            return _fail("charity_id is required.")
        try:
            out = _get(f"{base_url}/api/v1/charity_organization/get-charity-profile/{cid}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}", endpoint="/api/v1/charity_organization/get-charity-profile/:id")
            return _ok(out["json"], endpoint="/api/v1/charity_organization/get-charity-profile/:id", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v1/charity_organization/get-charity-profile/:id")

    class ProfileInput(BaseModel):
        charity_id: str = Field(..., description="Charity organization ID (e.g., org_001).")

    return StructuredTool.from_function(
        func=get_charity_profile,
        name="get_charity_profile",
        description=(
            "Get detailed profile for a single charity by charity_id (PUBLIC).\n"
            "Endpoint: GET /api/v1/charity_organization/get-charity-profile/:charityId\n"
            "Auth: None\n\n"
            "Args (JSON):\n"
            '- {"charity_id": "<string>"}  (required, e.g., "org_001")\n\n'
            "Response envelope (tool wrapper):\n"
            "- ok=true  -> { ok: true, result: <server_json>, meta?: {...} }\n"
            "- ok=false -> { ok: false, error: <string>, meta?: {...} }\n\n"
            "Server JSON (success):\n"
            "{ success:true, message:string, charity:{ _id,name,email,phone,logo,address,registrationNumber,"
            "verificationStatus,description,website,createdAt,updatedAt } }\n"
            "Server JSON (not found): HTTP 404 { success:false, message:'Charity not found or not approved' }."
            ),
        args_schema=ProfileInput,
    )


# --------------------------
# 4) Get charity products → NOW PUBLIC (no auth header)
# --------------------------

def build_get_charity_products_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
    def get_charity_products(
        page: int = 1,
        limit: int = 10,
        isActive: Optional[bool] = None,
        isDeleted: Optional[bool] = None,
        status: Optional[str] = None,
        productId: Optional[str] = None,
        minPrice: Optional[float] = None,
        maxPrice: Optional[float] = None,
        startDate: Optional[str] = None,
        endDate: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        sort: Optional[str] = None,
    ) -> str:
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if isActive is not None:
            params["isActive"] = str(bool(isActive)).lower()
        if isDeleted is not None:
            params["isDeleted"] = str(bool(isDeleted)).lower()
        if status:
            params["status"] = status
        if productId:
            params["productId"] = productId
        if minPrice is not None:
            params["minPrice"] = minPrice
        if maxPrice is not None:
            params["maxPrice"] = maxPrice
        if startDate:
            params["startDate"] = startDate
        if endDate:
            params["endDate"] = endDate
        if category:
            params["category"] = category
        if search:
            params["search"] = search
        if sort:
            params["sort"] = sort

        try:
            out = _get(f"{base_url}/api/v1/products/get-charity-products", params=params)  # NO header
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}", endpoint="/api/v1/products/get-charity-products")
            return _ok(out["json"], endpoint="/api/v1/products/get-charity-products", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v1/products/get-charity-products")

    class ProductsInput(BaseModel):
        page: int = Field(1, ge=1)
        limit: int = Field(10, ge=1, le=100)
        isActive: Optional[bool] = None
        isDeleted: Optional[bool] = None
        status: Optional[str] = Field(None, description="approved|pending|rejected")
        productId: Optional[str] = None
        minPrice: Optional[float] = None
        maxPrice: Optional[float] = None
        startDate: Optional[str] = Field(None, description="ISO date string")
        endDate: Optional[str] = Field(None, description="ISO date string")
        category: Optional[str] = Field(None, description="comma-separated category IDs")
        search: Optional[str] = None
        sort: Optional[str] = Field(None, description="e.g. -createdAt, price, name")

    return StructuredTool.from_function(
        func=get_charity_products,
        name="get_charity_products",
        description=(
            "Get paginated products for the demo charity (PUBLIC – no auth required).\n"
            "Endpoint: GET /api/v1/products/get-charity-products\n"
            "Auth: None (server hardcodes demo charity org_001)\n\n"
            "Args (JSON):\n"
            '- {"page":1, "limit":10, "isActive":true/false, "status":"approved", "search":"Food", "sort":"-createdAt", ...}\n'
            "All parameters are optional.\n\n"
            "Response envelope (tool wrapper):\n"
            "- ok=true  -> { ok: true, result: <server_json>, meta?: {...} }\n"
            "- ok=false -> { ok: false, error: <string>, meta?: {...} }\n\n"
            "Server JSON (success):\n"
            "{ success:true, message:string, data:{ products:[...], pagination:{...} } }"
        ),
        args_schema=ProductsInput,
    )


# --------------------------
# 5) Get charity blogs → NOW PUBLIC (no auth header)
# --------------------------

def build_get_charity_blogs_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
    def get_charity_blogs(
        page: int = 1,
        limit: int = 10,
        search: Optional[str] = None,
        sortBy: Optional[str] = None,
        order: Optional[str] = None,
    ) -> str:
        params: Dict[str, Any] = {"page": page, "limit": limit}
        if search:
            params["search"] = search
        if sortBy:
            params["sortBy"] = sortBy
        if order:
            params["order"] = order

        try:
            out = _get(f"{base_url}/api/v1/charity_organization/blogs", params=params)  # NO header
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}", endpoint="/api/v1/charity_organization/blogs")
            return _ok(out["json"], endpoint="/api/v1/charity_organization/blogs", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v1/charity_organization/blogs")

    class BlogsInput(BaseModel):
        page: int = Field(1, ge=1)
        limit: int = Field(10, ge=1, le=100)
        search: Optional[str] = Field(None, description="Search title/description/hashtags")
        sortBy: Optional[str] = Field(None, description="createdAt|updatedAt|title|status")
        order: Optional[str] = Field(None, description="asc|desc")

    return StructuredTool.from_function(
        func=get_charity_blogs,
        name="get_charity_blogs",
        description=(
            "Get paginated blogs for the demo charity (PUBLIC – no auth required).\n"
            "Endpoint: GET /api/v1/charity_organization/blogs\n"
            "Auth: None\n\n"
            "Args (JSON):\n"
            '- {"page":1, "limit":10, "search":"winter", "sortBy":"createdAt", "order":"desc"}\n'
            "All parameters are optional.\n\n"
            "Response envelope (tool wrapper):\n"
            "- ok=true  -> { ok: true, result: <server_json>, meta?: {...} }\n"
            "- ok=false -> { ok: false, error: <string>, meta?: {...} }\n\n"
            "Server JSON (success):\n"
            "{ success:true, message:string, blogs:[...], pagination:{...} }"
        ),
        args_schema=BlogsInput,
    )


# --------------------------
# 6) Get charity ranking → NOW PUBLIC (no auth header)
# --------------------------

def build_get_charity_ranking_tool(base_url: str = DEFAULT_BASE_URL) -> StructuredTool:
    def get_charity_ranking() -> str:
        try:
            out = _get(f"{base_url}/api/v1/charity_organization/charity-ranking")  # NO header
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}", endpoint="/api/v1/charity_organization/charity-ranking")
            return _ok(out["json"], endpoint="/api/v1/charity_organization/charity-ranking", http_status=out["status"])
        except requests.RequestException as e:
            return _fail(str(e), endpoint="/api/v1/charity_organization/charity-ranking")

    class RankingInput(BaseModel):
        # No parameters needed anymore
        pass

    return StructuredTool.from_function(
        func=get_charity_ranking,
        name="get_charity_ranking",
        description=(
            "Get ranking + impact stats for the demo charity (PUBLIC – no auth required).\n"
            "Endpoint: GET /api/v1/charity_organization/charity-ranking\n"
            "Auth: None\n\n"
            "Args (JSON): No parameters required\n\n"
            "Response envelope (tool wrapper):\n"
            "- ok=true  -> { ok: true, result: <server_json>, meta?: {...} }\n"
            "- ok=false -> { ok: false, error: <string>, meta?: {...} }\n\n"
            "Server JSON (success):\n"
            "{ success:true, message:string, data:{ ranking:{...}, rank:number } }"
        ),
        args_schema=RankingInput,
    )


# --------------------------
# AUCTION TOOLS
# --------------------------

MOCK_USER_ID = os.getenv("AUCTION_USER_ID", "usr_mujtaba")
AUCTION_BASE_URL = os.getenv("AUCTION_BASE_URL", "http://localhost:3000")


def build_get_wallet_balance_tool() -> StructuredTool:
    def get_wallet_balance() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/wallet/{MOCK_USER_ID}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class WalletInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_wallet_balance,
        name="get_wallet_balance",
        description=(
            "Fetch the current wallet balance for the authenticated user.\n"
            "Returns: balance, lockedBalance, availableBalance."
        ),
        args_schema=WalletInput,
    )


def build_get_active_auctions_tool() -> StructuredTool:
    def get_active_auctions() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/active")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionsInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_active_auctions,
        name="get_active_auctions",
        description=(
            "Fetch all currently active auctions.\n"
            "Returns: list of auctions with _id, title, minBidAmount, "
            "currentHighestBid, endTimeStamp, incrementType, incrementValue."
        ),
        args_schema=AuctionsInput,
    )


def build_get_auction_details_tool() -> StructuredTool:
    def get_auction_details(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionDetailsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_details,
        name="get_auction_details",
        description=(
            "Retrieve full details of a single auction by its ID.\n"
            "Returns: full auction object including currentHighestBid, totalBids, incrementType, incrementValue."
        ),
        args_schema=AuctionDetailsInput,
    )


def build_get_auction_bids_tool() -> StructuredTool:
    def get_auction_bids(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/bids")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionBidsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_bids,
        name="get_auction_bids",
        description=(
            "Retrieve all bids for a specific auction including the highest bid.\n"
            "Returns: totalBids, highestBid (amount, status, profile), bids list."
        ),
        args_schema=AuctionBidsInput,
    )


def build_get_auction_items_tool() -> StructuredTool:
    def get_auction_items(auction_id: str) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/items")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class AuctionItemsInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction.")

    return StructuredTool.from_function(
        func=get_auction_items,
        name="get_auction_items",
        description=(
            "Retrieve all items listed under a specific auction.\n"
            "Returns: totalItems, items list with name, description, condition."
        ),
        args_schema=AuctionItemsInput,
    )


def build_get_my_bid_history_tool() -> StructuredTool:
    def get_my_bid_history() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/users/{MOCK_USER_ID}/bids")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class BidHistoryInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_my_bid_history,
        name="get_my_bid_history",
        description=(
            "Retrieve the authenticated user's full bid history across all auctions.\n"
            "Returns: totalBids, bids list with amount, status (Leading/Outbid/Won/Lost), "
            "auctionTitle, auctionStatus."
        ),
        args_schema=BidHistoryInput,
    )


def build_place_bid_tool() -> StructuredTool:
    def place_bid(auction_id: str, amount: float) -> str:
        aid = (auction_id or "").strip()
        if not aid:
            return _fail("auction_id is required.")
        if not amount or amount <= 0:
            return _fail("amount must be a positive number.")
        try:
            r = requests.post(
                f"{AUCTION_BASE_URL}/auction/bid",
                json={"user_id": MOCK_USER_ID, "auction_id": aid, "amount": amount},
                timeout=5,
            )
            if not r.text.strip():
                return _fail("Empty response from server.")
            data = r.json()
            if not data.get("success"):
                return _fail(data.get("message", "Bid failed."), details=data)
            return _ok(data)
        except requests.exceptions.ConnectionError:
            return _fail("Could not connect to auction server.")
        except requests.exceptions.Timeout:
            return _fail("Auction server timed out.")
        except Exception as e:
            return _fail(str(e))

    class PlaceBidInput(BaseModel):
        auction_id: str = Field(..., description="The unique ID of the auction to bid on.")
        amount: float = Field(..., description="The bid amount in USD.", gt=0)

    return StructuredTool.from_function(
        func=place_bid,
        name="place_bid",
        description=(
            "Place a bid on an active auction on behalf of the authenticated user.\n"
            "Server validates: auction status, minimum bid, increment rules, config limit, wallet balance.\n"
            "On success: bid amount is locked in wallet. If outbid, amount is auto-released.\n"
            "Returns: bidId, auctionTitle, amount, nextMinimumBid, newLockedBalance, availableBalance."
        ),
        args_schema=PlaceBidInput,
    )


def build_finalize_ended_auctions_tool() -> StructuredTool:
    def finalize_ended_auctions() -> str:
        try:
            r = requests.post(f"{AUCTION_BASE_URL}/auction/finalize", timeout=10)
            if not r.text.strip():
                return _fail("Empty response from server.")
            data = r.json()
            return _ok(data)
        except requests.RequestException as e:
            return _fail(str(e))

    class FinalizeInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=finalize_ended_auctions,
        name="finalize_ended_auctions",
        description=(
            "Finalize all auctions that have ended.\n"
            "Deducts winning bid from winner wallet and releases locked funds for all other bidders.\n"
            "Returns: success message."
        ),
        args_schema=FinalizeInput,
    )


def build_get_donation_categories_tool() -> StructuredTool:
    def get_donation_categories() -> str:
        try:
            out = _get(f"{AUCTION_BASE_URL}/donation-categories")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class DonationCategoriesInput(BaseModel):
        pass

    return StructuredTool.from_function(
        func=get_donation_categories,
        name="get_donation_categories",
        description=(
            "Fetch all available donation categories (e.g. Emergency Funds, "
            "Water Projects, Gaza Relief, Food Aid, Education, Healthcare).\n"
            "Call this FIRST when user wants to browse or filter charities by cause/category.\n"
            "Returns: list of categories with _id, name, description, icon."
        ),
        args_schema=DonationCategoriesInput,
    )


def build_get_charities_by_category_tool() -> StructuredTool:
    def get_charities_by_category(category_id: str) -> str:
        cid = (category_id or "").strip()
        if not cid:
            return _fail("category_id is required.")
        try:
            out = _get(f"{AUCTION_BASE_URL}/charities/by-category/{cid}")
            if out["status"] >= 400:
                return _fail(f"HTTP {out['status']}: {out['json']}")
            return _ok(out["json"])
        except requests.RequestException as e:
            return _fail(str(e))

    class CharitiesByCategoryInput(BaseModel):
        category_id: str = Field(
            ...,
            description="Exact _id of the donation category (e.g. cat_emergency, cat_water, cat_gaza)."
        )

    return StructuredTool.from_function(
        func=get_charities_by_category,
        name="get_charities_by_category",
        description=(
            "Fetch all charities actively working in a specific donation category.\n"
            "Requires exact category _id from get_donation_categories.\n"
            "Returns: list of charities with name, description, website, phone, email."
        ),
        args_schema=CharitiesByCategoryInput,
    )

# --------------------------
# Tool setup
# --------------------------

def setup_tools():
    local_tools = [
        build_node_stats_tool(),
        build_search_charities_tool(),
        build_get_charity_profile_tool(),
        build_get_charity_products_tool(),
        build_get_charity_blogs_tool(),
        build_get_charity_ranking_tool(),
        PythonREPLTool(),
        # Auction tools
        build_get_wallet_balance_tool(),
        build_get_active_auctions_tool(),
        build_get_auction_details_tool(),
        build_get_auction_bids_tool(),
        build_get_auction_items_tool(),
        build_get_my_bid_history_tool(),
        build_place_bid_tool(),
        build_finalize_ended_auctions_tool(),
        build_get_donation_categories_tool(),      
        build_get_charities_by_category_tool(),
    ]
    return local_tools

    


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
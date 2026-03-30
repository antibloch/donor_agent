
import requests
from langchain_core.tools import tool
from tools.tool_helpers import _ok, _fail

# ── CONSTANTS ─────────────────────────────────────────────

BASE_URL = "https://giverr-api.verior.co"
AGENT_BASE_PATH = "/api/v3/agent"

X_API_KEY = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"
BEARER_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"

# Donor profile ObjectId — needed for get_my_bid_history endpoint
DONOR_PROFILE_ID = "695803a95d120db61afaf042"



# ── HEADERS ───────────────────────────────────────────────

def _api_headers() -> dict:
    """Read-only endpoints — only X-API-KEY required."""
    if not X_API_KEY:
        raise ValueError("X-API-KEY is required.")
    return {
        "Content-Type": "application/json",
        "X-API-KEY": X_API_KEY,
    }


def _user_headers() -> dict:
    """User-scoped endpoints — Bearer token required."""
    if not BEARER_TOKEN:
        raise ValueError("BEARER_TOKEN is required.")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {BEARER_TOKEN}",
    }


# ── AUCTION TOOLS ─────────────────────────────────────────

@tool
def get_active_auctions():
    """
    PURPOSE:
    Fetch all currently active auctions available on the platform.

    MUST_CALL_FIRST:
    - When the user wants to browse, explore, or list auctions before taking any action.
    - Before calling get_auction_details or place_bid when no auction _id is known.

    DEFAULT_CHAIN:
    - get_active_auctions -> get_auction_details -> place_bid

    WHEN TO USE:
    - User says: 'show auctions', 'active auctions', 'list auctions',
      'what auctions are there', 'any auctions', 'browse auctions'
    - auction _id is not yet known and is needed for a downstream tool

    DO NOT USE WHEN:
    - Auction list is already cached in chat history from this turn — reuse it instead.
    - User is asking about bid history, wallet balance, or donation categories.

    REQUIRES (Intuitive Schema):
    - No arguments required.

    REQUIRES (Detailed Schema):
    - No parameters.

    RETURNS (Intuitive Schema):
    - List of active auctions with titles, minimum bids, increments, and end times.

    RETURNS (Detailed Schema):
    - result.auctions -> list of auction objects, each containing:
        _id (str): Auction ID — required for get_auction_details and place_bid.
        title (str): Auction title.
        description (str): Auction description.
        minBidAmount (float): Minimum allowed bid.
        incrementType (str): Fixed or Percentage.
        incrementValue (float): Bid increment value.
        startTimeStamp (str): Auction start time (ISO format).
        endTimeStamp (str): Auction end time (ISO format).
    - result.pagination -> currentPage, totalPages, totalItems, hasNext, hasPrev.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - Output of this tool supplies auction _id for get_auction_details and place_bid.
    - If planning before execution, planner should use placeholder:
      "<AUCTION_ID_FROM_GET_ACTIVE_AUCTIONS>"
    - NEVER pass a display number like 1 or 2 — always use the exact _id string.

    DO NOT STOP HERE WHEN:
    - User wants full details of a specific auction — call get_auction_details next.
    - User wants to place a bid — resolve _id first, then call place_bid.
    """

    endpoint = f"{AGENT_BASE_PATH}/auctions/list"
    params = {"page": 1, "limit": 10}
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=_api_headers(),
            params=params
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                response_text=response.text[:2000]
            )
        data = response.json()
        auctions = data.get("data", {}).get("auctions", [])
        pagination = data.get("data", {}).get("pagination", {})
        return _ok(
            {"auctions": auctions, "pagination": pagination},
            endpoint=endpoint,
            http_status=response.status_code
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


@tool
def get_auction_details(auction_id: str):
    """
    PURPOSE:
    Retrieve full details of a single auction by its MongoDB ObjectId.

    MUST_CALL_FIRST:
    - get_active_auctions must be called first to obtain a valid auction _id.

    DEPENDS_ON:
    - get_active_auctions — must be called first to obtain auction_id.
    - auction_id passed here MUST come from get_active_auctions result, never invented.

    DEFAULT_CHAIN:
    - get_active_auctions -> get_auction_details -> place_bid

    WHEN TO USE:
    - User asks for details, description, condition, reserve price, or increment
      info about a specific auction.
    - User references 'the first auction', 'auction 1', or any auction by position —
      resolve the _id from get_active_auctions history first, then call this tool.

    DO NOT USE WHEN:
    - auction_id is not yet known — call get_active_auctions first.
    - User only wants a list of auctions — use get_active_auctions instead.
    - No auctions exist in the DB — inform user rather than guessing an ID.
    - NEVER pass a display number like 1 or 2 as auction_id.
    - NEVER guess or invent an auction_id.

    REQUIRES (Intuitive Schema):
    - Exact auction _id from get_active_auctions output.

    REQUIRES (Detailed Schema):
    - auction_id (str): MongoDB ObjectId of the auction.
                        Must be an exact _id from get_active_auctions.
                        NEVER a display number. NEVER guessed.

    RETURNS (Intuitive Schema):
    - Full auction object including condition, reserve price, and increment rules.

    RETURNS (Detailed Schema):
    - result contains:
        _id (str): Auction ID.
        title (str): Auction title.
        description (str): Auction description.
        condition (str): Item condition (e.g. New, Used).
        minBidAmount (float): Minimum allowed bid.
        incrementType (str): Fixed or Percentage.
        incrementValue (float): Bid increment value.
        reservePrice (float): Minimum price seller will accept.
        startTimeStamp (str): Auction start time (ISO format).
        endTimeStamp (str): Auction end time (ISO format).

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - Output of this tool informs the user before they call place_bid.
    - Planner placeholder: "<AUCTION_ID_FROM_GET_ACTIVE_AUCTIONS>"

    DO NOT STOP HERE WHEN:
    - User wants to place a bid after viewing details — call place_bid next.
    """

    auction_id = (auction_id or "").strip()
    if not auction_id:
        return _fail("auction_id is required.")
    if auction_id.startswith("<") and auction_id.endswith(">"):
        return _fail(
            "auction_id is a placeholder and cannot be used. Call get_active_auctions first to resolve the real auction _id.",
            endpoint=f"{AGENT_BASE_PATH}/auctions/{auction_id}"
        )

    endpoint = f"{AGENT_BASE_PATH}/auctions/{auction_id}"
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=_api_headers()
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                auction_id=auction_id,
                response_text=response.text[:2000]
            )
        return _ok(
            response.json().get("data", {}),
            endpoint=endpoint,
            http_status=response.status_code,
            auction_id=auction_id
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint, auction_id=auction_id)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


@tool
def get_my_bid_history():
    """
    PURPOSE:
    Retrieve all bids placed by the authenticated donor across all auctions.

    MUST_CALL_FIRST:
    - This is a standalone tool. No prerequisite tool required.

    DEPENDS_ON:
    - No dependencies. Standalone tool.
    - Uses DONOR_PROFILE_ID constant from auctions.py — must be a valid donorProfile ObjectId.
    AUTH:
    - Uses X-API-KEY header only (read-only endpoint).

    DEFAULT_CHAIN:
    - get_my_bid_history (standalone)

    WHEN TO USE:
    - ALWAYS call this tool when user says any of:
      'my bids', 'bid history', 'show my bids', 'what have I bid on',
      'my auction activity', 'am I winning', 'show bid history'.
    - This is the ONLY correct tool for bid history.
    - Do NOT substitute check_wallet_balance or any other tool for this request.

    DO NOT USE WHEN:
    - User wants to list all available auctions — use get_active_auctions instead.
    - User wants to place a new bid — use place_bid instead.
    - NEVER replace this tool with check_wallet_balance for bid history requests.

    REQUIRES (Intuitive Schema):
    - No arguments required. Donor identity is handled server-side.

    REQUIRES (Detailed Schema):
    - No parameters.

    RETURNS (Intuitive Schema):
    - List of all bids placed by the donor with status and amounts.

    RETURNS (Detailed Schema):
    - result.bids -> list of bid objects, each containing:
        auctionId (str): Auction ID the bid was placed on.
        title (str): Auction title.
        bidAmount (float): Amount bid.
        status (str): Bid status — Pending, Won, or Lost.
        startTimeStamp (str): Auction start time (ISO format).
        endTimeStamp (str): Auction end time (ISO format).
    - result.totalBids (int): Total number of bids placed.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - This is typically a terminal tool — no chaining required.

    DO NOT STOP HERE WHEN:
    - User wants to place a new bid after reviewing history — call place_bid next.
    """

    endpoint = f"{AGENT_BASE_PATH}/user/{DONOR_PROFILE_ID}/bids"
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=_api_headers()
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                response_text=response.text[:2000]
            )
        data = response.json()
        bids = data if isinstance(data, list) else data.get("bids", [])
        return _ok(
            {"bids": bids, "totalBids": len(bids)},
            endpoint=endpoint,
            http_status=response.status_code
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


@tool
def place_bid(auction_id: str, amount: float):
    """
    PURPOSE:
    Place a bid on an active auction on behalf of the authenticated donor.

    MUST_CALL_FIRST:
    - get_active_auctions must have been called to obtain a valid auction _id.
    - User must have explicitly stated both the bid amount AND auction_id.

    DEPENDS_ON:
    - get_active_auctions — required to resolve auction_id before calling this tool.
    - Bearer token (BEARER_TOKEN constant) — used in Authorization header for this request.

    AUTH:
    - Uses Bearer token header (user-scoped endpoint).

    DEFAULT_CHAIN:
    - get_active_auctions -> (optionally get_auction_details) -> place_bid

    WHEN TO USE:
    - User explicitly says they want to place a bid AND has provided:
        1. A specific auction reference (resolvable to an exact _id)
        2. A specific bid amount (explicitly stated, never assumed)
    - BOTH must be present before scheduling this tool.

    DO NOT USE WHEN:
    - auction_id is missing or unresolved — add 'auction_id' to missing_args.
    - amount is missing or ambiguous — add 'amount' to missing_args.
    - NEVER pass a display number like 1 or 2 as auction_id.
    - NEVER guess or invent an auction_id.
    - User is only browsing or asking about auctions.
    - A successful bid already exists in this turn's history.

    REQUIRES (Intuitive Schema):
    - Exact auction _id and explicit bid amount.

    REQUIRES (Detailed Schema):
    - auction_id (str): Exact MongoDB ObjectId from get_active_auctions output.
                        NEVER a display number. NEVER guessed or invented.
    - amount (float): Bid amount explicitly stated by the user. Must be > 0.
                      NEVER assumed or inferred.

    RETURNS (Intuitive Schema):
    - Confirmation of bid placement with bid ID and status.

    RETURNS (Detailed Schema):
    - result contains:
        _id (str): Bid record ID.
        amount (float): Bid amount placed.
        status (str): Bid status — Pending after successful placement.
        message (str): Confirmation or error message from server.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - After placing a bid, user may want to check bid history — call get_my_bid_history.
    - Planner placeholder for auction_id: "<AUCTION_ID_FROM_GET_ACTIVE_AUCTIONS>"

    DO NOT STOP HERE WHEN:
    - User wants to check if their bid is winning — call get_my_bid_history next.
    """

    auction_id = (auction_id or "").strip()
    if not auction_id:
        return _fail("auction_id is required.")
    if auction_id.startswith("<") and auction_id.endswith(">"):
        return _fail(
            "auction_id is a placeholder and cannot be used. Call get_active_auctions first to resolve the real auction _id.",
            endpoint=f"{AGENT_BASE_PATH}/auctions/{auction_id}/bid"
        )
    if not amount or amount <= 0:
        return _fail("amount must be a positive number.")
    # if not password:
    #     return _fail("password is required.")

    # from tools.transactions import verify_user_password
    # auth = verify_user_password(password)
    # if not auth["success"]:
    #     return _fail(
    #         f"TERMINAL_ERROR: Transaction Denied — password is incorrect. Do NOT retry with a different password. User must re-enter their password.",
    #         endpoint=f"{AGENT_BASE_PATH}/auctions/{auction_id}/bid"
    #     )

    endpoint = f"{AGENT_BASE_PATH}/auctions/{auction_id}/bid"
    try:
        response = requests.post(
            f"{BASE_URL}{endpoint}",
            headers=_user_headers(),
            json={"bidAmount": amount}
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                auction_id=auction_id,
                response_text=response.text[:2000]
            )
        return _ok(
            response.json().get("data", response.json()),
            endpoint=endpoint,
            http_status=response.status_code,
            auction_id=auction_id
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint, auction_id=auction_id)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


# ── DONATION CATEGORY TOOLS ───────────────────────────────

@tool
def get_donation_categories():
    """
    PURPOSE:
    Fetch all available donation types/categories on the platform.

    MUST_CALL_FIRST:
    - Always call this before get_charities_by_donation_type.
    - Required to obtain valid donation_type _id values for downstream tools.

    DEPENDS_ON:
    - No dependencies. Standalone tool — entry point of the donation category chain.
    AUTH:
    - Uses X-API-KEY header only (read-only endpoint).

    DEFAULT_CHAIN:
    - get_donation_categories -> get_charities_by_donation_type

    WHEN TO USE:
    - User says: 'show categories', 'donation categories', 'what categories are there',
      'show donation categories', 'browse causes', 'find charities by cause',
      'what types of donations', 'filter charities', 'charities by type'.
    - donation_type _id is not yet known and is needed for get_charities_by_donation_type.

    DO NOT USE WHEN:
    - Donation category _ids are already present in chat history — reuse them instead.
    - User is asking to list charities directly — this only returns categories.

    REQUIRES (Intuitive Schema):
    - No arguments required.

    REQUIRES (Detailed Schema):
    - No parameters.

    RETURNS (Intuitive Schema):
    - List of donation categories with names and IDs.

    RETURNS (Detailed Schema):
    - result.categories -> list of category objects, each containing:
        _id (str): Category ID — required for get_charities_by_donation_type.
        name (str): Category display name (e.g. chanda, fitra, hadya, saqdah).
        description (str): Short description of the category.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - Output of this tool supplies donation_type_id for get_charities_by_donation_type.
    - Planner placeholder: "<DONATION_TYPE_ID_FROM_GET_DONATION_CATEGORIES>"
    - NEVER guess a category _id — only use values returned by this tool.

    DO NOT STOP HERE WHEN:
    - User wants to see charities for a specific category — call get_charities_by_donation_type next.
    """
    endpoint = f"{AGENT_BASE_PATH}/donation-categories"
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=_api_headers()
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                response_text=response.text[:2000]
            )
        data = response.json()
        # API returns { "categories": [...] } — handle both flat and nested
        categories = data.get("categories", data.get("data", {}).get("categories", []))
        return _ok(
            {"categories": categories},
            endpoint=endpoint,
            http_status=response.status_code
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


@tool
def get_charities_by_donation_type(donation_type_id: str, country_code: str = "PK"):
    """
    PURPOSE:
    Fetch all charities accepting a specific donation type/category.

    MUST_CALL_FIRST:
    - get_donation_categories must be called first to obtain a valid donation_type_id.

    DEPENDS_ON:
    - get_donation_categories — must be called first to obtain donation_type_id.
    - donation_type_id passed here MUST come from get_donation_categories result, never invented.

    DEFAULT_CHAIN:
    - get_donation_categories -> get_charities_by_donation_type

    WHEN TO USE:
    - User wants to see charities for a SPECIFIC named category
      (e.g. 'chanda', 'fitra', 'hadya', 'saqdah').
    - donation_type_id is already known from get_donation_categories output.
    - User selects a category by number (e.g. 'category 2') — resolve the _id
      from prior get_donation_categories output, then call this tool.

    DO NOT USE WHEN:
    - User has NOT named or selected a specific category — add 'category_name'
      to missing_args and ask the user which category they want first.
    - NEVER call for ALL categories at once.
    - NEVER guess or invent a donation_type_id.
    - NEVER call before get_donation_categories has been called in this session.

    REQUIRES (Intuitive Schema):
    - Exact donation_type_id from get_donation_categories and optional country code.

    REQUIRES (Detailed Schema):
    - donation_type_id (str): Exact _id from get_donation_categories output.
                              NEVER guessed. NEVER invented.
    - country_code (str): ISO country code to filter charities by country.
                          Defaults to 'PK' if not specified by user.

    RETURNS (Intuitive Schema):
    - List of charities accepting the selected donation type in the specified country.

    RETURNS (Detailed Schema):
    - result.charities -> list of charity objects, each containing:
        _id (str): Charity ID.
        name (str): Charity name.
        description (str): Charity description.
        email (str): Contact email.
        phone (str): Contact phone.
        website (str): Charity website URL.

    CHAIN_OUTPUT_FOR_NEXT_TOOL:
    - This is typically a terminal tool in the donation category chain.
    - Planner placeholder for donation_type_id:
      "<DONATION_TYPE_ID_FROM_GET_DONATION_CATEGORIES>"

    DO NOT STOP HERE WHEN:
    - User wants more details about a specific charity from the results —
      pass the charity _id to charity_details tool.
    """
    
    donation_type_id = (donation_type_id or "").strip()
    if not donation_type_id:
        return _fail("donation_type_id is required.")
    if donation_type_id.startswith("<") and donation_type_id.endswith(">"):
        return _fail(
            "donation_type_id is a placeholder. Call get_donation_categories first to resolve the real _id.",
            endpoint=f"{AGENT_BASE_PATH}/charities/by-donation-type"
        )
    endpoint = f"{AGENT_BASE_PATH}/charities/by-donation-type"
    try:
        response = requests.get(
            f"{BASE_URL}{endpoint}",
            headers=_api_headers(),
            params={
                "donationTypeId": donation_type_id,
                "countryCode": country_code
            }
        )
        if response.status_code >= 400:
            return _fail(
                f"HTTP {response.status_code}",
                endpoint=endpoint,
                http_status=response.status_code,
                donation_type_id=donation_type_id,
                response_text=response.text[:2000]
            )
        data = response.json()
        charities = data.get("data", data.get("charities", []))
        return _ok(
            {"charities": charities},
            endpoint=endpoint,
            http_status=response.status_code,
            donation_type_id=donation_type_id
        )
    except requests.RequestException as e:
        return _fail(str(e), endpoint=endpoint, donation_type_id=donation_type_id)
    except Exception as e:
        return _fail(f"Unexpected error: {str(e)}", endpoint=endpoint)


# ── METADATA ──────────────────────────────────────────────

metadata_auctions = {
    "get_active_auctions": {
        "domain": "auction",
        "type": "lookup",
        "when_to_use": (
            "When user wants to browse, view, or see available auctions. "
            "Trigger phrases: 'show auctions', 'active auctions', 'browse auctions', "
            "'what auctions are there', 'any auctions', 'list auctions'."
        ),
        "do_not_use": (
            "Do not use for bid history, wallet balance, or auction details. "
            "Do not call again if auction list is already in chat history from this turn."
        ),
        "supports_pagination": True,
        "requires_auth": False,
        "example_usage": "no args required",
        "hint": (
            "- Returns _id values — these are the ONLY valid inputs for get_auction_details and place_bid.\n"
            "- Never pass a display number like 1 or 2 to other auction tools — always use the _id string.\n"
            "- If auction list is already in history, reuse those _id values instead of calling again."
        )
    },
    "get_auction_details": {
        "domain": "auction",
        "type": "lookup",
        "when_to_use": (
            "When user asks for details, description, condition, reserve price, or increment info "
            "about a specific auction. Requires exact _id from get_active_auctions."
        ),
        "do_not_use": (
            "Never call with a display number like 1 or 2. "
            "Never guess an auction_id — it must come from get_active_auctions output. "
            "If no auctions exist or auction list is empty, return missing_args instead of guessing. "
            "Do not use to list all auctions."
        ),
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": 'auction_id="507f1f77bcf86cd799439011"',
        "hint": (
            "- auction_id must be an exact MongoDB ObjectId string from get_active_auctions.\n"
            "- If user says 'tell me about auction 1' — first check if _id for item 1 is already in history.\n"
            "- If _id is not in history, call get_active_auctions first to get it.\n"
            "- If get_active_auctions returns empty list, inform user there are no active auctions."
        )
    },
    "get_my_bid_history": {
    "domain": "auction",
    "type": "lookup",
    "when_to_use": (
        "ALWAYS call this tool when user says any of: 'my bids', 'bid history', "
        "'show my bids', 'what have I bid on', 'my auction activity', 'am I winning'. "
        "This is the ONLY correct tool for bid history — do NOT substitute check_wallet_balance."
    ),
    "do_not_use": (
        "Do not use for listing all available auctions. "
        "Do not use for placing a new bid. "
        "NEVER replace this tool with check_wallet_balance for bid history requests."
    ),
    "supports_pagination": False,
    "requires_auth": False,
    "example_usage": "no args required",
    "hint": (
        "- Returns bids with status: Pending, Won, or Lost.\n"
        "- No arguments needed — donor identity is handled server-side.\n"
        "- Trigger words: 'my bids', 'bid history', 'show my bids', 'what have I bid on'."
    )
},

    "place_bid": {
        "domain": "auction",
        "type": "action",
        "when_to_use": (
            "When user explicitly states they want to place a bid AND provides both "
            "a specific auction reference AND a bid amount. "
            "a specific auction reference AND a bid amount."
        ),
        "do_not_use": (
            "Never call if auction_id is missing or unresolved. "
            "Never call if amount is missing or ambiguous. "
            "Never call if user only typed a number without specifying an auction. "
            "Never call if user is just browsing or asking about auctions. "
            "Never re-call if a successful bid already exists in this turn's history."
        ),
        "supports_pagination": False,
        "requires_auth": True,
        "example_usage": 'auction_id="507f...", amount=150, password="userpass"',
        "hint": (
            "- auction_id must be an exact _id from get_active_auctions — never a display number.\n"
            "- amount must be explicitly stated by the user — never assume or infer it.\n"
            "- amount must be explicitly stated by the user.\\n"
            "- If auction_id is not known, call get_active_auctions first then resolve the _id.\n"
            "- On success the server returns bid _id, amount, and status Pending."
        )
    },
    "get_donation_categories": {
        "domain": "charity",
        "type": "lookup",
        "when_to_use": (
            "ALWAYS call this FIRST when user wants to browse or filter charities by cause, type, or category. "
            "Trigger phrases: 'show categories', 'donation categories', 'what categories are there', "
            "'show donation categories', 'browse causes', 'find charities by cause', "
            "'what types of donations', 'filter charities', 'charities by type'."
        ),
        "do_not_use": (
            "Do not call again if donation category _ids are already present in chat history. "
            "Do not use for listing charities directly — this only returns categories."
        ),
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "no args required",
        "hint": (
            "- This is Step 1 of a two-step flow. Always call this before get_charities_by_donation_type.\n"
            "- Returns _id values for each category — pass the exact _id to get_charities_by_donation_type.\n"
            "- Never guess a category _id — only use values returned by this tool.\n"
            "- If category _ids are already in history from a prior call, skip this and go straight to get_charities_by_donation_type."
        )
    },
    "get_charities_by_donation_type": {
        "domain": "charity",
        "type": "lookup",
        "when_to_use": (
            "When user wants to see charities working in a specific cause or donation category "
            "AND the exact donation_type_id is already known from get_donation_categories. "
            "This is Step 2 of the two-step category filter flow."
        ),
        "do_not_use": (
            "Never call with a guessed or assumed donation_type_id. "
            "Only use _id values returned by get_donation_categories. "
            "Never call before get_donation_categories has been called in this session. "
            "NEVER call for ALL categories at once. "
            "If user has NOT named a specific category, add 'category_name' to missing_args "
            "and ask the user which category they want BEFORE calling this tool."
        ),
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": 'donation_type_id="abc123...", country_code="PK"',
        "hint": (
            "- donation_type_id must be an exact _id from get_donation_categories output.\n"
            "- country_code defaults to PK if not specified by user — always pass it explicitly.\n"
            "- If user selects a category by number (e.g. '2'), resolve the _id from prior get_donation_categories output.\n"
            "- Returns charities with name, description, email, phone, website.\n"
            "- Two-step flow: get_donation_categories → get_charities_by_donation_type."
        )
    },
}


# ── STANDALONE TEST ───────────────────────────────────────

if __name__ == "__main__":
    import json

    print("\n==============================")
    print("Testing auction tools")
    print("==============================\n")

    # Test 1 — Get active auctions
    print("TEST 1: get_active_auctions\n")
    result = get_active_auctions.invoke({})
    print(json.dumps(result, indent=2) if isinstance(result, dict) else result)

    # Try to extract auction_id for next tests
    auction_id = None
    try:
        parsed = result if isinstance(result, dict) else json.loads(result)
        auctions = parsed.get("result", {}).get("auctions", [])
        if auctions:
            auction_id = auctions[0].get("_id")
    except Exception:
        pass

    # Test 2 — Get auction details
    if auction_id:
        print(f"\nTEST 2: get_auction_details (id={auction_id})\n")
        result = get_auction_details.invoke({"auction_id": auction_id})
        print(json.dumps(result, indent=2) if isinstance(result, dict) else result)
    else:
        print("\nSkipping TEST 2 — no auction_id found (DB may be empty).\n")

    # Test 3 — Get bid history
    print("\nTEST 3: get_my_bid_history\n")
    result = get_my_bid_history.invoke({})
    print(json.dumps(result, indent=2) if isinstance(result, dict) else result)

    # Test 4 — Get donation categories
    print("\nTEST 4: get_donation_categories\n")
    result = get_donation_categories.invoke({})
    print(json.dumps(result, indent=2) if isinstance(result, dict) else result)

    # Try to extract donation_type_id for next test
    donation_type_id = None
    try:
        parsed = result if isinstance(result, dict) else json.loads(result)
        categories = parsed.get("result", {}).get("categories", [])
        if isinstance(categories, dict):
            categories = categories.get("categories", [])
        if categories:
            donation_type_id = categories[0].get("_id")
    except Exception:
        pass

    # Test 5 — Get charities by donation type
    if donation_type_id:
        print(f"\nTEST 5: get_charities_by_donation_type (id={donation_type_id})\n")
        result = get_charities_by_donation_type.invoke({
            "donation_type_id": donation_type_id,
            "country_code": "PK"
        })
        print(json.dumps(result, indent=2) if isinstance(result, dict) else result)
    else:
        print("\nSkipping TEST 5 — no donation_type_id found.\n")

    print("\n==============================")
    print("Auction Tool Tests Finished")
    print("==============================\n")


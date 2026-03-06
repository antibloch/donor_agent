import os
import requests
from langchain_core.tools import tool
from tools.tool_helpers import _ok, _fail

# ── CONSTANTS ─────────────────────────────────────────────

BASE_URL = "https://giverr-api.verior.co"
AGENT_BASE_PATH = "/api/v3/agent"

X_API_KEY = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"

# userId from JWT — used as the value to encrypt for X-USER-ID
_USER_ID_RAW = "695803a95d120db61afaf03e"

# Donor profile ObjectId — needed for get_my_bid_history endpoint
DONOR_PROFILE_ID = "PENDING"  # ask dev for donorProfile _id for demo account


# ── X-USER-ID ENCRYPTION ──────────────────────────────────
# Using AES-256-CBC encryption with a derived key.
# Format matches Postman collection pattern: encryptedData:iv (both hex-encoded)
# If dev provides a different secret key, update ENCRYPTION_SECRET below.

import hashlib
import hmac
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
import secrets

ENCRYPTION_SECRET = "giverr_ai_live_9f3b7c6e2d4a8f1c5e7b9a2c6d1f4e8b3c7a9d2e6f1b4c8a3d7e2f6c9b1a4e8"


def _encrypt_user_id(user_id: str) -> str:
    """
    Encrypts userId using AES-256-CBC.
    Returns: "encryptedHex:ivHex" format as expected by X-USER-ID header.
    """
    # Derive a 32-byte key from the secret using SHA-256
    key = hashlib.sha256(ENCRYPTION_SECRET.encode("utf-8")).digest()
    # Generate a random 16-byte IV
    iv = secrets.token_bytes(16)
    cipher = AES.new(key, AES.MODE_CBC, iv)
    encrypted = cipher.encrypt(pad(user_id.encode("utf-8"), AES.block_size))
    return f"{encrypted.hex()}:{iv.hex()}"


# Pre-compute once at module load — reused across all requests
_X_USER_ID = _encrypt_user_id(_USER_ID_RAW)


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
    """User-scoped endpoints — X-API-KEY + X-USER-ID required."""
    if not X_API_KEY:
        raise ValueError("X-API-KEY is required.")
    if not _X_USER_ID:
        raise ValueError("X-USER-ID is required.")
    return {
        "Content-Type": "application/json",
        "X-API-KEY": X_API_KEY,
        "X-USER-ID": _X_USER_ID,
    }


# ── AUCTION TOOLS ─────────────────────────────────────────

@tool
def get_active_auctions():
    """
    Fetch all currently active auctions.
    Returns a paginated list of auctions.
    Returns:
        dict:
            - success (bool): Whether the request was successful.
            - auctions (list[dict]): List of auction objects, each containing:
                - _id (str): Auction ID.
                - title (str): Auction title.
                - description (str): Auction description.
                - minBidAmount (float): Minimum bid amount.
                - incrementType (str): Fixed or Percentage.
                - incrementValue (float): Increment value.
                - startTimeStamp (str): Auction start time (ISO format).
                - endTimeStamp (str): Auction end time (ISO format).
            - pagination (dict): Pagination details.
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
    Retrieve full details of a single auction by its ID.
    Args:
        auction_id (str): MongoDB ObjectId of the auction.
                          Must be an exact _id from get_active_auctions.
                          NEVER pass a display number like 1 or 2.
                          NEVER guess or invent an auction_id.
                          If no auctions are in history, call get_active_auctions first.
    Returns:
        dict:
            - success (bool): Whether the request was successful.
            - auction (dict): Full auction object containing:
                - _id (str): Auction ID.
                - title (str): Auction title.
                - description (str): Auction description.
                - condition (str): Item condition.
                - minBidAmount (float): Minimum bid amount.
                - incrementType (str): Fixed or Percentage.
                - incrementValue (float): Increment value.
                - reservePrice (float): Reserve price.
                - startTimeStamp (str): ISO timestamp.
                - endTimeStamp (str): ISO timestamp.
    """
    auction_id = (auction_id or "").strip()
    if not auction_id:
        return _fail("auction_id is required.")

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
    ALWAYS call this tool when user says: 'my bids', 'bid history', 'show my bids',
    'what have I bid on', 'my auction activity', 'am I winning'.
    Do NOT call check_wallet_balance instead of this tool for bid history requests.

    Retrieve all bids placed by the authenticated donor.
    Returns:
        dict:
            - success (bool): Whether the request was successful.
            - bids (list[dict]): List of bid objects, each containing:
                - auctionId (str): Auction ID.
                - title (str): Auction title.
                - bidAmount (float): Amount bid.
                - status (str): Pending, Won, or Lost.
                - startTimeStamp (str): Auction start time (ISO format).
                - endTimeStamp (str): Auction end time (ISO format).
            - totalBids (int): Total number of bids.
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
def place_bid(auction_id: str, amount: float, password: str):
    """
    Place a bid on an active auction on behalf of the authenticated donor.
    Args:
        auction_id (str): Exact _id of the auction to bid on.
                          Must come from get_active_auctions output.
                          NEVER pass a display number. NEVER guess an ID.
        amount (float): Bid amount. Must be greater than zero.
                        Must be explicitly stated by user — never assumed.
        password (str): User's account password for transaction authorization.
                        Mandatory — add to missing_args if not provided.
    Returns:
        dict:
            - success (bool): Whether the bid was placed successfully.
            - message (str): Confirmation or error message.
            - data (dict): Bid details including _id, amount, status.
    """
    auction_id = (auction_id or "").strip()
    if not auction_id:
        return _fail("auction_id is required.")
    if not amount or amount <= 0:
        return _fail("amount must be a positive number.")
    if not password:
        return _fail("password is required.")

    from tools.transactions import verify_user_password
    auth = verify_user_password(password)
    if not auth["success"]:
        return _fail(
            f"Transaction Denied: {auth['message']}",
            endpoint=f"{AGENT_BASE_PATH}/auctions/{auction_id}/bid"
        )

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
            response.json(),
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
    Fetch all available donation categories.
    Call this FIRST when user wants to browse or filter charities by cause/category.
    This is a standalone lookup — does NOT require Python_REPL.
    Returns:
        dict:
            - success (bool): Whether the request was successful.
            - categories (list[dict]): List of category objects, each containing:
                - _id (str): Category ID — pass to get_charities_by_donation_type.
                - name (str): Category display name.
                - description (str): Short description.
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
    IMPORTANT: Only call this tool when user has named a SPECIFIC category
    (e.g. 'chanda', 'fitra', 'hadya', 'saqdah').
    If user has NOT specified which category, do NOT call this tool.
    Instead add 'category_name' to missing_args and ask which category they want.
    NEVER call this for all categories at once.

    Fetch all charities working in a specific donation category/type.
    Requires exact donation type _id from get_donation_categories.
    This is a standalone lookup — does NOT require Python_REPL.
    Args:
        donation_type_id (str): Exact _id from get_donation_categories.
                                NEVER guess this value.
                                Only use _ids returned by get_donation_categories.
        country_code (str): ISO country code to filter by. Default: PK.
    Returns:
        dict:
            - success (bool): Whether the request was successful.
            - charities (list[dict]): List of charity objects, each containing:
                - _id (str): Charity ID.
                - name (str): Charity name.
                - description (str): Charity description.
                - email (str): Contact email.
                - phone (str): Contact phone.
                - website (str): Charity website URL.
    """
    donation_type_id = (donation_type_id or "").strip()
    if not donation_type_id:
        return _fail("donation_type_id is required.")

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
            "Both auction_id AND amount AND password must be known before calling this tool."
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
            "- password is mandatory for transaction authorization — add to missing_args if not provided.\n"
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


# import requests
# from pydantic import BaseModel, Field
# from langchain_core.tools import StructuredTool
# from .tool_helpers import _ok, _fail, _get



# AUCTION_BASE_URL = "http://localhost:3000"
# MOCK_USER_ID = "usr_mujtaba"





# def build_get_wallet_balance_tool() -> StructuredTool:
#     def get_wallet_balance() -> str:
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/wallet/{MOCK_USER_ID}")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class WalletInput(BaseModel):
#         pass

#     return StructuredTool.from_function(
#         func=get_wallet_balance,
#         name="get_wallet_balance",
#         description=(
#             "Fetch the current wallet balance for the authenticated user.\n"
#             "Returns: balance, lockedBalance, availableBalance."
#         ),
#         args_schema=WalletInput,
#     )


# def build_get_active_auctions_tool() -> StructuredTool:
#     def get_active_auctions() -> str:
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/auctions/active")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class AuctionsInput(BaseModel):
#         pass

#     return StructuredTool.from_function(
#         func=get_active_auctions,
#         name="get_active_auctions",
#         description=(
#             "Fetch all currently active auctions.\n"
#             "Returns: list of auctions with _id, title, minBidAmount, "
#             "currentHighestBid, endTimeStamp, incrementType, incrementValue."
#         ),
#         args_schema=AuctionsInput,
#     )


# def build_get_auction_details_tool() -> StructuredTool:
#     def get_auction_details(auction_id: str) -> str:
#         aid = (auction_id or "").strip()
#         if not aid:
#             return _fail("auction_id is required.")
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class AuctionDetailsInput(BaseModel):
#         auction_id: str = Field(..., description="The unique ID of the auction.")

#     return StructuredTool.from_function(
#         func=get_auction_details,
#         name="get_auction_details",
#         description=(
#             "Retrieve full details of a single auction by its ID.\n"
#             "Returns: full auction object including currentHighestBid, totalBids, incrementType, incrementValue."
#         ),
#         args_schema=AuctionDetailsInput,
#     )


# def build_get_auction_bids_tool() -> StructuredTool:
#     def get_auction_bids(auction_id: str) -> str:
#         aid = (auction_id or "").strip()
#         if not aid:
#             return _fail("auction_id is required.")
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/bids")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class AuctionBidsInput(BaseModel):
#         auction_id: str = Field(..., description="The unique ID of the auction.")

#     return StructuredTool.from_function(
#         func=get_auction_bids,
#         name="get_auction_bids",
#         description=(
#             "Retrieve all bids for a specific auction including the highest bid.\n"
#             "Returns: totalBids, highestBid (amount, status, profile), bids list."
#         ),
#         args_schema=AuctionBidsInput,
#     )


# def build_get_auction_items_tool() -> StructuredTool:
#     def get_auction_items(auction_id: str) -> str:
#         aid = (auction_id or "").strip()
#         if not aid:
#             return _fail("auction_id is required.")
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/auctions/{aid}/items")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class AuctionItemsInput(BaseModel):
#         auction_id: str = Field(..., description="The unique ID of the auction.")

#     return StructuredTool.from_function(
#         func=get_auction_items,
#         name="get_auction_items",
#         description=(
#             "Retrieve all items listed under a specific auction.\n"
#             "Returns: totalItems, items list with name, description, condition."
#         ),
#         args_schema=AuctionItemsInput,
#     )


# def build_get_my_bid_history_tool() -> StructuredTool:
#     def get_my_bid_history() -> str:
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/users/{MOCK_USER_ID}/bids")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class BidHistoryInput(BaseModel):
#         pass

#     return StructuredTool.from_function(
#         func=get_my_bid_history,
#         name="get_my_bid_history",
#         description=(
#             "Retrieve the authenticated user's full bid history across all auctions.\n"
#             "Returns: totalBids, bids list with amount, status (Leading/Outbid/Won/Lost), "
#             "auctionTitle, auctionStatus."
#         ),
#         args_schema=BidHistoryInput,
#     )


# def build_place_bid_tool() -> StructuredTool:
#     def place_bid(auction_id: str, amount: float) -> str:
#         aid = (auction_id or "").strip()
#         if not aid:
#             return _fail("auction_id is required.")
#         if not amount or amount <= 0:
#             return _fail("amount must be a positive number.")
#         try:
#             r = requests.post(
#                 f"{AUCTION_BASE_URL}/auction/bid",
#                 json={"user_id": MOCK_USER_ID, "auction_id": aid, "amount": amount},
#                 timeout=5,
#             )
#             if not r.text.strip():
#                 return _fail("Empty response from server.")
#             data = r.json()
#             if not data.get("success"):
#                 return _fail(data.get("message", "Bid failed."), details=data)
#             return _ok(data)
#         except requests.exceptions.ConnectionError:
#             return _fail("Could not connect to auction server.")
#         except requests.exceptions.Timeout:
#             return _fail("Auction server timed out.")
#         except Exception as e:
#             return _fail(str(e))

#     class PlaceBidInput(BaseModel):
#         auction_id: str = Field(..., description="The unique ID of the auction to bid on.")
#         amount: float = Field(..., description="The bid amount in USD.", gt=0)

#     return StructuredTool.from_function(
#         func=place_bid,
#         name="place_bid",
#         description=(
#             "Place a bid on an active auction on behalf of the authenticated user.\n"
#             "Server validates: auction status, minimum bid, increment rules, config limit, wallet balance.\n"
#             "On success: bid amount is locked in wallet. If outbid, amount is auto-released.\n"
#             "Returns: bidId, auctionTitle, amount, nextMinimumBid, newLockedBalance, availableBalance."
#         ),
#         args_schema=PlaceBidInput,
#     )


# def build_finalize_ended_auctions_tool() -> StructuredTool:
#     def finalize_ended_auctions() -> str:
#         try:
#             r = requests.post(f"{AUCTION_BASE_URL}/auction/finalize", timeout=10)
#             if not r.text.strip():
#                 return _fail("Empty response from server.")
#             data = r.json()
#             return _ok(data)
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class FinalizeInput(BaseModel):
#         pass

#     return StructuredTool.from_function(
#         func=finalize_ended_auctions,
#         name="finalize_ended_auctions",
#         description=(
#             "Finalize all auctions that have ended.\n"
#             "Deducts winning bid from winner wallet and releases locked funds for all other bidders.\n"
#             "Returns: success message."
#         ),
#         args_schema=FinalizeInput,
#     )

# def build_get_donation_categories_tool() -> StructuredTool:
#     def get_donation_categories() -> str:
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/donation-categories")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class DonationCategoriesInput(BaseModel):
#         pass

#     return StructuredTool.from_function(
#         func=get_donation_categories,
#         name="get_donation_categories",
#         description=(
#             "Fetch all available donation categories (e.g. Emergency Funds, "
#             "Water Projects, Gaza Relief, Food Aid, Education, Healthcare).\n"
#             "Call this FIRST when user wants to browse or filter charities by cause/category.\n"
#             "Returns: list of categories with _id, name, description, icon."
#         ),
#         args_schema=DonationCategoriesInput,
#     )

# #get tools added for finding charities by donation type.
# def build_get_charities_by_category_tool() -> StructuredTool:
#     def get_charities_by_category(category_id: str) -> str:
#         cid = (category_id or "").strip()
#         if not cid:
#             return _fail("category_id is required.")
#         try:
#             out = _get(f"{AUCTION_BASE_URL}/charities/by-category/{cid}")
#             if out["status"] >= 400:
#                 return _fail(f"HTTP {out['status']}: {out['json']}")
#             return _ok(out["json"])
#         except requests.RequestException as e:
#             return _fail(str(e))

#     class CharitiesByCategoryInput(BaseModel):
#         category_id: str = Field(
#             ...,
#             description="Exact _id of the donation category (e.g. cat_emergency, cat_water, cat_gaza)."
#         )

#     return StructuredTool.from_function(
#         func=get_charities_by_category,
#         name="get_charities_by_category",
#         description=(
#             "Fetch all charities actively working in a specific donation category.\n"
#             "Requires exact category _id from get_donation_categories.\n"
#             "Returns: list of charities with name, description, website, phone, email."
#         ),
#         args_schema=CharitiesByCategoryInput,
#     )




# #=======================Adding Meta Data for Tool Guidance=======================


# metadata_auctions = {
#     "Python_REPL": {
#         "domain": "utility",
#         "type": "compute",
#         "when_to_use": "When arithmetic, transformation, parsing, or quick one-off computations are needed.",
#         "do_not_use": "Do not use for external web/page fetches or tool discovery.",
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": "tool_name=Python_REPL",
#         "hint": (
#                     "- Python_REPL must NEVER have empty args.\n"
#                     "- Python_REPL argument format: {{ \"input\": \"<python code that performs analysis, whose final line of code is ONLY print statement that prints the final numeric result>\" }}"
#                 )
#     },
#     "get_charity_stats": {
#         "domain": "charity",
#         "type": "stats",
#         "when_to_use": "When user asks for donor counts, impact metrics, rankings, blogs, products, addresses, or any numeric summary per charity",
#         "do_not_use": "Never use for wallet, bids, payments, or auctions -- those belong to transaction/auction tools",
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": "tool_name=charity_donor_count",
#         "hint": "none"
#     },
#     "fetch_url": {
#         "domain": "web",
#         "type": "action",
#         "when_to_use": "When a specific URL is already known and you need page content.",
#         "do_not_use": "Do not use when you need discovery/search over unknown URLs.",
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": "tool_name=fetch_url",
#         "hint": "none"
#     },
#     "fetch_urls": {
#         "domain": "web",
#         "type": "paginate",
#         "when_to_use": "When multiple known URLs should be fetched in one operation.",
#         "do_not_use": "Do not use for keyword search/discovery over the open web.",
#         "supports_pagination": True,
#         "requires_auth": False,
#         "example_usage": "tool_name=fetch_urls",
#         "hint": "none"
#     },
#     "get_donation_categories": {
#         "domain": "charity",
#         "type": "lookup",
#         "when_to_use": (
#             "ALWAYS call this first when user says anything like: "
#             "'show categories', 'donation categories', 'what categories', "
#             "'show donation categories', 'browse causes', 'find charities by cause/type'. "
#             "This is a standalone tool — it does NOT require Python_REPL."
#         ),
#         "do_not_use": (
#             "Do not call again if category _ids are already in chat history from a prior call."
#         ),
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": "no args required",
#         "hint": (
#             "Returns _id values like cat_emergency, cat_water, cat_gaza, "
#             "cat_food_aid, cat_education, cat_healthcare. "
#             "Pass the exact _id to get_charities_by_category. "
#             "No synthesis step needed — this is a direct lookup."
#         ),
#     },

#     "get_charities_by_category": {
#         "domain": "charity",
#         "type": "lookup",
#         "when_to_use": (
#             "Call this when user wants charities in a specific cause/category "
#             "AND the exact category _id is already known from get_donation_categories output. "
#             "This is a standalone tool — it does NOT require Python_REPL."
#         ),
#         "do_not_use": (
#             "Never call with a guessed _id. "
#             "Only use _ids returned by get_donation_categories."
#         ),
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": 'category_id="cat_water"',
#         "hint": (
#             "Two-step flow: get_donation_categories first, then this tool. "
#             "No synthesis step needed — this is a direct lookup."
#         ),
#     },
# }

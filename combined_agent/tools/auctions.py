# import os
# import requests
# from langchain_core.tools import tool

# BASE_URL = "https://giverr-api.verior.co"
# AUCTION_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"
# DONOR_PROFILE_ID = "695803a95d120db61afaf03e"

# auction_headers = {
#     "Content-Type": "application/json",
#     "Authorization": f"Bearer {AUCTION_TOKEN}"
# }


# @tool
# def get_active_auctions():
#     """
#     Fetch all currently active auctions.
#     Returns a paginated list of auctions where current time is between
#     startTimeStamp and endTimeStamp.
#     Returns:
#         dict:
#             - success (bool): Whether the request was successful.
#             - auctions (list[dict]): List of auction objects, each containing:
#                 - _id (str): Auction ID.
#                 - title (str): Auction title.
#                 - description (str): Auction description.
#                 - minBidAmount (float): Minimum bid amount.
#                 - incrementType (str): Increment type (Fixed or Percentage).
#                 - incrementValue (float): Increment value.
#                 - reservePrice (float): Reserve price.
#                 - startTimeStamp (str): Auction start time (ISO format).
#                 - endTimeStamp (str): Auction end time (ISO format).
#             - pagination (dict): Pagination details.
#     """
#     params = {
#         "page": 1,
#         "limit": 10,
#         "sortBy": "startTimeStamp",
#         "sortOrder": "asc",
#     }
#     try:
#         response = requests.get(
#             f"{BASE_URL}/api/v3/auctions/list",
#             headers=auction_headers,
#             params=params
#         )
#         response.raise_for_status()
#         data = response.json()

#         auctions = data.get("data", {}).get("auctions", [])
#         pagination = data.get("data", {}).get("pagination", {})

#         return {
#             "success": True,
#             "auctions": auctions,
#             "pagination": pagination
#         }

#     except requests.exceptions.RequestException as e:
#         return {"success": False, "error": f"Request failed: {str(e)}"}
#     except Exception as e:
#         return {"success": False, "error": f"Unexpected error: {str(e)}"}


# @tool
# def get_auction_details(auction_id: str):
#     """
#     Retrieve full details of a single auction by its ID.
#     Returns full auction object including description, condition,
#     incrementType, incrementValue, reservePrice.
#     Args:
#         auction_id (str): The MongoDB ObjectId of the auction.
#                           Must be an exact _id from get_active_auctions.
#     Returns:
#         dict:
#             - success (bool): Whether the request was successful.
#             - auction (dict): Full auction object containing:
#                 - _id (str): Auction ID.
#                 - title (str): Auction title.
#                 - category (str): Category ID.
#                 - condition (str): Item condition.
#                 - description (str): Auction description.
#                 - minBidAmount (float): Minimum bid amount.
#                 - incrementType (str): Fixed or Percentage.
#                 - incrementValue (float): Increment value.
#                 - reservePrice (float): Reserve price.
#                 - startTimeStamp (str): Start time (ISO format).
#                 - endTimeStamp (str): End time (ISO format).
#     """
#     try:
#         response = requests.get(
#             f"{BASE_URL}/api/v3/auctions/{auction_id}",
#             headers=auction_headers
#         )
#         response.raise_for_status()
#         data = response.json()

#         if not data.get("success"):
#             return {"success": False, "error": data.get("message", "Auction not found")}

#         return {"success": True, "auction": data.get("data", {})}

#     except requests.exceptions.RequestException as e:
#         return {"success": False, "error": f"Request failed: {str(e)}"}
#     except Exception as e:
#         return {"success": False, "error": f"Unexpected error: {str(e)}"}


# @tool
# def get_my_bid_history():
#     """
#     Retrieve all active bids placed by the authenticated donor.
#     Only includes bids where auction status is Active and
#     endTimeStamp is in the future.
#     Returns:
#         dict:
#             - success (bool): Whether the request was successful.
#             - bids (list[dict]): List of bid objects, each containing:
#                 - auctionId (str): Auction ID.
#                 - title (str): Auction title.
#                 - bidAmount (float): Amount bid.
#                 - status (str): Bid status (Pending, Won, Lost).
#                 - startTimeStamp (str): Auction start time (ISO format).
#                 - endTimeStamp (str): Auction end time (ISO format).
#             - totalBids (int): Total number of bids.
#     """
#     try:
#         response = requests.get(
#             f"{BASE_URL}/api/v3/auctions/user/{DONOR_PROFILE_ID}/bids",
#             headers=auction_headers
#         )
#         response.raise_for_status()
#         data = response.json()

#         bids = data if isinstance(data, list) else data.get("bids", [])

#         return {"success": True, "bids": bids, "totalBids": len(bids)}

#     except requests.exceptions.RequestException as e:
#         return {"success": False, "error": f"Request failed: {str(e)}"}
#     except Exception as e:
#         return {"success": False, "error": f"Unexpected error: {str(e)}"}


# @tool
# def place_bid(auction_id: str, amount: float, password: str):
#     """
#     Place a bid on an active auction on behalf of the authenticated donor.
#     Args:
#         auction_id (str): The exact _id of the auction to bid on.
#                           Must come from get_active_auctions, never a number.
#         amount (float): The bid amount. Must be greater than zero and
#                         meet the auction's minimum bid and increment rules.
#         password (str): The user's account password for transaction authorization.
#     Returns:
#         dict:
#             - success (bool): Whether the bid was placed successfully.
#             - message (str): Confirmation or error message.
#             - data (dict): Bid details including _id, amount, status.
#     """
#     from tools.transactions import verify_user_password
#     auth = verify_user_password(password)
#     if not auth["success"]:
#         return {
#             "success": False,
#             "message": f"Transaction Denied: {auth['message']}",
#             "data": {}
#         }
#     try:
#         response = requests.post(
#             f"{BASE_URL}/api/v3/auctions/{auction_id}/bid",
#             headers=auction_headers,
#             json={
#                 "donorProfileId": DONOR_PROFILE_ID,
#                 "bidAmount": amount
#             }
#         )
#         response.raise_for_status()
#         data = response.json()

#         return {"success": True, "message": "Bid placed successfully", "data": data}

#     except requests.exceptions.RequestException as e:
#         return {"success": False, "message": f"Request failed: {str(e)}", "data": {}}
#     except Exception as e:
#         return {"success": False, "message": f"Unexpected error: {str(e)}", "data": {}}


# # ======================
# # Donation Category Tools
# # (these still hit the local auction server at localhost:3000)
# # ======================

# from pydantic import BaseModel, Field
# from langchain_core.tools import StructuredTool
# from tools.tool_helpers import _ok, _fail, _get

# LOCAL_AUCTION_BASE_URL = "http://localhost:3000"


# def build_get_donation_categories_tool() -> StructuredTool:
#     def get_donation_categories() -> str:
#         try:
#             out = _get(f"{LOCAL_AUCTION_BASE_URL}/donation-categories")
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
#             "lookup: Fetch all available donation categories (e.g. Emergency Funds, "
#             "Water Projects, Gaza Relief, Food Aid, Education, Healthcare).\n"
#             "Call this FIRST when user wants to browse or filter charities by cause/category.\n"
#             "This is a standalone lookup — does NOT require Python_REPL.\n"
#             "Returns: list of categories with _id, name, description, icon."
#         ),
#         args_schema=DonationCategoriesInput,
#     )


# def build_get_charities_by_category_tool() -> StructuredTool:
#     def get_charities_by_category(category_id: str) -> str:
#         cid = (category_id or "").strip()
#         if not cid:
#             return _fail("category_id is required.")
#         try:
#             out = _get(f"{LOCAL_AUCTION_BASE_URL}/charities/by-category/{cid}")
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
#             "lookup: Fetch all charities actively working in a specific donation category.\n"
#             "Requires exact category _id from get_donation_categories.\n"
#             "This is a standalone lookup — does NOT require Python_REPL.\n"
#             "Returns: list of charities with name, description, website, phone, email."
#         ),
#         args_schema=CharitiesByCategoryInput,
#     )


# # ======================
# # Metadata
# # ======================

# metadata_auctions = {
#     "get_active_auctions": {
#         "domain": "auction",
#         "type": "lookup",
#         "when_to_use": "When user wants to browse or see currently active auctions.",
#         "do_not_use": "Do not use for bid history or auction details.",
#         "supports_pagination": True,
#         "requires_auth": True,
#         "example_usage": "no args required",
#         "hint": "Returns _id values needed for get_auction_details and place_bid."
#     },
#     "get_auction_details": {
#         "domain": "auction",
#         "type": "lookup",
#         "when_to_use": "When user wants full details of a specific auction by its _id.",
#         "do_not_use": "Never call with a number — only exact _id from get_active_auctions.",
#         "supports_pagination": False,
#         "requires_auth": True,
#         "example_usage": 'auction_id="507f1f77bcf86cd799439011"',
#         "hint": "none"
#     },
#     "get_my_bid_history": {
#         "domain": "auction",
#         "type": "lookup",
#         "when_to_use": "When user asks for their bid history, active bids, or bid status.",
#         "do_not_use": "Do not use for listing all auctions.",
#         "supports_pagination": False,
#         "requires_auth": True,
#         "example_usage": "no args required",
#         "hint": "none"
#     },
#     "place_bid": {
#         "domain": "auction",
#         "type": "action",
#         "when_to_use": "When user explicitly wants to place a bid on a specific auction with a stated amount.",
#         "do_not_use": "Never call if auction_id or amount is missing. Never call if user only typed a number without naming an auction.",
#         "supports_pagination": False,
#         "requires_auth": True,
#         "example_usage": 'auction_id="507f...", amount=150, password="userpass"',
#         "hint": "Requires password for transaction authorization."
#     },
#     "get_donation_categories": {
#         "domain": "charity",
#         "type": "lookup",
#         "when_to_use": (
#             "ALWAYS call this first when user says anything like: "
#             "'show categories', 'donation categories', 'what categories', "
#             "'show donation categories', 'browse causes', 'find charities by cause/type'. "
#             "This is a standalone lookup — does NOT require Python_REPL."
#         ),
#         "do_not_use": "Do not call again if category _ids are already in chat history.",
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": "no args required",
#         "hint": (
#             "Returns _id values like cat_emergency, cat_water, cat_gaza, "
#             "cat_food_aid, cat_education, cat_healthcare. "
#             "Pass the exact _id to get_charities_by_category."
#         ),
#     },
#     "get_charities_by_category": {
#         "domain": "charity",
#         "type": "lookup",
#         "when_to_use": (
#             "When user wants charities in a specific cause/category "
#             "AND the exact category _id is already known from get_donation_categories. "
#             "This is a standalone lookup — does NOT require Python_REPL."
#         ),
#         "do_not_use": "Never call with a guessed _id. Only use _ids from get_donation_categories.",
#         "supports_pagination": False,
#         "requires_auth": False,
#         "example_usage": 'category_id="cat_water"',
#         "hint": "Two-step flow: get_donation_categories first, then this tool.",
#     },
# }



import requests
from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool
from .tool_helpers import _ok, _fail, _get



AUCTION_BASE_URL = "http://localhost:3000"
MOCK_USER_ID = "usr_mujtaba"





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

#get tools added for finding charities by donation type.
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




#=======================Adding Meta Data for Tool Guidance=======================


metadata_auctions = {
    "Python_REPL": {
        "domain": "utility",
        "type": "compute",
        "when_to_use": "When arithmetic, transformation, parsing, or quick one-off computations are needed.",
        "do_not_use": "Do not use for external web/page fetches or tool discovery.",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=Python_REPL",
        "hint": (
                    "- Python_REPL must NEVER have empty args.\n"
                    "- Python_REPL argument format: {{ \"input\": \"<python code that performs analysis, whose final line of code is ONLY print statement that prints the final numeric result>\" }}"
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
    "get_donation_categories": {
        "domain": "charity",
        "type": "lookup",
        "when_to_use": (
            "ALWAYS call this first when user says anything like: "
            "'show categories', 'donation categories', 'what categories', "
            "'show donation categories', 'browse causes', 'find charities by cause/type'. "
            "This is a standalone tool — it does NOT require Python_REPL."
        ),
        "do_not_use": (
            "Do not call again if category _ids are already in chat history from a prior call."
        ),
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "no args required",
        "hint": (
            "Returns _id values like cat_emergency, cat_water, cat_gaza, "
            "cat_food_aid, cat_education, cat_healthcare. "
            "Pass the exact _id to get_charities_by_category. "
            "No synthesis step needed — this is a direct lookup."
        ),
    },

    "get_charities_by_category": {
        "domain": "charity",
        "type": "lookup",
        "when_to_use": (
            "Call this when user wants charities in a specific cause/category "
            "AND the exact category _id is already known from get_donation_categories output. "
            "This is a standalone tool — it does NOT require Python_REPL."
        ),
        "do_not_use": (
            "Never call with a guessed _id. "
            "Only use _ids returned by get_donation_categories."
        ),
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": 'category_id="cat_water"',
        "hint": (
            "Two-step flow: get_donation_categories first, then this tool. "
            "No synthesis step needed — this is a direct lookup."
        ),
    },
}

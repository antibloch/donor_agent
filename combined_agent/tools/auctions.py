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
}
# ----------------------------
# Import Libraries
# ----------------------------
import os
import json
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph.message import add_messages
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
import requests
import re
from uuid import uuid4
from dotenv import load_dotenv
load_dotenv()

# ----------------------------
# Langfuse Setup
# ----------------------------
langfuse = Langfuse(
    public_key=os.environ.get("LANGFUSE_PUBLIC_KEY"),
    secret_key=os.environ.get("LANGFUSE_SECRET_KEY"),
    host=os.environ.get("LANGFUSE_HOST"),
)
langfuse_handler = CallbackHandler()

# ----------------------------
# Constants
# ----------------------------
MODEL_NAME = "llama-3.1-8b-instant"
BASE_URL = "http://localhost:3000"
MOCK_USER_ID = "usr_mujtaba"

# ----------------------------
# 1) Graph State
# ----------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Optional[dict]
    selected_auction: Optional[dict]
    skip_planner: Optional[bool]

# ----------------------------
# 2) Tool Definitions
# ----------------------------

@tool
def get_wallet_balance():
    """
    Fetch the current wallet balance for the authenticated user.

    Returns:
        dict:
            - success (bool)
            - wallet_id (str)
            - balance (float): Total balance
            - lockedBalance (float): Amount locked in active bids
            - availableBalance (float): balance minus lockedBalance
            - isActive (bool)
    """
    return requests.get(f"{BASE_URL}/wallet/{MOCK_USER_ID}").json()


@tool
def get_active_auctions():
    """
    Fetch all currently active auctions. Only returns auctions where
    status is Active and current time is within start and end timestamps.

    Returns:
        dict:
            - success (bool)
            - count (int)
            - auctions (list): Each item includes _id, title, description,
              minBidAmount, incrementType, incrementValue, reservePrice,
              startTimeStamp, endTimeStamp, status,
              currentHighestBid (float or null), totalBids (int)
    """
    return requests.get(f"{BASE_URL}/auctions/active").json()


@tool
def get_auction_details(auction_id: str):
    """
    Retrieve full details of a single auction by its ID.
    Includes currentHighestBid and totalBids.

    Args:
        auction_id (str): The unique ID of the auction.

    Returns:
        dict:
            - success (bool)
            - auction (dict): Full auction object
    """
    return requests.get(f"{BASE_URL}/auctions/{auction_id}").json()


@tool
def get_auction_bids(auction_id: str):
    """
    Retrieve all bids for a specific auction including the highest bid.

    Args:
        auction_id (str): The unique ID of the auction.

    Returns:
        dict:
            - success (bool)
            - auction_id (str)
            - totalBids (int)
            - highestBid (dict or null): amount, status, profile
            - bids (list): All bids sorted by amount descending
    """
    return requests.get(f"{BASE_URL}/auctions/{auction_id}/bids").json()


@tool
def get_auction_items(auction_id: str):
    """
    Retrieve all items listed under a specific auction.

    Args:
        auction_id (str): The unique ID of the auction.

    Returns:
        dict:
            - success (bool)
            - auction_id (str)
            - totalItems (int)
            - items (list): Each item has name, description, condition, status
    """
    return requests.get(f"{BASE_URL}/auctions/{auction_id}/items").json()


@tool
def get_my_bid_history():
    """
    Retrieve the authenticated user's full bid history across all auctions.
    Sorted newest first.

    Returns:
        dict:
            - success (bool)
            - user_id (str)
            - totalBids (int)
            - bids (list): Each entry has amount, status (Leading/Outbid/Won/Lost),
              auctionTitle, auctionStatus, and timestamps
    """
    return requests.get(f"{BASE_URL}/users/{MOCK_USER_ID}/bids").json()


@tool
def place_bid(auction_id: str, amount: float):
    """
    Place a bid on an active auction on behalf of the authenticated user.
    Server validates auction status, bid config, minimum bid, increment
    rules, and wallet balance. On success the bid amount is locked in
    the wallet. If outbid later, the locked amount is automatically released.

    Args:
        auction_id (str): The unique ID of the auction to bid on.
        amount (float): The bid amount in USD.

    Returns:
        dict:
            - success (bool)
            - message (str)
            - bidId (str)
            - auctionTitle (str)
            - amount (float)
            - nextMinimumBid (float)
            - newLockedBalance (float)
            - availableBalance (float)
    """
    try:
        response = requests.post(
            f"{BASE_URL}/auction/bid",
            json={
                "user_id": MOCK_USER_ID,
                "auction_id": auction_id,
                "amount": amount,
            },
            timeout=5,
        )
        if not response.text.strip():
            return {"success": False, "error": "Empty response from server"}
        return response.json()
    except requests.exceptions.ConnectionError:
        return {"success": False, "error": "Could not connect to auction server."}
    except requests.exceptions.Timeout:
        return {"success": False, "error": "Auction server timed out."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool
def finalize_ended_auctions():
    """
    Finalize all auctions that have ended. Deducts winning bid from
    winner wallet and releases locked funds for all other bidders.

    Returns:
        dict:
            - success (bool)
            - message (str)
    """
    return requests.post(f"{BASE_URL}/auction/finalize").json()


# ----------------------------
# 3) Tool Registry
# ----------------------------
def build_tools():
    return [
        get_wallet_balance,
        get_active_auctions,
        get_auction_details,
        get_auction_bids,
        get_auction_items,
        get_my_bid_history,
        place_bid,
        finalize_ended_auctions,
    ]

tools = build_tools()
tools_by_name = {t.name: t for t in tools}


def build_tool_context(tools_by_name):
    blocks = []
    for t in tools_by_name.values():
        name = t.name
        description = (t.description or "No description.").split("\n")[0]  # first line only
        args_schema = getattr(t, "args_schema", None)
        if args_schema:
            fields = args_schema.model_fields
            arg_lines = [
                f"  - {fn} ({'required' if f.is_required() else 'optional'})"
                for fn, f in fields.items()
            ]
            args_text = "\n".join(arg_lines) if arg_lines else "  none"
        else:
            args_text = "  none"
        blocks.append(f"{name}\n  Args:\n{args_text}")
    return "\n\n".join(blocks)


# ----------------------------
# 4) Models
# ----------------------------
planner_model = ChatGroq(
    model=MODEL_NAME,
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.0,
    callbacks=[langfuse_handler],
)

responder_model = ChatGroq(
    model=MODEL_NAME,
    api_key=os.environ.get("GROQ_API_KEY"),
    temperature=0.0,
    callbacks=[langfuse_handler],
)

# ----------------------------
# 5) Planner Node
# ----------------------------
def planner_node(state: AgentState):
    chat_history = "\n".join(
        [f"{msg.type}: {msg.content}" for msg in state["messages"]]
    )
    tool_context = build_tool_context(tools_by_name)

    prompt = f"""
You are a planning assistant for a charity auction chatbot.

Your ONLY job is to decide which tools to call based on the user's request.
Return a JSON plan. Nothing else — no explanation, no markdown.

STRICT RULES:
1. Use EXACT tool names from the list below.
2. Only schedule a tool if you have ALL required arguments from the chat history.
3. If a required argument is missing, add it to missing_args, do NOT schedule the tool.
4. No-argument tools: get_wallet_balance, get_active_auctions, get_my_bid_history, finalize_ended_auctions.
5. For place_bid you need BOTH auction_id AND amount explicitly stated by the user.
6. If the user types ONLY a number like "1", "2", "3" — return empty steps. The UI handles number selection.
7. If the user types a bid amount while viewing an auction — return empty steps. The UI handles bid placement.
8. Do NOT schedule place_bid unless the user explicitly said "place a bid" with a clear amount AND auction context.
9. Do NOT schedule get_auction_details, get_auction_items, or get_wallet_balance unless specifically asked.
10. If no tool clearly matches the request, return empty steps and empty missing_args.
11. Never schedule more than 2 tools at once.

AVAILABLE TOOLS:
{tool_context}

OUTPUT FORMAT (strict JSON, no markdown):
{{
  "steps": [
    {{"tool": "tool_name", "args": {{"arg": "value"}}}}
  ],
  "missing_args": []
}}

Chat History:
{chat_history}
"""

    response = planner_model.invoke(prompt)
    print(f"\n  [Planner Raw]: {response.content[:400]}\n")

    try:
        match = re.search(r"\{.*\}", response.content, re.DOTALL)
        plan = json.loads(match.group())
    except Exception as e:
        print(f"  [Planner Parse FAILED]: {e}")
        plan = {"steps": [], "missing_args": []}

    return {"plan": plan}


# ----------------------------
# 6) Validator Node
# ----------------------------
def validator_node(state: AgentState):
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    missing_args = plan.get("missing_args", [])
    messages = []

    valid_steps = []
    for step in steps:
        tool_name = step.get("tool")
        args = step.get("args", {})

        if tool_name not in tools_by_name:
            messages.append(
                AIMessage(content=f"System Note: Tool '{tool_name}' not found. Skipping.")
            )
            continue

        # Skip steps that have no args when args are missing
        if not args and missing_args:
            continue

        valid_steps.append(step)

    updated_plan = {"steps": valid_steps, "missing_args": missing_args}

    if missing_args and not valid_steps:
        return {
            "plan": updated_plan,
            "messages": [
                AIMessage(
                    content=f"System Note: STOP. Ask the user for: {', '.join(missing_args)}"
                )
            ],
        }

    if not valid_steps and not missing_args:
        return {
            "plan": updated_plan,
            "messages": [
                AIMessage(content="System Note: No tools needed. Reply based on chat history.")
            ],
        }

    return {"plan": updated_plan, "messages": messages}


# ----------------------------
# 7) Executor Node
# ----------------------------
active_auctions_cache = {}  # maps "1","2","3" -> auction dict


def get_historical_tool_data(ref_tool, local_results, all_messages):
    if ref_tool in local_results:
        return local_results[ref_tool]
    for msg in reversed(all_messages):
        if isinstance(msg, ToolMessage) and msg.name == ref_tool:
            try:
                return json.loads(msg.content)
            except Exception:
                pass
    return None


def executor_node(state: AgentState):
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    missing_args = plan.get("missing_args", [])

    if not steps:
        return {}

    messages = []
    tool_results = {}

    for step in steps:
        tool_name = step["tool"]
        raw_args = dict(step.get("args", {}))
        resolved_args = {}

        # Resolve $reference args
        for key, value in raw_args.items():
            if isinstance(value, str) and value.startswith("$"):
                ref = value[1:]
                parts = ref.split(".", 1)
                ref_tool = parts[0]
                path = parts[1] if len(parts) > 1 else ""
                data = get_historical_tool_data(ref_tool, tool_results, state["messages"])
                if data is None:
                    return {
                        "messages": [
                            AIMessage(
                                content=f"Execution aborted: no data from '{ref_tool}' for '${ref}'."
                            )
                        ]
                    }
                for part in path.replace("[", ".").replace("]", "").split("."):
                    if not part:
                        continue
                    if part.isdigit():
                        try:
                            data = data[int(part)]
                        except (IndexError, TypeError):
                            return {"messages": [AIMessage(content=f"Index {part} out of bounds.")]}
                    else:
                        data = data.get(part) if isinstance(data, dict) else None
                resolved_args[key] = data
            else:
                resolved_args[key] = value

        # Execute tool — real API call
        tool_fn = tools_by_name[tool_name]
        print(f"  [Executor] {tool_name}({resolved_args})")
        result = tool_fn.invoke(resolved_args)
        parsed = result if isinstance(result, dict) else json.loads(result)
        tool_results[tool_name] = parsed
        print(f"  [Executor] Result: {json.dumps(parsed, default=str)[:300]}")

        # Build user-friendly message for get_active_auctions
        if tool_name == "get_active_auctions":
            active_auctions_cache.clear()
            auctions_list = parsed.get("auctions", [])
            for i, auction in enumerate(auctions_list):
                active_auctions_cache[str(i + 1)] = auction

            if auctions_list:
                lines = []
                for i, a in enumerate(auctions_list):
                    current = f"${a['currentHighestBid']}" if a.get("currentHighestBid") else "No bids yet"
                    lines.append(
                        f"{i+1}. {a['title']}\n"
                        f"   Min Bid: ${a['minBidAmount']} | "
                        f"Current Highest: {current} | "
                        f"Ends: {a['endTimeStamp'][:10]}"
                    )
                messages.append(
                    AIMessage(
                        content=(
                            f"Here are the active auctions:\n\n"
                            + "\n".join(lines)
                            + "\n\nType a number to view details and place a bid."
                        )
                    )
                )
            else:
                messages.append(AIMessage(content="There are no active auctions at the moment."))

        # Append raw tool result for LLM context
        messages.append(
            ToolMessage(
                content=json.dumps(parsed, ensure_ascii=False, default=str),
                name=tool_name,
                tool_call_id=str(uuid4()),
            )
        )

    if missing_args:
        messages.append(
            AIMessage(content=f"System Note: Ask the user for: {', '.join(missing_args)}")
        )

    return {"messages": messages}


# ----------------------------
# 8) Responder Node
# ----------------------------
def responder(state: AgentState):
    user_last_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_last_msg = msg.content.strip()
            break

    messages_to_send = []

    # Helper: get the most recent result for a specific tool this turn
    def get_latest_tool_result(tool_name):
        for msg in reversed(state["messages"]):
            if isinstance(msg, ToolMessage) and msg.name == tool_name:
                try:
                    return json.loads(msg.content)
                except Exception:
                    return None
        return None

    # Helper: check if a tool was called in the most recent executor turn
    def tool_was_just_called(tool_name):
        # Walk backwards — stop if we hit a HumanMessage (means it was a prior turn)
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                break
            if isinstance(msg, ToolMessage) and msg.name == tool_name:
                return True
        return False

    # -------------------------------------------------------
    # CASE 1: place_bid was just executed — show result
    # -------------------------------------------------------
    if tool_was_just_called("place_bid"):
        result = get_latest_tool_result("place_bid")
        if result:
            if result.get("success"):
                state["selected_auction"] = None
                messages_to_send.append(
                    AIMessage(
                        content=(
                            f"Your bid of ${result.get('amount')} on "
                            f"'{result.get('auctionTitle')}' was placed successfully!\n\n"
                            f"Locked Balance:    ${result.get('newLockedBalance')}\n"
                            f"Available Balance: ${result.get('availableBalance')}\n"
                            f"Next Minimum Bid:  ${result.get('nextMinimumBid')}\n\n"
                            f"You are currently the highest bidder.\n"
                            f"If someone outbids you, your ${result.get('amount')} will be "
                            f"automatically unlocked and returned to your available balance."
                            f"Your bid of ${result.get('amount')} on "
                            f"'{result.get('auctionTitle')}' was placed successfully!\n\n"
                            f"Bid Reference:     {result.get('bidId')}\n"   # add this line
                            f"Locked Balance:    ${result.get('newLockedBalance')}\n"
                            f"Available Balance: ${result.get('availableBalance')}\n"
                            f"Next Minimum Bid:  ${result.get('nextMinimumBid')}\n\n"
                        )
                    )
                )
            else:
                messages_to_send.append(
                    AIMessage(
                        content=(
                            f"Could not place bid: "
                            f"{result.get('message', result.get('error', 'Unknown error'))}\n\n"
                            f"Please try a different amount, or type 'cancel' to go back."
                        )
                    )
                )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 2: get_wallet_balance was just called — show balance
    # -------------------------------------------------------
    if tool_was_just_called("get_wallet_balance"):
        result = get_latest_tool_result("get_wallet_balance")
        if result and result.get("success"):
            # If user is mid-bid, remind them of the context too
            auction_reminder = ""
            if state.get("selected_auction"):
                a = state["selected_auction"]
                auction_reminder = (
                    f"\n\nYou are currently viewing '{a.get('title')}'. "
                    f"Type a bid amount to proceed or 'cancel' to go back."
                )
            messages_to_send.append(
                AIMessage(
                    content=(
                        f"Your current wallet:\n\n"
                        f"Total Balance:     ${result.get('balance')}\n"
                        f"Locked in Bids:    ${result.get('lockedBalance')}\n"
                        f"Available to Spend: ${result.get('availableBalance')}"
                        f"{auction_reminder}"
                    )
                )
            )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 3: get_my_bid_history was just called
    # -------------------------------------------------------
    if tool_was_just_called("get_my_bid_history"):
        result = get_latest_tool_result("get_my_bid_history")
        if result and result.get("success"):
            bids = result.get("bids", [])
            if not bids:
                messages_to_send.append(AIMessage(content="You have no bid history yet."))
            else:
                lines = []
                for b in bids:
                    lines.append(
                        f"- {b.get('auctionTitle')} | "
                        f"${b.get('amount')} | "
                        f"Status: {b.get('status')} | "
                        f"Auction: {b.get('auctionStatus')}"
                    )
                messages_to_send.append(
                    AIMessage(
                        content=f"Your bid history ({result.get('totalBids')} total):\n\n"
                        + "\n".join(lines)
                    )
                )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 4: get_auction_bids was just called
    # -------------------------------------------------------
    if tool_was_just_called("get_auction_bids"):
        result = get_latest_tool_result("get_auction_bids")
        if result and result.get("success"):
            highest = result.get("highestBid")
            total = result.get("totalBids", 0)
            if total == 0:
                msg = "No bids have been placed on this auction yet."
            else:
                msg = (
                    f"This auction has {total} bid(s).\n"
                    f"Current highest bid: ${highest['amount']} (Status: {highest['status']})"
                )
            messages_to_send.append(AIMessage(content=msg))
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 5: get_auction_items was just called
    # -------------------------------------------------------
    if tool_was_just_called("get_auction_items"):
        result = get_latest_tool_result("get_auction_items")
        if result and result.get("success"):
            items = result.get("items", [])
            if not items:
                messages_to_send.append(AIMessage(content="No items found for this auction."))
            else:
                lines = [
                    f"- {item.get('name')} ({item.get('condition')}): "
                    f"{item.get('description', '').replace('<p>', '').replace('</p>', '')}"
                    for item in items
                ]
                messages_to_send.append(
                    AIMessage(
                        content=f"Items in this auction:\n\n" + "\n".join(lines)
                    )
                )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 6: get_auction_details was just called (not from number selection)
    # -------------------------------------------------------
    if tool_was_just_called("get_auction_details") and not tool_was_just_called("place_bid"):
        result = get_latest_tool_result("get_auction_details")
        if result and result.get("success"):
            auction_data = result.get("auction", {})
            current_bid = auction_data.get("currentHighestBid")
            increment_type = auction_data.get("incrementType", "fixed")
            increment_value = auction_data.get("incrementValue", 0)
            min_bid = auction_data.get("minBidAmount", 0)

            if current_bid:
                next_min = (
                    round(current_bid + increment_value, 2)
                    if increment_type == "fixed"
                    else round(current_bid * (1 + increment_value / 100), 2)
                )
            else:
                next_min = min_bid

            state["selected_auction"] = auction_data

            text = (
                f"--- {auction_data.get('title', 'N/A')} ---\n\n"
                f"{auction_data.get('description', '').replace('<p>', '').replace('</p>', '')}\n\n"
                f"Minimum Bid:     ${min_bid}\n"
                f"Current Highest: {'$' + str(current_bid) if current_bid else 'No bids yet'}\n"
                f"Your Minimum:    ${next_min}\n"
                f"Ends:            {auction_data.get('endTimeStamp', 'N/A')[:10]}\n\n"
                f"Type the amount you want to bid (minimum ${next_min}), or type 'cancel' to go back."
            )
            messages_to_send.append(AIMessage(content=text))
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 7: User picked auction by number
    # -------------------------------------------------------
    if user_last_msg.isdigit() and user_last_msg in active_auctions_cache:
        auction = active_auctions_cache[user_last_msg]
        details_result = get_auction_details.invoke({"auction_id": auction["_id"]})
        details = details_result if isinstance(details_result, dict) else json.loads(details_result)
        auction_data = details.get("auction", details)

        current_bid = auction_data.get("currentHighestBid")
        increment_type = auction_data.get("incrementType", "fixed")
        increment_value = auction_data.get("incrementValue", 0)
        min_bid = auction_data.get("minBidAmount", 0)

        if current_bid:
            next_min = (
                round(current_bid + increment_value, 2)
                if increment_type == "fixed"
                else round(current_bid * (1 + increment_value / 100), 2)
            )
        else:
            next_min = min_bid

        state["selected_auction"] = auction_data

        text = (
            f"--- {auction_data.get('title', 'N/A')} ---\n\n"
            f"{auction_data.get('description', '').replace('<p>', '').replace('</p>', '')}\n\n"
            f"Minimum Bid:     ${min_bid}\n"
            f"Current Highest: {'$' + str(current_bid) if current_bid else 'No bids yet'}\n"
            f"Your Minimum:    ${next_min}\n"
            f"Ends:            {auction_data.get('endTimeStamp', 'N/A')[:10]}\n\n"
            f"Type the amount you want to bid (minimum ${next_min}), or type 'cancel' to go back."
        )
        messages_to_send.append(AIMessage(content=text))
        return {"messages": messages_to_send}

    # Invalid number
    if user_last_msg.isdigit() and active_auctions_cache and user_last_msg not in active_auctions_cache:
        messages_to_send.append(
            AIMessage(
                content=f"Invalid selection. Please choose a number between 1 and {len(active_auctions_cache)}."
            )
        )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 8: User is in bid placement flow (typed an amount)
    # -------------------------------------------------------
    if state.get("selected_auction"):
        auction = state["selected_auction"]

        if user_last_msg.lower() in ["cancel", "back", "no"]:
            state["selected_auction"] = None
            messages_to_send.append(
                AIMessage(content="Bid cancelled. You can view active auctions again.")
            )
            return {"messages": messages_to_send}

        try:
            bid_amount = float(user_last_msg)
        except ValueError:
            messages_to_send.append(
                AIMessage(
                    content="Please enter a valid numeric bid amount, or type 'cancel' to go back."
                )
            )
            return {"messages": messages_to_send}

        # Make the real API call
        print(f"  [Responder] Placing bid: {auction['_id']} amount={bid_amount}")
        bid_result = place_bid.invoke({"auction_id": auction["_id"], "amount": bid_amount})
        bid_result = bid_result if isinstance(bid_result, dict) else json.loads(bid_result)
        print(f"  [Responder] Bid result: {bid_result}")

        if bid_result.get("success"):
            state["selected_auction"] = None
            messages_to_send.append(
                AIMessage(
                    content=(
                        f"Your bid of ${bid_amount} on '{bid_result.get('auctionTitle')}' "
                        f"was placed successfully!\n\n"
                        f"Locked Balance:    ${bid_result.get('newLockedBalance')}\n"
                        f"Available Balance: ${bid_result.get('availableBalance')}\n"
                        f"Next Minimum Bid:  ${bid_result.get('nextMinimumBid')}\n\n"
                        f"You are currently the highest bidder.\n"
                        f"If someone outbids you, your ${bid_amount} will be "
                        f"automatically unlocked and returned to your available balance."
                    )
                )
            )
        else:
            messages_to_send.append(
                AIMessage(
                    content=(
                        f"Could not place bid: "
                        f"{bid_result.get('message', bid_result.get('error', 'Unknown error'))}\n\n"
                        f"Please try a different amount, or type 'cancel' to go back."
                    )
                )
            )
        return {"messages": messages_to_send}

    # -------------------------------------------------------
    # CASE 9: Default — LLM handles general conversation
    # -------------------------------------------------------
    message_summary = state["messages"]
    system_prompt = """
You are a specialized Auction Assistant for a charitable organization.

You ONLY assist with:
- Viewing active auctions
- Viewing auction details and items
- Checking bid history
- Checking wallet balance
- Placing bids

If the user asks about anything outside this scope, politely decline.
Do NOT use emojis. Keep responses short and factual.
Do NOT invent auction data, bid amounts, or any numbers.
If you do not know something, say so and suggest the user asks to view auctions.
"""
    final_prompt = [
        HumanMessage(
            content=f"{system_prompt}\n\nConversation History:\n{message_summary}"
        )
    ]
    summary = responder_model.invoke(final_prompt)
    messages_to_send.append(summary)
    return {"messages": messages_to_send}


# ----------------------------
# 9) Routing
# ----------------------------
def route_after_validator(state: AgentState):
    steps = state.get("plan", {}).get("steps", [])
    return "executor" if steps else "responder"


def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("responder", responder)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "validator")
    workflow.add_conditional_edges("validator", route_after_validator)
    workflow.add_edge("executor", "responder")
    workflow.add_edge("responder", END)

    return workflow.compile()


# ----------------------------
# 10) Main
# ----------------------------
def main():
    graph = build_graph()
    chat_memory = []

    print("\n==================================================")
    print("  CHARITY AUCTION AGENT")
    print("  Type 'exit' to quit.")
    print("==================================================\n")

    while True:
        try:
            user_input = input("You: ")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if user_input.lower() in ["exit", "quit", "q"]:
            print("Goodbye!")
            break

        user_input_stripped = user_input.strip()

        in_bid_flow = any(
            isinstance(msg, AIMessage) and "Type the amount you want to bid" in msg.content
            for msg in reversed(chat_memory[-6:])
        )

        skip = user_input_stripped.isdigit() or in_bid_flow

        chat_memory.append(HumanMessage(content=user_input_stripped))
        print("\n(thinking...)\n")

        try:
            for step in graph.stream(
                {
                    "messages": chat_memory,
                    "plan": None,
                    "selected_auction": None,
                    "skip_planner": skip,
                },
                stream_mode="updates",
            ):
                for node_name, node_output in step.items():
                    if not node_output:
                        continue

                    if node_name == "planner" and "plan" in node_output:
                        plan = node_output["plan"]
                        scheduled = [s["tool"] for s in plan.get("steps", [])]
                        missing = plan.get("missing_args", [])
                        if scheduled:
                            print(f"  [Planner] Scheduled: {scheduled}")
                        if missing:
                            print(f"  [Planner] Missing: {missing}")
                        if not scheduled and not missing:
                            print(f"  [Planner] No tools needed")

                    if "messages" in node_output:
                        for msg in node_output["messages"]:
                            chat_memory.append(msg)
                            if isinstance(msg, ToolMessage):
                                print(f"  [Tool Done] {msg.name}")
                            elif isinstance(msg, AIMessage):
                                if "System Note:" not in msg.content:
                                    print(f"\nAgent: {msg.content}\n")

        except Exception as e:
            print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()

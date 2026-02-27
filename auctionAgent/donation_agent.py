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
    # Check for injected plan FIRST — before skip check
    existing_plan = state.get("plan")
    if existing_plan and existing_plan.get("steps"):
        print(f"\n  [Planner] Using injected plan: {[s['tool'] for s in existing_plan['steps']]}\n")
        return {"plan": existing_plan}

    # Then skip check
    if state.get("skip_planner"):
        return {"plan": {"steps": [], "missing_args": []}}

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
12. If the most recent tool result shows a successful place_bid, do NOT schedule 
    place_bid again unless the user explicitly asks to place a NEW bid with a different amount.
13. Words like "cancel", "back", "thanks", "thank you", "okay", "yes", "no" are 
    conversational — return empty steps and empty missing_args for these.

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
        # if tool_name == "get_active_auctions":
        #     active_auctions_cache.clear()
        #     auctions_list = parsed.get("auctions", [])
        #     for i, auction in enumerate(auctions_list):
        #         active_auctions_cache[str(i + 1)] = auction

        #     if auctions_list:
        #         lines = []
        #         for i, a in enumerate(auctions_list):
        #             current = f"${a['currentHighestBid']}" if a.get("currentHighestBid") else "No bids yet"
        #             lines.append(
        #                 f"{i+1}. {a['title']}\n"
        #                 f"   Min Bid: ${a['minBidAmount']} | "
        #                 f"Current Highest: {current} | "
        #                 f"Ends: {a['endTimeStamp'][:10]}"
        #             )
        #         messages.append(
        #             AIMessage(
        #                 content=(
        #                     f"Here are the active auctions:\n\n"
        #                     + "\n".join(lines)
        #                     + "\n\nType a number to view details and place a bid."
        #                 )
        #             )
        #         )
        #     else:
        #         messages.append(AIMessage(content="There are no active auctions at the moment."))

        if tool_name == "get_active_auctions":
            active_auctions_cache.clear()
            auctions_list = parsed.get("auctions", [])
            for i, auction in enumerate(auctions_list):
                active_auctions_cache[str(i + 1)] = auction # Responder handles display — do NOT append AIMessage here
    

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


#helper functions for responder node
def get_next_steps(selected_auction=None, just_bid=False):
    """Returns contextual next step options based on current state."""
    if just_bid:
        return (
            "\n\nWhat would you like to do next?\n"
            "- Type a number to view another auction (show auctions first)\n"
            "- Type 'my bids' to see your bid history\n"
            "- Type 'balance' to check your wallet\n"
            "- Type 'auctions' to browse active auctions"
        )
    if selected_auction:
        title = selected_auction.get("title", "this auction")
        return (
            f"\n\nYou are viewing: {title}\n"
            "- Type a bid amount to place a bid\n"
            "- Type 'cancel' to go back to auctions"
        )
    return (
        "\n\nWhat would you like to do?\n"
        "- Type 'auctions' to see active auctions\n"
        "- Type 'balance' to check your wallet\n"
        "- Type 'my bids' to see your bid history\n"
        "- Type 'finalize' to close ended auctions"
    )
def get_bid_error_guidance(selected_auction=None):
    """Shown after a failed bid attempt."""
    if selected_auction:
        return (
            "\n\n─────────────────────────\n"
            "  • Type a different amount to retry\n"
            "  • Type 'cancel' to go back to auctions"
        )
    return (
        "\n\n─────────────────────────\n"
        "  • Try again with a valid amount\n"
        "  • Type 'auctions' to browse and select an auction first"
    )


def get_auction_list_footer():
    """Always shown after the auction list."""
    return (
        "\n\nType a number (1, 2, 3) to view details and place a bid."
        "\nOr type 'balance' to check your wallet first."
    )


def get_capabilities():
    """Full capabilities list shown on help or greeting."""
    return (
        "\n\n─────────────────────────\n"
        "Here is what I can help you with:\n"
        "  • Type 'auctions' — see all active auctions\n"
        "  • Type 'balance' — check your wallet balance\n"
        "  • Type 'my bids' — view your bidding history\n"
        "  • Type 'finalize' — close auctions that have ended\n"
        "  • Type a number after viewing auctions to select one and bid"
    )


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

    def get_latest_tool_result(tool_name):
        for msg in reversed(state["messages"]):
            if isinstance(msg, ToolMessage) and msg.name == tool_name:
                try:
                    return json.loads(msg.content)
                except Exception:
                    return None
        return None

    def tool_was_just_called(tool_name):
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                break
            if isinstance(msg, ToolMessage) and msg.name == tool_name:
                return True
        return False

    
    # -------------------------------------------------------
    # CASE 0: get_active_auctions just called — show list once
    # -------------------------------------------------------
    if tool_was_just_called("get_active_auctions"):
        auctions_list = list(active_auctions_cache.values())
        if not auctions_list:
            messages_to_send.append(
                AIMessage(content="There are no active auctions at the moment." + get_next_steps())
            )
        else:
            lines = []
            for i, a in enumerate(auctions_list):
                current = f"${a['currentHighestBid']}" if a.get("currentHighestBid") else "No bids yet"
                lines.append(
                    f"{i+1}. {a['title']}\n"
                    f"   Min Bid: ${a['minBidAmount']} | Current Highest: {current} | Ends: {a['endTimeStamp'][:10]}"
                )
            messages_to_send.append(
                AIMessage(
                    content="Here are the active auctions:\n\n" + "\n".join(lines) + get_auction_list_footer()
                )
            )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 1: place_bid just executed — show result
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
                            f"Bid Reference:     {result.get('bidId')}\n"
                            f"Locked Balance:    ${result.get('newLockedBalance')}\n"
                            f"Available Balance: ${result.get('availableBalance')}\n"
                            f"Next Minimum Bid:  ${result.get('nextMinimumBid')}\n\n"
                            f"You are currently the highest bidder.\n"
                            f"If someone outbids you, your ${result.get('amount')} will be "
                            f"automatically unlocked and returned to your available balance."
                            + get_next_steps(just_bid=True)
                        )
                    )
                )
            else:
                error_msg = result.get("message", result.get("error", "Unknown error"))
                messages_to_send.append(
                    AIMessage(
                        content=(
                            f"Could not place bid: {error_msg}"
                            + get_bid_error_guidance(state.get("selected_auction"))
                        )
                    )
                )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 2: get_wallet_balance just called — show balance
    # -------------------------------------------------------
    if tool_was_just_called("get_wallet_balance"):
        result = get_latest_tool_result("get_wallet_balance")
        if result and result.get("success"):
            messages_to_send.append(
                AIMessage(
                    content=(
                        f"Your current wallet:\n\n"
                        f"Total Balance:      ${result.get('balance')}\n"
                        f"Locked in Bids:     ${result.get('lockedBalance')}\n"
                        f"Available to Spend: ${result.get('availableBalance')}"
                        + get_next_steps(selected_auction=state.get("selected_auction"))
                    )
                )
            )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 3: get_my_bid_history just called
    # -------------------------------------------------------
    if tool_was_just_called("get_my_bid_history"):
        result = get_latest_tool_result("get_my_bid_history")
        if result and result.get("success"):
            bids = result.get("bids", [])
            if not bids:
                messages_to_send.append(
                    AIMessage(content="You have no bid history yet." + get_next_steps())
                )
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
                        content=(
                            f"Your bid history ({result.get('totalBids')} total):\n\n"
                            + "\n".join(lines)
                            + get_next_steps()
                        )
                    )
                )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}
    
    # After Case 3, add:
    if tool_was_just_called("finalize_ended_auctions"):
        result = get_latest_tool_result("finalize_ended_auctions")
        if result and result.get("success"):
            messages_to_send.append(
                AIMessage(
                    content=(
                        "All ended auctions have been finalized successfully.\n"
                        "Winners have been notified and locked funds released."
                        + get_next_steps()
                    )
                )
            )
        else:
            messages_to_send.append(
                AIMessage(content="Could not finalize auctions. Please try again." + get_next_steps())
            )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 4: get_auction_bids just called
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
            messages_to_send.append(
                AIMessage(content=msg + get_next_steps(selected_auction=state.get("selected_auction")))
            )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 5: get_auction_items just called
    # -------------------------------------------------------
    if tool_was_just_called("get_auction_items"):
        result = get_latest_tool_result("get_auction_items")
        if result and result.get("success"):
            items = result.get("items", [])
            if not items:
                messages_to_send.append(
                    AIMessage(content="No items found for this auction." + get_next_steps())
                )
            else:
                lines = [
                    f"- {item.get('name')} ({item.get('condition')}): "
                    f"{item.get('description', '').replace('<p>', '').replace('</p>', '')}"
                    for item in items
                ]
                messages_to_send.append(
                    AIMessage(
                        content=(
                            "Items in this auction:\n\n"
                            + "\n".join(lines)
                            + get_next_steps(selected_auction=state.get("selected_auction"))
                        )
                    )
                )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 6: get_auction_details just called (planner path, not number selection)
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
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 7: User picked auction by number from cache
    # -------------------------------------------------------
    if user_last_msg.isdigit() and len(user_last_msg) == 1 and user_last_msg in active_auctions_cache:
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
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # Invalid number typed (single digit not in cache)
    if user_last_msg.isdigit() and len(user_last_msg) == 1 and active_auctions_cache and user_last_msg not in active_auctions_cache:
        messages_to_send.append(
            AIMessage(
                content=(
                    f"Invalid selection. Please choose a number between 1 and {len(active_auctions_cache)}."
                    + get_auction_list_footer()
                )
            )
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 8: User is in bid placement flow
    # -------------------------------------------------------
    if state.get("selected_auction") and not tool_was_just_called("place_bid"):
        auction = state["selected_auction"]

        # Cancel — fetch fresh list and show it
        if user_last_msg.lower() in ["cancel", "back", "no"]:
            auctions_result = get_active_auctions.invoke({})
            auctions_list = auctions_result.get("auctions", [])
            active_auctions_cache.clear()
            for i, a in enumerate(auctions_list):
                active_auctions_cache[str(i + 1)] = a

            if auctions_list:
                lines = []
                for i, a in enumerate(auctions_list):
                    current = f"${a['currentHighestBid']}" if a.get("currentHighestBid") else "No bids yet"
                    lines.append(
                        f"{i+1}. {a['title']}\n"
                        f"   Min Bid: ${a['minBidAmount']} | Current Highest: {current} | Ends: {a['endTimeStamp'][:10]}"
                    )
                content = (
                    "Bid cancelled. Here are the active auctions:\n\n"
                    + "\n".join(lines)
                    + get_auction_list_footer()
                )
            else:
                content = "Bid cancelled. There are no active auctions at the moment." + get_next_steps()

            messages_to_send.append(AIMessage(content=content))
            return {"messages": messages_to_send, "selected_auction": None}

        # Balance check inside bid flow
        balance_phrases = ["balance", "money", "wallet", "how much", "funds"]
        if any(p in user_last_msg.lower() for p in balance_phrases):
            wallet_result = get_wallet_balance.invoke({})
            if wallet_result.get("success"):
                messages_to_send.append(
                    AIMessage(
                        content=(
                            f"Your current wallet:\n\n"
                            f"Total Balance:      ${wallet_result.get('balance')}\n"
                            f"Locked in Bids:     ${wallet_result.get('lockedBalance')}\n"
                            f"Available to Spend: ${wallet_result.get('availableBalance')}\n\n"
                            f"─────────────────────────\n"
                            f"You are viewing: {auction.get('title', 'the selected auction')}\n"
                            f"  • Type a bid amount to place a bid\n"
                            f"  • Type 'cancel' to go back"
                        )
                    )
                )
            return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

        # Try parsing as bid amount
        try:
            bid_amount = float(user_last_msg)
        except ValueError:
            messages_to_send.append(
                AIMessage(
                    content=(
                        "Please enter a valid numeric bid amount, or type 'cancel' to go back."
                    )
                )
            )
            return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

        # Place the bid
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
                        f"Bid Reference:     {bid_result.get('bidId')}\n"
                        f"Locked Balance:    ${bid_result.get('newLockedBalance')}\n"
                        f"Available Balance: ${bid_result.get('availableBalance')}\n"
                        f"Next Minimum Bid:  ${bid_result.get('nextMinimumBid')}\n\n"
                        f"You are currently the highest bidder.\n"
                        f"If someone outbids you, your ${bid_amount} will be "
                        f"automatically unlocked and returned to your available balance."
                        + get_next_steps(just_bid=True)
                    )
                )
            )
        else:
            messages_to_send.append(
                AIMessage(
                    content=(
                        f"Could not place bid: "
                        f"{bid_result.get('message', bid_result.get('error', 'Unknown error'))}"
                        + get_bid_error_guidance(state.get("selected_auction"))
                    )
                )
            )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # -------------------------------------------------------
    # CASE 9: Deterministic fallback — pattern matching first, LLM last resort
    # -------------------------------------------------------

    # Acknowledgements
    if user_last_msg.lower() in ALWAYS_SKIP:
        messages_to_send.append(
            AIMessage(content="Glad to help!" + get_next_steps())
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # Personal info
    personal_patterns = ["my name", "i am ", "i'm ", "call me", "name is"]
    if any(p in user_last_msg.lower() for p in personal_patterns):
        messages_to_send.append(
            AIMessage(
                content=(
                    "I'm here specifically to assist with charity auctions "
                    "and don't store personal information."
                    + get_capabilities()
                )
            )
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # Off-topic
    off_topic_patterns = [
        "weather", "sports", "news", "politics", "code", "programming",
        "recipe", "movie", "music", "game", "crypto", "stock",
        "who are you", "what are you", "tell me about yourself"
    ]
    if any(p in user_last_msg.lower() for p in off_topic_patterns):
        messages_to_send.append(
            AIMessage(
                content=(
                    "I can only assist with charity auction related actions."
                    + get_capabilities()
                )
            )
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}
    
    #greetings pattern handling
    greeting_patterns = ["hi", "hello", "hey", "good morning", "good evening", "salam", "assalam"]
    if any(p in user_last_msg.lower() for p in greeting_patterns):
        messages_to_send.append(
            AIMessage(
                content=(
                    "Welcome to the charity auction platform. "
                    "I'm here to help you browse and bid on active auctions."
                    + get_capabilities()
                )
            )
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # Capabilities / help
    capability_patterns = [
        "what can you", "what do you", "how do i", "how to",
        "help", "options", "menu", "what are my options"
    ]
    if any(p in user_last_msg.lower() for p in capability_patterns):
        messages_to_send.append(
            AIMessage(content="Here is everything I can help you with:" + get_capabilities())
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # Empty or very short
    if len(user_last_msg.strip()) <= 2:
        messages_to_send.append(
            AIMessage(content="How can I assist you?" + get_next_steps())
        )
        return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

    # True unknown — LLM, strictly 1 sentence, next steps appended
    system_prompt = """
You are a charity auction assistant. Respond in ONE sentence maximum.
If the request is not about auctions, respond with exactly: "I can only help with auction related actions."
Never mention specific auction names, prices, or bid amounts.
Never invent any data.
"""
    final_prompt = [
        HumanMessage(content=f"{system_prompt}\n\nUser said: {user_last_msg}")
    ]
    summary = responder_model.invoke(final_prompt)
    summary.content = summary.content.strip() + get_next_steps()
    messages_to_send.append(summary)
    return {"messages": messages_to_send, "selected_auction": state.get("selected_auction")}

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
# ----------------------------
# Keyword & Pattern Constants (outside main, add above it)
# ----------------------------
KEYWORD_TO_TOOL = {
    "auctions": "get_active_auctions",
    "auction": "get_active_auctions",
    "view": "get_active_auctions",
    "browse": "get_active_auctions",
    "list": "get_active_auctions",
    "active auctions": "get_active_auctions",
    "show auctions": "get_active_auctions",
    "view auctions": "get_active_auctions",
    "see auctions": "get_active_auctions",
    "show active auctions": "get_active_auctions",

    "balance": "get_wallet_balance",
    "my balance": "get_wallet_balance",
    "wallet": "get_wallet_balance",
    "check balance": "get_wallet_balance",
    "check my balance": "get_wallet_balance",
    "my wallet": "get_wallet_balance",
    "how much money do i have": "get_wallet_balance",
    "how much do i have": "get_wallet_balance",
    "whats my balance": "get_wallet_balance",
    "what is my balance": "get_wallet_balance",

    "my bids": "get_my_bid_history",
    "bid history": "get_my_bid_history",
    "history": "get_my_bid_history",
    "my bid history": "get_my_bid_history",
    "show my bids": "get_my_bid_history",
    "view my bids": "get_my_bid_history",
    "my bidding history": "get_my_bid_history",

    "finalize": "finalize_ended_auctions",
    "close auctions": "finalize_ended_auctions",
    "finalize auctions": "finalize_ended_auctions",
    "end auctions": "finalize_ended_auctions",
}

ALWAYS_SKIP = {
    "cancel", "back", "no", "yes", "ok", "okay",
    "thank you", "thanks", "thankyou", "bye", "goodbye",
    "got it", "noted", "understood", "great", "perfect",
    "awesome", "cool", "nice", "good", "alright"
}

# ----------------------------
# 10) Main
# ----------------------------
def main():
    graph = build_graph()
    chat_memory = []
    session = {"selected_auction": None}

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
        user_lower = user_input_stripped.lower()

        # Strip punctuation for matching
        user_clean = re.sub(r'[^\w\s]', '', user_lower).strip()
        forced_tool = KEYWORD_TO_TOOL.get(user_clean) or KEYWORD_TO_TOOL.get(user_lower)

        if not forced_tool:
            for keyword, tool_name in KEYWORD_TO_TOOL.items():
                if user_clean == keyword or user_lower == keyword:
                    forced_tool = tool_name
                    break

        in_bid_flow = any(
            isinstance(msg, AIMessage) and "Type the amount you want to bid" in msg.content
            for msg in reversed(chat_memory[-6:])
        )

        skip = (
            user_input_stripped.isdigit()
            or in_bid_flow
            or user_lower in ALWAYS_SKIP
            or forced_tool is not None
        )

        if forced_tool:
            injected_plan = {
                "steps": [{"tool": forced_tool, "args": {}}],
                "missing_args": []
            }
        else:
            injected_plan = None

        # Trim context window
        MAX_MEMORY = 20
        if len(chat_memory) > MAX_MEMORY:
            chat_memory = chat_memory[-MAX_MEMORY:]

        chat_memory.append(HumanMessage(content=user_input_stripped))
        print("\n(thinking...)\n")

        try:
            for step in graph.stream(
                {
                    "messages": chat_memory,
                    "plan": injected_plan,
                    "selected_auction": session["selected_auction"],
                    "skip_planner": skip,
                },
                stream_mode="updates",
            ):
                for node_name, node_output in step.items():
                    if not node_output:
                        continue

                    if node_name == "responder" and node_output:
                        if "selected_auction" in node_output:
                            session["selected_auction"] = node_output.get("selected_auction")

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
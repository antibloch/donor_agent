# ----------------------------
# Import Libraries
# ----------------------------
import os
import json
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph.message import add_messages
# from langchain_nvidia import ChatNVIDIA
# from langchain.chat_models import ChatNVIDIA
from langchain_groq import ChatGroq
from langgraph.graph import StateGraph, END
from langchain_core.tools import tool
import requests
import datetime
import re
from uuid import uuid4
from dotenv import load_dotenv
load_dotenv()

# ----------------------------
# Variables Definition & File Handling
# ----------------------------
MODEL_NAME='llama-3.1-8b-instant'

def load_dummy_data(path="data.json"):
    with open(path, "r") as f:
        data = json.load(f)

    wallets = data.get("wallets", {})
    virtual_cards = data.get("virtual_cards", {})

    # Convert date strings to datetime
    for wallet in wallets.values():
        wallet["createdAt"] = datetime.datetime.fromisoformat(
            wallet["createdAt"].replace("Z", "")
        )

    for card in virtual_cards.values():
        card["createdAt"] = datetime.datetime.fromisoformat(
            card["createdAt"].replace("Z", "")
        )
        card["updatedAt"] = datetime.datetime.fromisoformat(
            card["updatedAt"].replace("Z", "")
        )

    return wallets, virtual_cards
wallets, virtual_cards = load_dummy_data()

def save_dummy_data(data):
    with open('saved_data', "w") as f:
        json.dump(data, f, indent=2)

# ----------------------------
# 1) Graph state
# ----------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Optional[dict]

# ----------------------------
# 2) Tools Definition
# ----------------------------
@tool
def check_wallet_balance(user_id: str):
    """
    Retrieve the wallet details and current balance for a given user.

    This tool searches for an active, non-deleted wallet associated
    with the provided user ID and returns wallet metadata including
    available and locked balances.

    Args:
        user_id (str): Unique identifier of the user whose wallet
            information is being requested.

    Returns:
        dict: A dictionary containing:
            - wallet_id (str): Unique wallet identifier
            - balance (float): Available wallet balance
            - lockedBalance (float): Amount currently locked
            - isActive (bool): Whether the wallet is active

        If no wallet is found:
            - error (str): Error message explaining the issue

    Notes:
        This function does not modify wallet state.
    """
    return requests.get(
        f"http://localhost:3000/wallet/{user_id}"
    ).json()

@tool
def fund_wallet(user_id: str, amount: float, card_id: str):
    """
    Fund a user's wallet by charging a valid virtual card.

    This tool validates the wallet, verifies card ownership and status,
    checks spending limits, and credits the specified amount to the wallet.
    A transaction record is created and appended to the wallet's transaction history.

    Args:
        user_id (str): Unique identifier of the user whose wallet will be funded.
        amount (float): Amount to credit to the wallet. Must be greater than zero
            and within the card's spending limit.
        card_id (str): Unique identifier of the virtual card used for funding.

    Returns:
        dict: A dictionary containing:
            - message (str): Confirmation message if successful
            - new_balance (float): Updated wallet balance
            - transaction (dict):
                - transactionId (str): Unique transaction ID
                - type (str): Transaction type ("CREDIT")
                - amount (float): Credited amount
                - currency (str): Currency used
                - timestamp (str): UTC ISO timestamp

        If validation fails:
            - error (str): Explanation of failure (e.g., wallet not found,
              invalid card, blocked card, limit exceeded)

    Notes:
        This tool performs state mutation by updating wallet balance
        and transaction history.
    """
    return requests.post(
        "http://localhost:3000/wallet/fund",
        json={
            "user_id": user_id,
            "amount": amount,
            "card_id": card_id
        }
    ).json()

@tool
def get_user_virtual_cards(user_id: str):
    """
    Retrieve all virtual cards associated with a specific user.

    This tool returns a list of virtual cards linked to the given user ID,
    including both active and blocked cards.

    Args:
        user_id (str): Unique identifier of the user whose cards
            are being requested.

    Returns:
        dict: A dictionary containing:
            - cards (list): List of virtual card objects, each including:
                - _id (str): Card identifier
                - isActive (bool): Whether the card is active
                - isBlocked (bool): Whether the card is blocked
                - limit (float): Spending limit
                - currency (str): Card currency
                - updatedAt (datetime): Last updated timestamp

    Notes:
        This tool does not modify card data.
    """
    return requests.get(
        f"http://localhost:3000/cards/{user_id}"
    ).json()

@tool
def add_virtual_card(user_id: str, card_number: str, card_holder: str, expiry_date: str, cvv: str, card_type: str, currency: str, limit: float):
    """
    Add a new virtual payment card for a user.

    Args:
        user_id (str): ID of the user adding the card.
        card_number (str): Full card number.
        card_holder (str): Name on card.
        expiry_date (str): Expiry date in YYYY-MM-DD format.
        cvv (str): Card CVV.
        card_type (str): Card brand (VISA, MASTERCARD, AMEX).
        currency (str): Card currency (e.g., USD).
        limit (float): Spending limit of the card.

    Returns:
        dict: Newly created virtual card object.
    """

    return requests.post(
        "http://localhost:3000/card/add",
        json={
            "user_id": user_id,
            "card_number": card_number,
            "card_holder": card_holder,
            "expiry_date": expiry_date,
            "cvv": cvv,
            "card_type": card_type,
            "currency": currency,
            "limit": limit
        }
    ).json()

@tool
def get_active_auctions():
    """
    Fetch all currently active auctions from the backend Node service.

    Returns:
        list: List of active auctions with fields:
            - _id
            - title
            - description
            - minBidAmount
            - incrementType
            - incrementValue
            - reservePrice
            - startTimeStamp
            - endTimeStamp
    """
    return requests.get("http://localhost:3000/auctions/active").json()

@tool
def get_auction_details(auction_id: str):
    """
    Retrieve full details of a single auction by its ID.

    Args:
        auction_id (str): The unique ID of the auction.

    Returns:
        dict: Full auction details if found, else:
            {"error": "Auction not found"}
    """
    return requests.get(f"http://localhost:3000/auctions/{auction_id}").json()


def build_tools():
    # Both are "single input" tools
    return [check_wallet_balance, fund_wallet, get_user_virtual_cards, add_virtual_card, get_active_auctions,get_auction_details]

# ----------------------------
# 3) Tools Processing for Planner
# ----------------------------
tools = build_tools()
tools_by_name = {t.name: t for t in tools}
def build_tool_context(tools_by_name):
    blocks = []

    for tool in tools_by_name.values():
        name = tool.name
        description = tool.description or "No description."

        args_schema = getattr(tool, "args_schema", None)

        if args_schema:
            fields = args_schema.model_fields
            arg_lines = []
            for field_name, field in fields.items():
                required = "required" if field.is_required() else "optional"
                arg_lines.append(f"- {field_name} ({required})")

            args_text = "\n".join(arg_lines)
        else:
            args_text = "No parameters"

        block = f"""
{name}
Description:
{description}

Arguments:
{args_text}
"""
        blocks.append(block)

    return "\n\n".join(blocks)

# ----------------------------
# 3) Model Definition
# ----------------------------
planner_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
)

executor_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
).bind_tools(tools) 

responder_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
)

# ----------------------------
# 4) Planner Node
# ---------------------------- 
def planner_node(state: AgentState):
    last_user_message = state["messages"][-1].content
    tool_context = build_tool_context(tools_by_name)
    prompt = f"""
You are a financial wallet planner.
Available tools:
{tool_context}

Rules:
- If the user request matches a tool description, you MUST select that tool.
- Extract arguments only from user input.
- Do NOT hallucinate values.
- If arguments are missing, list them in "missing_args".
- If absolutely no tool matches, return {{ "tool": null }}.

Return STRICT JSON:

{{
  "tool": "tool_name",
  "args": {{ ... }},
  "missing_args": []
}}

User Request:
{last_user_message}
"""
    response = planner_model.invoke(prompt)
    try:
        plan = json.loads(re.search(r"\{.*\}", response.content, re.DOTALL).group())
    except:
        plan = None
    return {"plan": plan}

# ----------------------------
# 5) Validator Node
# ---------------------------- 
def validator_node(state: AgentState):
    plan = state.get("plan", {})
    # No tool required → respond normally
    if not plan.get("tool"):
        return {
            "messages": [
                AIMessage(content="No wallet operation required.")
            ]
        }
    # Missing args → ask user
    missing = plan.get("missing_args", [])
    if missing:
        return {
            "messages": [
                AIMessage(
                    content=f"I need the following information to proceed: {', '.join(missing)}."
                )
            ]
        }
    return {}

# ----------------------------
# 6) Executor Node
# ---------------------------- 
def executor_node(state: AgentState):
    plan = state.get("plan")
    if not plan or not plan.get("tool"):
        return {}
    tool_name = plan["tool"]
    args = plan.get("args", {})
    # Safety check
    if tool_name not in tools_by_name:
        return {
            "messages": [
                AIMessage(content=f"Tool '{tool_name}' is not available.")
            ]
        }
    tool_call = {
        "id": str(uuid4()),
        "name": tool_name,
        "args": args,
    }
    return {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[tool_call],
            )
        ]
    }

# ----------------------------
# 7) Tool Node
# ----------------------------
def tool_node(state: AgentState):
    last = state["messages"][-1]
    outputs = []
    for tc in getattr(last, "tool_calls", []):
        name = tc["name"]
        tool = tools_by_name[name]
        result = tool.invoke(tc["args"])
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False, default=str)
        outputs.append(
            ToolMessage(
                content=result,
                name=name,
                tool_call_id=tc["id"],
            )
        )
    return {"messages": outputs}

# # ----------------------------
# # 8) Responder Node
# # ----------------------------
def responder(state: AgentState):
    message_summary = state["messages"]
    summary_prompt = [
        HumanMessage(
            content=f"Based on the messages history, give the user proper answer, keep it exact, precise and to the point:\n\n{message_summary}"
        )
    ]
    summary = responder_model.invoke(summary_prompt)
    return {"messages": [summary]}

# ----------------------------
# 9) Control Flow
# ----------------------------
def route_after_validator(state: AgentState):
    plan = state.get("plan", {})
    if not plan.get("tool"):
        return "end"
    if plan.get("missing_args"):
        return "ask_user"
    return "execute"

def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("tools", tool_node)
    workflow.add_node("responder", responder)
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "validator")
    workflow.add_conditional_edges(
        "validator",
        route_after_validator,
        {
            "ask_user": END,
            "execute": "executor",
            "end": END,
        },
    )
    workflow.add_edge("executor", "tools")
    workflow.add_edge("tools", "responder")
    workflow.add_edge("responder", END)
    return workflow.compile()

# ----------------------------
# Run
# ----------------------------
def main():
    graph = build_graph()
    query = (
        "Show me active acutions "
    )
    inputs = {"messages": [HumanMessage(content=query)]}
    print("\n===== EXECUTION TRACE =====\n")
    print("USER QUERY: ", query)
    for step in graph.stream(inputs, stream_mode="updates"):
        for node_name, node_output in step.items():
            if not node_output:
                continue  # Skip None updates
            # Planner output
            if node_name == "planner" and node_output.get("plan"):
                print("\nPLANNER OUTPUT:")
                print(json.dumps(node_output["plan"], indent=2))

            # Messages
            for msg in node_output.get("messages", []):

                if getattr(msg, "tool_calls", None):
                    print("\nEXECUTOR CREATED TOOL CALL:")
                    print(json.dumps(msg.tool_calls, indent=2))

                elif msg.type == "tool":
                    print("\nTOOL EXECUTED:")
                    print("Tool Name:", msg.name)
                    print("Tool Result:", msg.content)

                elif msg.type == "ai" and msg.content:
                    print("\nSYSTEM RESPONSE:")
                    print(msg.content)

    print("\n===== END TRACE =====\n")
if __name__ == "__main__":
    main()
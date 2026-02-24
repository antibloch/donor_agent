# ----------------------------
# Import Libraries
# ----------------------------
import os
import json
from typing import Annotated, Sequence, TypedDict, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from langgraph.graph.message import add_messages
# from langchain_nvidia import ChatNVIDIA
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
# Variables Definition & File Handling
# ----------------------------
MODEL_NAME='llama-3.1-8b-instant'


# ----------------------------
# 1) Graph state
# ----------------------------
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Optional[dict]

# ----------------------------
# 2) Tools Definition
# ----------------------------
POST_BASE_URL = "http://localhost:3000"
GET_BASE_URL = "http://localhost:3000"

@tool
def check_wallet_balance():
    """
    Fetch the wallet and associated virtual card details
    for the authenticated user.

    Returns:
        dict:
            - success (bool): Indicates whether the request was successful
            - message (str): Response message from the API 

            - wallet (dict | None):
                - _id (str): Wallet ID
                - user (str): Associated user ID
                - balance (float): Available balance
                - lockedBalance (float): Locked amount
                - isDeleted (bool): Deletion status
                - isActive (bool): Wallet active status
                - transactionsHistory (list): List of transaction records
                - createdAt (str): Creation timestamp (ISO format)
                - __v (int): Document version

            - virtualCard (dict | None):
                - _id (str): Virtual card ID
                - user (str): Associated user ID
                - cardNumber (str): Virtual card number
                - cardHolder (str): Card holder name
                - expiryDate (str): Card expiry date (YYYY-MM-DD)
                - cvv (str): Card security code (⚠ sensitive)
                - isActive (bool): Card active statusk
                - isBlocked (bool): Card blocked status
                - cardType (str): Card network type (e.g., VISA)
                - currency (str): Card currency
                - limit (float): Spending limit
                - createdAt (str): Creation timestamp
                - updatedAt (str): Last update timestamp
                - __v (int): Document version

        If the wallet is not found:
            - success (bool): False
            - message (str): Error message
    """
    return requests.get(
        f"{GET_BASE_URL}/api/v1/wallet/balance"
    ).json()

@tool
def get_payment_methods():
    """
    Retrieve available payment methods for the authenticated mock user.

    Returns:
        dict:
            - success (bool): Indicates if the request was successful
            - data (dict):
                - success (bool): Internal operation status
                - message (str): Operation result message
                - count (int): Number of payment methods returned
                - data (list): List of payment method objects, each including:
                    - last4 (str): Last four digits of the card
                    - type (int): Payment method type identifier
                    - createdAt (str): Creation timestamp (ISO 8601 format)
                    - brand (str): Card brand (e.g., visa)
                    - expiryDate (str): Card expiry date (YYYY-MM-DD)
                    - uid (str): Unique payment method identifier
                    - country (str): Issuing country code (ISO 2-letter)


        If retrieval fails:
            - error (str): Error message explaining the issue
    """
    return requests.get(
        f"{GET_BASE_URL}/api/v1/payment-apis/get-payment-methods"
    ).json()

@tool
def add_payment_method():
    """
    Generate a hosted payment method page URL for the authenticated mock user.

    Returns:
        dict:
            - success (bool): Indicates if the request was successful
            - data (dict):
                - success (bool): Internal operation status
                - message (str): Operation result message
                - url (str): Hosted payment page URL where user can add new payment methods
    """
    return requests.get(
        f"{GET_BASE_URL}/api/v1/payment-apis/add-method"
    ).json()

@tool
def fund_wallet(amount: float, paymentMethodId: str):
    """
    Fund a user's wallet using a selected payment method.

    This tool sends a funding request to the wallet service using the
    provided paymentMethodId and amount. It does not perform local
    wallet or card validation logic; validation is handled by the backend API.

    Args:
        amount (float): The amount to fund into the wallet. 
            Must be greater than zero.
        paymentMethodId (str): Unique identifier of the selected
            payment method (card) to be charged.

    Returns:
        dict: A dictionary containing:
            - success (bool): Indicates if the request was successful.
            - message (str): Confirmation message.
            - data (dict):
                - paymentRequestUid (str): Unique identifier of the payment request.
                - customerId (str): Unique customer identifier.
                - walletUid (str): Unique wallet identifier.
                - newBalance (float): Updated wallet balance after funding.

        If the request fails:
            - success (bool): False
            - message (str): Error description (e.g., missing fields,
              invalid payment method, limit exceeded).
    """
    return requests.post(
            f"{POST_BASE_URL}/api/v1/payment-apis/fund-wallet",
            json={
                "amount": amount,
                "paymentMethodId":paymentMethodId
            }
        ).json()

@tool
def get_charities_by_country(country_code: str):
    """
    Retrieve a list of charities available in the specified country.

    Args:
        country_code (str): The country for which to fetch charities for e.g., (PK)

    Returns:
        dict: 
            - success (bool): Indicates if the request was successful
            - charities (list[dict]): List of charity objects, each containing:
                - _id (str): Charity ID
                - name (str): Charity name
                - email (str): Contact email
                - phone (str): Contact phone number
                - description (str): Charity description
                - address (dict): Charity address with fields:
                    - street (str), city (str), state (str), country (str), countryCode (str), postalCode (str), latitude (float), longitude (float)
                - documents (dict): Verification documents with fields like registrationCertificate, taxExemptionCertificate, annualReport, governmentApproval
                - verificationStatus (str): Approval status
                - CountryAvailability (list[dict]): List of countries where the charity operates
                - website (str): Charity website URL
                - logo (str): URL to charity logo
                - isLikedByMe (bool): Whether the current user has liked this charity
                - other fields like paymentCustomerId, registrationNumber, walletUid, partOfGiver, isDeleted, isSuspended, user, createdAt, updatedAt, __v
            - pagination (dict):
                - currentPage (int): Current page number
                - totalPages (int): Total number of pages
                - totalResults (int): Total number of charities
                - hasMore (bool): Whether more pages are available
    """
    return requests.get(
        f"{GET_BASE_URL}/api/v1/donations/charities/:{country_code}"
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
    return [ get_active_auctions, get_auction_details]

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
# 4) Model Definition
# ----------------------------
planner_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
        callbacks=[langfuse_handler],
        # extra_body={"chat_template_kwargs":{"enable_thinking":False,"clear_thinking":False}}
)

executor_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
        callbacks=[langfuse_handler],
        # extra_body={"chat_template_kwargs":{"enable_thinking":False,"clear_thinking":False}}
).bind_tools(tools) 

responder_model = ChatGroq(
        model=MODEL_NAME,
        api_key=os.environ.get('GROQ_API_KEY'), 
        temperature=0.0,
        callbacks=[langfuse_handler],
        # extra_body={"chat_template_kwargs":{"enable_thinking":False,"clear_thinking":False}}
)

# ----------------------------
# 4) Planner Node
# ---------------------------- 
def planner_node(state: AgentState):
    # Only take the recent messages so context doesn't blow up
    
    chat_history = "\n".join([f"{msg.type}: {msg.content}" for msg in state["messages"]])
    
    tool_context = build_tool_context(tools_by_name)
    prompt = f"""
    You are a specialized Auction Assistant.

YOUR DOMAIN:
- Viewing active auctions
- Viewing auction details
- (Later) placing bids

STRICT BOUNDARIES:
- You are ONLY allowed to help with auction-related queries.
- If the user asks about wallet, weather, sports, history, coding, or anything unrelated to auctions:
    - Do NOT plan any tools.
    - Return:
      {{
        "steps": [],
        "missing_args": []
      }}

PLANNING RULES:
1. Only schedule auction tools.
2. Never invent arguments.
3. If a required argument (like auction_id) is missing:
   - DO NOT schedule the tool
   - Put the parameter name in "missing_args"
4. If the user is off-topic, return empty steps and empty missing_args.

    Return STRICT JSON matching this format exactly:
    {{
      "steps": [
        {{
          "tool": "tool_name",
          "args": {{"arg_name": "value or $reference"}}
        }}
      ],
      "missing_args": ["list", "of", "missing", "user", "inputs"]
    }}

    7. If a tool requires an argument (e.g., 'country_code') and you do not have it in the Chat History:
       - STOP: Do NOT put this tool in the "steps" array.
       - INSTEAD: Add the parameter name to the "missing_args" array.
    8. NEVER use "$ask.user", "$user_input", or any reference to a tool that hasn't run yet.
    9. The "steps" array should ONLY contain tools where you have 100% of the data right now (either from history or from a tool scheduled earlier in this same plan).
    10. 10. You MUST use tool names exactly as listed in AVAILABLE TOOLS.
    Do NOT rename, paraphrase, or invent tool names.
    
    Example:
    User: "Explore charities"
    Action: {{"steps": [], "missing_args": ["country_code"]}} 
    (Note: steps is empty because country_code is missing)

    AVAILABLE TOOLS (YOU MUST USE EXACT NAMES):

    {tool_context}

    Chat History & User Request:
    {chat_history}
    """
    response = planner_model.invoke(prompt)
    try:
        plan = json.loads(re.search(r"\{.*\}", response.content, re.DOTALL).group())
    except:
        plan = {"steps": [], "missing_args": []}
    return {"plan": plan}

# ----------------------------
# 5) Validator Node 
# ---------------------------- 
def validator_node(state: AgentState):
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    missing_args = plan.get("missing_args", [])
    messages = []

    # 1. FILTER STEPS: Remove tools that don't have arguments if we know args are missing
    valid_steps = []
    for step in steps:
        tool_name = step.get("tool")
        args = step.get("args", {})

        # Safety: Check if tool exists
        if tool_name not in tools_by_name:
            messages.append(AIMessage(content=f"System Note: Tool '{tool_name}' not found."))
            continue

        # CRITICAL CHECK: 
        # If the tool is in 'steps' but has no arguments, and the planner 
        # also put things in 'missing_args', this tool call is invalid.
        if not args and missing_args:
            # We skip this step so the executor doesn't crash
            continue
            
        valid_steps.append(step)

    # 2. Update the plan in the state with the filtered steps
    updated_plan = {"steps": valid_steps, "missing_args": missing_args}

    # 3. Handle the "Nothing to execute" cases
    if missing_args and not valid_steps:
        return {
            "plan": updated_plan,
            "messages": [AIMessage(content=f"System Note: STOP EXECUTION. The planner needs input. Ask the user strictly for: {', '.join(missing_args)}")]
        }

    if not valid_steps and not missing_args:
        return {
            "plan": updated_plan,
            "messages": [AIMessage(content="System Note: No tools needed. Reply nicely based on chat history.")]
        }

    # Return the updated plan so the Router sees the correct number of steps
    return {"plan": updated_plan, "messages": messages}

# ----------------------------
# 6) Executor Node
# ---------------------------- 
def get_historical_tool_data(ref_tool, local_results, all_messages):
    """Fetches tool data from current turn OR previous conversational turns."""
    if ref_tool in local_results:
        return local_results[ref_tool]
    
    # Search backwards through chat history for the previous tool execution
    for msg in reversed(all_messages):
        if isinstance(msg, ToolMessage) and msg.name == ref_tool:
            try:
                return json.loads(msg.content)
            except:
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

        for key, value in raw_args.items():
            if isinstance(value, str) and value.startswith("$"):
                ref = value[1:]
                parts = ref.split(".", 1)
                ref_tool = parts[0]
                path = parts[1] if len(parts) > 1 else ""

                data = get_historical_tool_data(ref_tool, tool_results, state["messages"])
                
                if data is None:
                    return {"messages": [AIMessage(content=f"Execution aborted: Tool '{ref_tool}' has no data for reference '${ref}'.")]}

                for part in path.replace("[", ".").replace("]", "").split("."):
                    if not part: continue
                    if part.isdigit():
                        try:
                            data = data[int(part)]
                        except (IndexError, TypeError):
                            return {"messages": [AIMessage(content=f"Execution aborted: Index {part} out of bounds in '${ref}'.")]}
                    else:
                        if isinstance(data, dict):
                            data = data.get(part)
                        else:
                            return {"messages": [AIMessage(content=f"Execution aborted: Path '{part}' not found in '${ref}'.")]}

                resolved_args[key] = data
            else:
                resolved_args[key] = value

        tool = tools_by_name[tool_name]
        result = tool.invoke(resolved_args)
        parsed = result if not isinstance(result, str) else json.loads(result)
        tool_results[tool_name] = parsed

        # --- NEW: Cache active auctions ---
        if tool_name == "get_active_auctions":
            active_auctions_cache.clear()  # Clear old cache
            for i, auction in enumerate(parsed):
                # Number them 1, 2, 3,... for user-friendly selection
                active_auctions_cache[str(i+1)] = auction

            # Optional: create a formatted message to display to the user
            auction_lines = []
            for i, auction in enumerate(parsed):
                auction_lines.append(f"{i+1}. {auction['title']} | Current Bid: {auction.get('currentBid', 'N/A')}")
            formatted_list = "\n".join(auction_lines)

            messages.append(AIMessage(
                content=f"Here are the active auctions:\n{formatted_list}\n\nPlease type the number of the auction you'd like details about."
            ))

        messages.append(ToolMessage(
            content=json.dumps(parsed, ensure_ascii=False, default=str),
            name=tool_name, tool_call_id=str(uuid4())
        ))

    # IMPORTANT: If tools were executed but the planner still indicated missing arguments for FUTURE steps, ask the user!
    if missing_args:
        messages.append(AIMessage(content=f"System Note: Tools executed successfully. Now ask the user to provide: {', '.join(missing_args)}"))

    return {"messages": messages}

# ----------------------------
# 7) Responder Node
# ----------------------------
# Cache for active auctions mapping numbers -> auction dict
active_auctions_cache = {}

def responder(state: AgentState):
    # Get the last user message
    user_last_msg = ""
    for msg in reversed(state["messages"]):
        if isinstance(msg, HumanMessage):
            user_last_msg = msg.content.strip()
            break

    messages_to_send = []

    # --- Step 1: Check if user typed a number corresponding to an active auction ---
    if user_last_msg.isdigit() and user_last_msg in active_auctions_cache:
        auction = active_auctions_cache[user_last_msg]
        # Call the details tool
        details_result = get_auction_details.invoke({"auction_id": auction["_id"]})

        

        # The result may be a string (JSON) or dict depending on your tool setup
        details = details_result if isinstance(details_result, dict) else json.loads(details_result)

        auction_text = f"""
        Title: {details.get('title', 'N/A')}

        Description: {details.get('description', 'N/A')}
        Minimum Bid: {details.get('minBidAmount', 'N/A')}
        Current Bid: {details.get('currentBid', 'N/A')}
        Start Time: {details.get('startTimeStamp', 'N/A')}
        End Time: {details.get('endTimeStamp', 'N/A')}
        """
        messages_to_send.append(AIMessage(content=auction_text))
        active_auctions_cache.clear()  # clear cache after selection

        return {"messages": messages_to_send}

    # --- Step 2: User typed a number but invalid ---
    elif user_last_msg.isdigit() and user_last_msg not in active_auctions_cache and active_auctions_cache:
        messages_to_send.append(AIMessage(
            content=f"Invalid selection. Please choose a number between 1 and {len(active_auctions_cache)}."
        ))
        return {"messages": messages_to_send}

    # --- Step 3: Normal auction assistant flow ---
    message_summary = state["messages"]
    
    # Strict System Prompt
    system_prompt = """
        You are a specialized Auction Assistant.

        CRITICAL TOPIC BOUNDARIES:
        1. You ONLY assist with auction-related actions:
        - Viewing active auctions
        - Viewing auction details
        - (Later) placing bids
        2. DO NOT answer questions about:
        - Wallets
        - Payments
        - Donations
        - Weather
        - Sports
        - Coding
        - History
        - General knowledge
        3. If the user asks anything outside auctions:
        - Politely refuse
        - State that you are an Auction Assistant only
        - Ask if they would like to view active auctions

        DO NOT use emojis.
        Base your answer strictly on conversation history and tool outputs.
            """

    # Combine instructions with history
    final_prompt = [
        HumanMessage(
            content=f"{system_prompt}\n\nConversation History:\n{message_summary}"
        )
    ]
    
    summary = responder_model.invoke(final_prompt)
    messages_to_send.append(summary)
    
    return {"messages": messages_to_send}

# ----------------------------
# 8) Control Flow
# ----------------------------
def route_after_validator(state: AgentState):
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    
    # If there are steps to run, route to executor. 
    # If no steps, route directly to responder (to chat or ask for missing args).
    if len(steps) > 0:
        return "executor"
    return "responder"

def build_graph():
    workflow = StateGraph(AgentState)
    workflow.add_node("planner", planner_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("responder", responder)
    
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "validator")
    
    # Clean string returns to avoid KeyErrors
    workflow.add_conditional_edges("validator", route_after_validator)
    
    workflow.add_edge("executor", "responder")
    workflow.add_edge("responder", END)
    
    return workflow.compile()

# ----------------------------
# Run - Interactive Chat Loop
# ----------------------------
def main():
    graph = build_graph()
    
    # "Memory" for the conversation
    chat_memory = []
    
    
    print("\n==================================================")
    print("💰 FINANCIAL WALLET AGENT (CLI MODE)")
    print("Type 'exit', 'quit', or 'q' to stop.")
    print("==================================================\n")

    while True:
        # 1. Get User Input
        try:
            user_input = input("User: ")
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break

        if user_input.lower() in ["exit", "quit", "q"]:
            print("Goodbye!")
            break
        
        # 2. Add User Message to Memory
        user_msg = HumanMessage(content=user_input)
        chat_memory.append(user_msg)
        
        # 3. Stream the Graph
        print("\n(Agent is thinking...)\n")
        
        try:
            for step in graph.stream({"messages": chat_memory}, stream_mode="updates"):
                for node_name, node_output in step.items():
                    
                    # --- FIX: SAFETY CHECK ---
                    # If a node returns None or empty dict, skip it to prevent "NoneType" error
                    if not node_output:
                        continue
                    
                    # --- A) Display Planner Logic ---
                    # safely check if "plan" is in the dictionary
                    if node_name == "planner" and "plan" in node_output:
                        plan = node_output["plan"]
                        steps = plan.get("steps", [])
                        missing = plan.get("missing_args", [])
                        
                        if steps:
                            print(f"  ➤ [Planner] Scheduled tools: {[s['tool'] for s in steps]}")
                        if missing:
                            print(f"  ➤ [Planner] Need user input for: {missing}")

                    # --- B) Capture and Print New Messages ---
                    # safely check if "messages" is in the dictionary
                    if "messages" in node_output:
                        new_messages = node_output["messages"]
                        for msg in new_messages:
                            # CRITICAL: Append new messages to memory for the next turn
                            chat_memory.append(msg)

                            # Print outputs nicely
                            if isinstance(msg, ToolMessage):
                                print(f"  ➤ [Tool Executed] {msg.name}")
                            
                            elif isinstance(msg, AIMessage):
                                # Distinguish between hidden System Notes and actual Responses
                                if "System Note:" in msg.content:
                                    # (Optional) Print system logic for debugging
                                    # print(f"  ➤ [Logic] {msg.content}")
                                    pass
                                else:
                                    print(f"\nAgent: {msg.content}\n")
                                    
        except Exception as e:
            print(f"\n[ERROR] An error occurred in the graph: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()
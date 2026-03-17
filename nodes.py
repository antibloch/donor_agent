import json
from uuid import uuid4
from typing import Dict, List, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from rich import print as rich_print
import re

from llm import make_model       
from history_formatters import (
    format_history_for_planner,
    format_history_for_gate,
    build_cached_tool_outputs,
    format_history_for_responder,
    extract_latest_requested_missing_args,
    detect_recent_tool_errors,
    get_current_round_messages,
    format_msg, 
    _parse_plan, 
    _compact_json, 
    _safe_json_loads, 
    _extract_tool_error,
    _format_previous_agentic_step,
    _format_last_agentic_step, 
    _detect_semantic_error,
)
from tools.tool_setup import build_tool_context

import dotenv
dotenv.load_dotenv()
DEBUG_MESSAGES = int(dotenv.get_key(dotenv.find_dotenv(), "DEBUG_MESSAGES") or "0")
DO_SELECTION = (dotenv.get_key(dotenv.find_dotenv(), "DO_SELECTION") or "0").strip().lower() in ("1", "true", "yes", "on")
SHOW_PLANNER_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_PLANNER_HISTORY") or "0")
SHOW_PLANNER_TOOL_CONTEXT = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_PLANNER_TOOL_CONTEXT") or "0")
SHOW_RESPONDER_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_RESPONDER_HISTORY") or "0")
TRUNCATION_LIMIT_PLANNER_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "TRUNCATION_LIMIT_PLANNER_HISTORY") or "10000")
TRUNCATION_LIMIT_PLANNER_TOOL = int(dotenv.get_key(dotenv.find_dotenv(), "TRUNCATION_LIMIT_PLANNER_TOOL") or "1000")
TRUNCATION_LIMIT_RESPONDER_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "TRUNCATION_LIMIT_RESPONDER_HISTORY") or "10000")
TRUNCATION_LIMIT_GATE_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "TRUNCATION_LIMIT_GATE_HISTORY") or "10000")
SHOW_GATE_HISTORY = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_HISTORY") or "0")
SHOW_GATE_CACHED_TOOL_OUTPUTS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_CACHED_TOOL_OUTPUTS") or "0")
SHOW_GATE_FIXED_ERRORS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_FIXED_ERRORS") or "0")
SHOW_GATE_UNRESOLVED_ERRORS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_UNRESOLVED_ERRORS") or "0")
SHOW_GATE_ATTEMPTED_REPAIRS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_ATTEMPTED_REPAIRS") or "0")
SHOW_GATE_UNRESOLVED_ERROR_IDS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_UNRESOLVED_ERROR_IDS") or "0")
SHOW_GATE_TOOL_OUTPUTS = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_TOOL_OUTPUTS") or "0")
TRUNCATION_LIMIT_GATE_TOOL_OUTPUT = int(dotenv.get_key(dotenv.find_dotenv(), "TRUNCATION_LIMIT_GATE_TOOL_OUTPUT") or "500")

def _normalize_missing_args(items: List[Any] | None) -> List[str]:
    out: List[str] = []
    for item in items or []:
        if not isinstance(item, str):
            continue
        value = item.strip()
        if value and value not in out:
            out.append(value)
    return out

def make_planner_node(tools_by_name: dict):
    model = make_model(temperature=0.0)

    def planner_node(state: dict) -> Dict:
        chat_history = format_history_for_planner(
            state.get("messages", []),
            drop_last_user=True,
            last_agentic_step=state.get("last_agentic_step"),
        )
        prior_missing_args = extract_latest_requested_missing_args(state.get("messages", []))
        user_query = state.get("messages", [])[-1].content if state.get("messages") else ""
        tool_context = build_tool_context(
            tools_by_name,
            do_selection=DO_SELECTION,
            user_query=user_query,
            chat_history=chat_history,
            model=model,
        )


        prompt = f"""
        You are a planning module for a charity & donation assistant.

        Your job is to output the fullest correct dependency-aware tool plan for the user's request.

        VERY IMPORTANT:
        - Tool descriptions contain dependency chains and required ordering.
        - Use any FINAL_AGENT_STEP[gate] and PREVIOUS_AGENT_STEP[gate] context in Chat History as grounded execution context when choosing the next plan.
        - FINAL_AGENT_STEP[gate] and PREVIOUS_AGENT_STEP[gate] may include reason, output, and missing_args from recent gate activity; use them to continue unfinished repair work correctly.
        - The most recent FINAL_AGENT_STEP[gate], and when present its paired PREVIOUS_AGENT_STEP[gate], are especially important when continuing or repairing a multi-round workflow.
        - You must follow those dependency chains.
        - If a later tool depends on an earlier tool's result, you must still include the later tool in the plan when it is part of the required chain.
        - When an argument is not yet known because it will come from a previous tool result, use a symbolic placeholder instead of omitting the dependent tool.
        - If a required value cannot be recovered from prior successful outputs or from tools earlier in THIS plan, do NOT leave it as a placeholder. Put that field name in missing_args.
        - The missing_args list must represent the current unresolved user inputs after considering all reusable prior tool outputs in chat history.
        - For list-of-object arguments (e.g., products: [{{"partner": "...", "charityProd": "..."}}]), construct each object by extracting real field values (_id, pricePerUnit, category, partner, etc.) from the cached tool output in Conversation History, that returned those records.
        - Intelligently match and substitute, what available args can be associated with extracted objects like 'id', 'category', etc., so that missing_args contains only truly unrecoverable values that the user must provide.

        PLACEHOLDER POLICY:
        - For list-of-object arguments (e.g., products: [{{"partner": "...", "charityProd": "..."}}]), construct each object by extracting real field values (_id, pricePerUnit, category, partner, etc.) from the cached tool output in Conversation History, that returned those records.
        - Intelligently match and substitute, what available args can be associated with extracted objects like 'id', 'category', etc., so that missing_args contains only truly unrecoverable values that the user must provide.
        - Use placeholders for arguments that are potential missing_args elements.
        - Do NOT invent fake final values.
        - Instead use placeholders such as:
        - "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"
        - "<WEBSITE_URL_FROM_CHARITY_DETAILS>"
        - Prefer a complete dependency-aware plan over a single first-step plan when tool descriptions define a normal chain.

        MISSING-ARG POLICY:
        - For list-of-object arguments (e.g., products: [{{"partner": "...", "charityProd": "..."}}]), construct each object by extracting real field values (_id, pricePerUnit, category, partner, etc.) from the cached tool output in Conversation History, that returned those records.
        - Intelligently match and substitute, what available args can be associated with extracted objects like 'id', 'category', etc., so that missing_args contains only truly unrecoverable values that the user must provide.
        - For action tools like donations, bids, wallet funding, or other write operations: if any required final argument is not already known and not recoverable from earlier tools, add its exact field name to missing_args.
        - Do not ask for args already supplied in the latest user message.
        - Do not include any arg in missing_args if it can be grounded from prior successful tool outputs already present in chat history.
        - Entity ids such as charityId, grantId, campaignId, productId, auction_id, and similar backend identifiers are NOT user-facing missing args when a prior successful tool output in chat history already contains a clearly matching candidate entity for that type.
        - If prior successful output already contains candidate entities for a needed id:
          1. first try to match the user's requested name/title semantically,
          2. if the user explicitly named a grant/campaign/product/auction and no clear semantic match exists, do NOT select an arbitrary first item,
          3. in that case keep the entity unresolved so the system can ask the user to clarify or report that no matching entity was found,
          4. only use an item's _id/id directly when the match is grounded by the tool output.
        - Example: if list_charity_grants already returned one or more grants, you may plan grant_donation with a concrete grantId only when one of those grants clearly matches the user's requested grant.

        CONTINUING A PRIOR INCOMPLETE ACTION (highest priority rule — check this first):
        - If Chat History contains a FINAL_AGENT_STEP[gate] with done=true and non-empty missing_args,
          AND the most recent user message provides one or more of those missing args (e.g., a password,
          a donation type, a grant title), THEN you MUST re-plan the original pending action with:
          (a) the newly provided values substituted for their placeholders,
          (b) all previously resolved values (ids, amounts, etc.) reused from Chat History.
          Do NOT return steps: [] in this case — the action was never completed and must be retried.
        - Look at the FINAL_AGENT_STEP[gate] and PREVIOUS_AGENT_STEP[gate] reason/output/missing_args fields to understand what was pending and what was already attempted.
        - Do not re-run discovery tools (discover_charities, list_charity_active_campaigns, etc.) if
          their outputs are already present in Chat History — reuse those cached values directly.
        - Use Python_REPL ONLY for genuine computation (math, data transformation). NEVER use it to
          search or filter arrays — you can do that directly in the plan by reading tool output context.

        PLANNING RULES:
        1. Identify all user intents.
        2. Reuse prior successful tool outputs where sufficient.
        3. Read and obey dependency instructions in tool descriptions.
        4. If a vague charity name is mentioned, follow the default charity chain:
        discover_charities -> charity_details -> fetch_url
        5. Do not stop at discovery for a "tell me about X" query if deeper tools are part of the required chain.
        6. If downstream args are not yet known, include the downstream tool with a symbolic placeholder.
        7. Only return steps: [] if BOTH are true: (a) no FINAL_AGENT_STEP[gate] shows a pending
           incomplete action, AND (b) chat history already fully satisfies the current user request.

        ---

        AVAILABLE TOOLS:
        {tool_context}

        OUTPUT FORMAT (STRICT JSON ONLY):
        {{
        "steps": [
            {{
            "tool": "tool_name",
            "args": {{
                "arg_name": "value_or_symbolic_placeholder"
            }}
            }}
        ],
        "missing_args": []
        }}

        Chat History:
        {chat_history}

        User Request:
        {state.get("messages", [])[-1].content if state.get("messages") else ""}
        """

        trunc_lim_history = TRUNCATION_LIMIT_PLANNER_HISTORY
        trunc_lim_tool = TRUNCATION_LIMIT_PLANNER_TOOL
        
        if DEBUG_MESSAGES == 1 and SHOW_PLANNER_HISTORY == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER INPUT CHAT HISTORY (DO_SELECTION={})".format(DO_SELECTION))
            rich_print("="*80)
            truncated_history = chat_history[:trunc_lim_history] + ("..." if len(chat_history) > trunc_lim_history else "")
            rich_print(f'{truncated_history}')
            rich_print("="*80)

        if DEBUG_MESSAGES == 1 and SHOW_PLANNER_TOOL_CONTEXT == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER INPUT TOOL CONTEXT (DO_SELECTION={})".format(DO_SELECTION))
            rich_print("="*80)
            truncated_context = tool_context[:trunc_lim_tool] + ("..." if len(tool_context) > trunc_lim_tool else "")
            rich_print(f'{truncated_context}')
            rich_print("="*80)

        response = model.invoke([HumanMessage(content=prompt)])

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER RAW OUTPUT")
            rich_print("="*80)
            rich_print(response.content)
            rich_print("="*80)

        plan = _parse_plan(response.content)
        plan["missing_args"] = _normalize_missing_args(plan.get("missing_args", []))

        if DEBUG_MESSAGES == 1:
            steps_list = [s.get("tool", "") for s in plan.get("steps", [])]
            rich_print(f"[PLANNER] Scheduled tools: {steps_list}")

        return {"plan": plan}

    return planner_node


def make_validator_node(tools_by_name: dict):
    def validator_node(state: dict) -> Dict:
        plan = state.get("plan", {})
        steps = plan.get("steps", [])
        missing_args = _normalize_missing_args(plan.get("missing_args", []))
        messages = []

        valid_steps = []
        for step in steps:
            tool_name = step.get("tool")
            args = step.get("args", {})
            if tool_name not in tools_by_name:
                messages.append(AIMessage(content=f"System Note: Tool '{tool_name}' not found."))
                continue
            if not args and missing_args:
                continue
            valid_steps.append(step)

        updated_plan = {"steps": valid_steps, "missing_args": missing_args}

        if missing_args and not valid_steps:
            return {
                "plan": updated_plan,
                "messages": [AIMessage(content=(
                    f"System Note: STOP EXECUTION. The planner needs input. "
                    f"Ask the user strictly for: {', '.join(missing_args)}. "
                    f"CURRENT_MISSING_ARGS_JSON={json.dumps(missing_args, ensure_ascii=False)}"
                ))]
            }
        if not valid_steps and not missing_args:
            return {
                "plan": updated_plan,
                "messages": [AIMessage(content="System Note: No tools needed. Reply nicely based on chat history.")]
            }
        return {"plan": updated_plan, "messages": messages}

    return validator_node


def make_executor_node(tools_by_name: dict):
    async def _invoke_tool(tool, raw_args: dict):
        # Prefer async if the tool supports it
        if hasattr(tool, "ainvoke"):
            # Some tools have ainvoke but it's not a coroutine function → still try
            result = await tool.ainvoke(raw_args)
            return result

        # Fallback to sync invoke
        if getattr(tool, "args_schema", None) is not None:
            return tool.invoke(raw_args)

        if not raw_args:
            return tool.invoke("")

        if len(raw_args) == 1:
            return tool.invoke(next(iter(raw_args.values())))

        # fallback for tools that expect a string
        return tool.invoke(json.dumps(raw_args, ensure_ascii=False))

    def _looks_like_error_text(s: str) -> bool:
        if not s:
            return False
        error_markers = (
            "Traceback (most recent call last):",
            "IndentationError", "SyntaxError", "NameError", "KeyError",
            "TypeError", "ValueError", "Exception", "ERROR", "Error:",
        )
        return any(m in s for m in error_markers)

    def _normalize_result(tool_name: str, result):
        if result is None:
            return {"ok": True, "result": None}
        if isinstance(result, str):
            s = result.strip()
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, dict) and parsed.get("ok") is False:
                        return parsed
                    return {"ok": True, "result": parsed}
                except json.JSONDecodeError:
                    pass
            if tool_name in ("Python_REPL", "python_repl", "PythonREPLTool") and _looks_like_error_text(s):
                return {"ok": False, "error": s}
            if _looks_like_error_text(s):
                return {"ok": False, "error": s}
            return {"ok": True, "result": s}
        if isinstance(result, (dict, list, int, float, bool)):
            return {"ok": True, "result": result}
        return {"ok": True, "result": str(result)}

    def _mk_tool_call(tool_name: str, args: dict, tool_call_id: str) -> dict:
        return {"name": tool_name, "args": args or {}, "id": tool_call_id, "type": "tool_call"}

    async def executor_node(state: dict) -> Dict:
        plan = state.get("plan", {})
        steps = plan.get("steps", [])
        if not steps:
            return {}

        messages: List[BaseMessage] = []
        for step in steps:
            tool_name = step.get("tool")
            raw_args = dict(step.get("args", {}) or {})

            if tool_name not in tools_by_name:
                messages.append(AIMessage(content=f"System Note: Tool '{tool_name}' not found. Skipping."))
                continue

            tool = tools_by_name[tool_name]
            tool_call_id = str(uuid4())

            messages.append(AIMessage(content="", tool_calls=[_mk_tool_call(tool_name, raw_args, tool_call_id)]))

            try:
                # This is the key change: we now await the invocation
                result = await _invoke_tool(tool, raw_args)
                payload = _normalize_result(tool_name, result)

            except Exception as e:
                error_msg = str(e)
                payload = {
                    "ok": False,
                    "error": error_msg,
                    "tool": tool_name,
                    "args": raw_args
                }

            messages.append(ToolMessage(
                content=json.dumps(payload, ensure_ascii=False, default=str),
                name=tool_name,
                tool_call_id=tool_call_id,
            ))

            if DEBUG_MESSAGES == 1:
                preview = payload.get("result") if payload.get("ok") else payload.get("error")
                preview_s = _compact_json(preview, max_chars=200)   # ← FIXED
                rich_print(f"[EXECUTOR] {tool_name} done ok={payload.get('ok')} args={raw_args} preview={preview_s}")

        return {"messages": messages}

    return executor_node


def make_responder_node():
    model = make_model(temperature=0.0)

    # Auth-gated tools — these require a password parameter and represent
    # actual transactional operations.  Used by the programmatic password
    # short-circuit to avoid false positives when a non-auth tool succeeds
    # alongside a failed auth tool in the same execution round.
    AUTH_GATED_TOOLS = frozenset({
        "place_bid",
        "fund_wallet",
        "product_donation",
        "campaign_donation",
        "grant_donation",
    })

    def _message_may_contain_password(text: str) -> bool:
        if not isinstance(text, str):
            return False
        lowered = text.lower()
        if lowered.startswith("password:"):
            return True
        return bool(re.search(r"\bpass(?:word)?\b\s*[:;,\-]?", lowered))

    def _latest_password_submission_index(messages: List[BaseMessage]) -> int | None:
        for i in range(len(messages) - 1, -1, -1):
            msg = messages[i]
            if isinstance(msg, HumanMessage) and _message_may_contain_password((msg.content or "").strip()):
                return i
        return None

    def _build_recent_auth_context(messages: List[BaseMessage], current_round_tool_msgs: List[ToolMessage]) -> str:
        # Only emit auth context when an auth-gated tool actually ran this round.
        if not any(m.name in AUTH_GATED_TOOLS for m in current_round_tool_msgs):
            return ""

        password_idx = _latest_password_submission_index(messages)
        if password_idx is None:
            return ""

        auth_success_tool = None
        auth_failure_tool = None
        for msg in messages[password_idx + 1:]:
            if not isinstance(msg, ToolMessage) or msg.name not in AUTH_GATED_TOOLS:
                continue
            payload = _safe_json_loads((msg.content or "").strip())
            if payload is None:
                continue
            if _extract_tool_error(payload) is None:
                auth_success_tool = msg.name
                break
            auth_failure_tool = msg.name

        if auth_success_tool:
            return (
                "RECENT AUTHENTICATION: The latest user-provided password is grounded by a "
                f"successful auth-sensitive tool result after that message. Successful tool: "
                f"'{auth_success_tool}'."
            )

        if auth_failure_tool:
            return (
                "RECENT AUTHENTICATION: The latest user-provided password was followed by an "
                f"auth-sensitive tool failure. Latest failing tool: '{auth_failure_tool}'."
            )

        return (
            "RECENT AUTHENTICATION: A recent user message appears to provide a password, but "
            "there is no successful auth-sensitive tool output after it yet."
        )

    def _looks_like_missing_arg_reply(text: str, pending_missing_args: List[str]) -> bool:
        if not isinstance(text, str):
            return False
        value = text.strip()
        if not value or not pending_missing_args:
            return False
        lowered = value.lower()
        if _message_may_contain_password(value):
            return True
        if len(value.split()) <= 6:
            return True
        for arg in pending_missing_args:
            arg_name = str(arg).strip().lower()
            if arg_name and lowered.startswith(arg_name):
                return True
        return False

    def _build_active_user_request_context(messages: List[BaseMessage], pending_missing_args: List[str]) -> str:
        for i in range(len(messages) - 1, -1, -1):
            current = messages[i]
            if isinstance(current, HumanMessage):
                content = (current.content or "").strip()
                if not content:
                    continue
                # Strip leading "Password: <value>" prefix so the actual request is shown
                stripped = re.sub(r"(?i)^pass(?:word)?\s*[:;]\s*\S+\s*[,;]?\s*", "", content).strip()
                request = stripped if stripped else content
                # Skip pure password submissions (nothing left after stripping)
                if not stripped and _message_may_contain_password(content):
                    continue
                if _looks_like_missing_arg_reply(request, pending_missing_args):
                    continue
                return (
                    "ACTIVE USER REQUEST: The latest unresolved user message that the final "
                    f"response must address is: {request}"
                )
        return ""

    def _detect_empty_results(tool_messages):
        """
        Scan successful ToolMessages for empty-but-ok payloads.
        Returns a list of human-readable notes like:
          "Tool 'get_my_bid_history' returned successfully but 'bids' is empty (0 results)."
        """
        notes = []
        for m in tool_messages:
            payload = _safe_json_loads((m.content or "").strip())
            if payload is None:
                continue
            if _extract_tool_error(payload) is not None:
                continue

            # Unwrap the standard envelope: {"ok": true, "result": { ... }}
            result = payload.get("result", payload) if isinstance(payload, dict) else payload
            if isinstance(result, dict) and "result" in result:
                result = result["result"]

            if not isinstance(result, dict):
                continue

            for key, val in result.items():
                if isinstance(val, list) and len(val) == 0:
                    notes.append(
                        f"Tool '{m.name}' returned successfully but '{key}' is empty (0 results)."
                    )
                elif (
                    isinstance(val, (int, float))
                    and key.lower().startswith("total")
                    and val == 0
                ):
                    notes.append(
                        f"Tool '{m.name}' returned successfully but '{key}' is 0."
                    )
        return notes

    def _unwrap_success_payload(payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload
        result = payload.get("result", payload)
        if isinstance(result, dict) and "result" in result:
            result = result.get("result")
        return result

    def _collect_entity_options(messages: List[BaseMessage], missing_args: List[str]) -> Dict[str, List[str]]:
        options: Dict[str, List[str]] = {}
        wanted = set(missing_args or [])
        if not wanted:
            return options

        entity_specs = {
            "grantId": ("grants", "title", "grant"),
            "grant_id": ("grants", "title", "grant"),
            "campaignId": ("campaigns", "title", "campaign"),
            "campaign_id": ("campaigns", "title", "campaign"),
            "productId": ("products", "name", "product"),
            "product_id": ("products", "name", "product"),
            "auction_id": ("auctions", "title", "auction"),
            "auctionId": ("auctions", "title", "auction"),
            "charityId": ("items", "name", "charity"),
            "charity_id": ("items", "name", "charity"),
        }

        for arg_name, (list_key, label_key, label_name) in entity_specs.items():
            if arg_name not in wanted:
                continue

            labels: List[str] = []
            for msg in reversed(messages):
                if not isinstance(msg, ToolMessage):
                    continue
                payload = _safe_json_loads((msg.content or "").strip())
                if payload is None or _extract_tool_error(payload) is not None:
                    continue
                result = _unwrap_success_payload(payload)
                if not isinstance(result, dict):
                    continue
                items = result.get(list_key)
                if not isinstance(items, list):
                    nested_data = result.get("data")
                    if isinstance(nested_data, dict):
                        items = nested_data.get(list_key)
                if not isinstance(items, list) or not items:
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue
                    label = item.get(label_key)
                    if not label and label_key != "name":
                        label = item.get("name")
                    if not label and label_key != "title":
                        label = item.get("title")
                    if isinstance(label, str):
                        value = label.strip()
                        if value and value not in labels:
                            labels.append(value)

                if labels:
                    options[arg_name] = labels
                    break

            if labels:
                options[f"{arg_name}__label"] = [label_name]

        return options

    def _build_situational_block(state, current_round_tool_msgs):
        """
        Build a SITUATIONAL CONTEXT string from programmatic signals that
        the responder LLM would otherwise not see.

        Priority:
        1) current missing args
        2) final gate step for this round (last_agentic_step)
        3) unresolved last_tool_error
        4) fallback heuristics from all current-round tool messages
        """
        plan = state.get("plan", {}) or {}
        missing_args = plan.get("missing_args", []) or []
        last_tool_error = state.get("last_tool_error")
        last_agentic_step = state.get("last_agentic_step") or {}
        all_messages = list(state.get("messages", []) or [])

        empty_data_notes = _detect_empty_results(current_round_tool_msgs)
        lines = []

        effective_missing_args = list(missing_args)
        effective_step = dict(last_agentic_step) if isinstance(last_agentic_step, dict) else {}
        prev_attempt = effective_step.get("previous_attempt") if isinstance(effective_step, dict) else None

        # Duplicate-step terminal states should inherit the previous executed attempt's
        # grounded context. Otherwise stale planner missing_args (e.g. grantId) leak
        # into responder behavior even after the gate already resolved them.
        if (
            isinstance(effective_step, dict)
            and effective_step.get("reason") == "Duplicate repair step detected; no further automatic repair attempted."
            and isinstance(prev_attempt, dict)
        ):
            prev_missing = list(prev_attempt.get("missing_args") or [])
            prev_output = str(prev_attempt.get("output", ""))
            prev_reason = str(prev_attempt.get("reason", "")).strip()
            if not prev_missing and re.search(r"(request failed:?\s*(?:4|5)\d\d|client error|server error|http\s*(?:4|5)\d\d)", prev_output, re.IGNORECASE):
                effective_missing_args = []
                effective_step["tool"] = prev_attempt.get("tool") or effective_step.get("tool")
                effective_step["reason"] = prev_reason or effective_step.get("reason", "")
                effective_step["output"] = prev_output or effective_step.get("output", "")
                effective_step["missing_args"] = []

        # Only emit ACTIVE USER REQUEST when the gate didn't succeed — if the
        # gate succeeded the responder should use FINAL AGENT STEP SUCCEEDED instead.
        gate_ok = isinstance(last_agentic_step, dict) and last_agentic_step.get("ok") is True
        if not gate_ok:
            active_user_request = _build_active_user_request_context(all_messages, effective_missing_args)
            if active_user_request:
                lines.append(active_user_request)

        recent_auth_context = _build_recent_auth_context(all_messages, current_round_tool_msgs)
        if recent_auth_context:
            lines.append(recent_auth_context)

        entity_options = _collect_entity_options(all_messages, effective_missing_args)

        # 1) Missing user input
        if effective_missing_args:
            lines.append(
                f"MISSING USER INPUT: The system determined the following inputs "
                f"are required from the user before the requested action can proceed: "
                f"{', '.join(effective_missing_args)}. "
                f"Ask the user for ONLY these specific values. "
                f"Do NOT attempt the action without them."
            )
            for missing_arg in effective_missing_args:
                readable_options = entity_options.get(missing_arg) or []
                label_hint = (entity_options.get(f"{missing_arg}__label") or [""])[0]
                if readable_options:
                    lines.append(
                        f"MISSING INPUT OPTIONS: For '{missing_arg}', ask the user to choose the "
                        f"{label_hint or 'item'} by human-readable title/name, not by backend id. "
                        f"Available options: {', '.join(readable_options)}."
                    )

        # 2) Final gate step for this round (preferred over coarse tool heuristics)
        has_final_gate_step = isinstance(effective_step, dict) and bool(effective_step)

        if has_final_gate_step:
            step_ok = effective_step.get("ok")
            step_tool = effective_step.get("tool") or "gate_decision"
            step_output = str(effective_step.get("output", ""))[:250]
            step_reason = str(effective_step.get("reason", "")).strip()
            step_missing_args = list(effective_step.get("missing_args") or [])
            step_done = bool(effective_step.get("done"))

            if step_ok is False:
                msg = (
                    f"FINAL AGENT STEP FAILED: The final gate step for this round "
                    f"failed or concluded that automatic repair was not possible. "
                    f"Tool: '{step_tool}'."
                )

                if step_reason:
                    msg += f" Reason: {step_reason}"

                if step_missing_args:
                    msg += f" Missing args still needed: {', '.join(step_missing_args)}."

                if step_output:
                    msg += f" Error/output: {step_output}"

                if step_done and step_tool == "gate_decision":
                    msg += " The gate explicitly decided that no further automatic repair step should be attempted."

                lines.append(msg)

        # 3) Empty but successful-looking data
        for note in empty_data_notes:
            lines.append(f"EMPTY DATA: {note}")

        # 4) Fallback heuristics only when there is NO final gate step
        if not has_final_gate_step:
            has_any_tool_output = len(current_round_tool_msgs) > 0
            has_any_successful_tool = any(
                _extract_tool_error(_safe_json_loads((m.content or "").strip())) is None
                for m in current_round_tool_msgs
                if _safe_json_loads((m.content or "").strip()) is not None
            )

            if not has_any_tool_output:
                lines.append(
                    "NO TOOLS EXECUTED: No tools were called for this request. "
                    "If the user asked for data that requires a tool, inform them that "
                    "the information could not be retrieved. Do NOT fabricate data."
                )
            elif not has_any_successful_tool:
                lines.append(
                    "ALL TOOLS FAILED: Every tool that ran in this round returned an error. "
                    "Inform the user that the request could not be completed and summarize "
                    "the issue. Do NOT fabricate data."
                )

        # 5) Unresolved tool error
        if last_tool_error:
            err_tool = last_tool_error.get("tool", "unknown")
            err_text = str(last_tool_error.get("error", ""))[:250]
            lines.append(
                f"UNRESOLVED ERROR: Tool '{err_tool}' failed and could not be "
                f"repaired automatically. Error: {err_text}"
            )

        if not lines:
            lines.append(
                "NO SPECIAL SITUATIONAL FLAGS: Answer strictly from the Conversation History and "
                "tool outputs, with priority on the latest unresolved user request."
            )

        return (
            "\n\nSITUATIONAL CONTEXT (system-generated, authoritative):\n"
            + "\n".join(f"- {line}" for line in lines)
        )

    def responder(state: dict) -> Dict:
        messages = list(state.get("messages", []) or [])

        # Build situational context from programmatic signals
        current_round = get_current_round_messages(messages)
        current_round_tool_msgs = [
            m for m in current_round if isinstance(m, ToolMessage)
        ]
        situational_block = _build_situational_block(state, current_round_tool_msgs)
        tool_context = (
            "Use successful Giver tool outputs in the Conversation History as the primary source "
            "for valid options and argument values. Treat external web URLs only as supplementary."
        )

        
        system_prompt = """
You are a donor-assisting AI agent for Giver, a donation platform, and you produce FINAL, USER-FACING answers.                               
Your role is to help donors discover charities, products, campaigns, and auctions exclusively through the Giver platform.    
Assume the user may be a confused or first-time donor who needs clear guidance.

OUTPUT RULES (STRICT — apply in this exact priority order):
- RULE 1 (MISSING USER INPUT — highest priority): If the SITUATIONAL CONTEXT contains a MISSING USER INPUT line, respond in natural, helpful language tailored to the latest unresolved user request. You may briefly mention what the user was trying to do if that is grounded by ACTIVE USER REQUEST, FINAL_AGENT_STEP[gate], or other recent conversation context, but do NOT invent missing details. Clearly ask only for the missing args listed in the MISSING USER INPUT line, using human-readable names converted from those exact args (snake_case/camelCase → spaced words, e.g., donation_type → "donation type", countryCode → "country code"). Do NOT infer, add, or derive additional missing args from TOOL CONTEXT, UNRESOLVED ERROR, or any other source. For each listed arg that has grounded valid values described in TOOL CONTEXT, relevant successful Giver tool outputs, or MISSING INPUT OPTIONS lines in SITUATIONAL CONTEXT, include concise helpful options or examples. For entity-id args like grantId/campaignId/productId/auctionId/charityId, never ask for a raw backend id if human-readable title/name options are available; ask the user to choose the grant/campaign/product/auction/charity by title or name instead. Do not print an options line when no real options exist. End with a short invitation to reply with the missing information. Do NOT apply RULE 2 when this rule fires.
- RULE 2 (SERVER / AUTH ERROR — only when RULE 1 does not apply): If the SITUATIONAL CONTEXT or most recent FINAL AGENT STEP contains a tool error with an HTTP 401, HTTP 403, HTTP 5xx, or a grounded duplicate-retry HTTP 4xx failure (for example 400 Bad Request after all required args were already grounded) AND there is no MISSING USER INPUT in SITUATIONAL CONTEXT, your FINAL answer MUST be exactly: "Sorry, your request cannot be completed at this time. Please try again later." Do NOT ask for any missing arg. Do NOT retry the action.
- If SITUATIONAL CONTEXT in Conversation History indicates FINAL AGENT STEP FAILED, you MUST inform the user that the latest automated attempt failed,when drafting final draft in natural professional language.
- When FINAL_AGENT_STEP[gate] or PREVIOUS_AGENT_STEP[gate] shows a failure or relevant attempted repair context, prefer that evidence over cached data when explaining the result (naturally for non-technical user), when drafting final draft in natural professional language.
- Do NOT present information as verified if the most recent gate step indicates a failed verification attempt.
- Always show the money in USD.
- Authentication for the latest user request must be grounded only in tool outputs that occur AFTER the latest USER password submission.
- A USER message containing a password is NOT itself evidence of successful authentication.
- Do NOT reuse older successful auth-sensitive tool outputs from earlier turns as proof that the latest password worked.
- Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
- Do NOT describe tool usage steps.
- Do NOT output any code blocks or code snippets.
- The Conversation History may contain cached tool traces labeled as `CACHED_TOOL_CALL[...]` and cached successful results labeled as `CACHED_SUCCESS[...]`.
- The Conversation History may contain FINAL_AGENT_STEP[gate] and PREVIOUS_AGENT_STEP[gate] entries from the current and prior rounds. Use them as grounded execution context for the final response.
- Give highest priority to the most recent FINAL_AGENT_STEP[gate], and when present its paired PREVIOUS_AGENT_STEP[gate], but use earlier ones too when they help explain or continue an ongoing workflow.
- The SITUATIONAL CONTEXT is authoritative programmatic state. Use it together with Conversation History, with special attention to the latest unresolved USER request and any still-unanswered USER queries carried forward in the workflow.
- Treat `CACHED_SUCCESS[...]` as reusable factual evidence from prior successful tool execution.
- ONLY use information explicitly present in the Conversation History (especially `CACHED_SUCCESS[...]` entries and other tool outputs), do NOT invent or assume any facts not in the history.
- If the needed value is not present, say what is missing and ask for the minimum needed input.
- If the Conversation History's recent FINAL AGENT STEP or SITUATIONAL CONTEXT contains a tool error with a HTTP 4xx or HTTP 5xx status code in relationship to password authentication, or a grounded action retry that still failed with HTTP 4xx/5xx after required args were already resolved, respond with exactly: "Sorry, your request cannot be completed at this time. Please try again later." Do NOT ask for password again. Do NOT retry the action.
- If the SITUATIONAL CONTEXT contains a RECENT AUTHENTICATION line showing a successful auth-sensitive tool result after the latest password-bearing USER message, treat that as authoritative evidence that the most recent authentication succeeded.
- ACTION COMPLETION RULE (highest priority for action requests): When the user's request was an action (donate, place a bid, fund wallet, etc.) and the corresponding action tool (grant_donation, campaign_donation, product_donation, place_bid, fund_wallet) returned a success response anywhere in the Conversation History — including inside gate repair steps — report that action as COMPLETED only if the acted-on entity is grounded as the same entity the user requested. If the tool succeeded but the chosen entity does not clearly match the user's requested title/name, do not present it as a confirmed match for that requested entity.

SOURCE GROUNDING RULES (STRICT):                                                                                                                         
- You are exclusively a Giver platform agent. ALL donation-related information, charity data, products, campaigns, and auctions must come from Giver API tool outputs in the Conversation History.                                                                                                          
- If a tool output contains an external URL (e.g., a charity's own website, a third-party donation page, or any non-Giver URL), do NOT direct the user to that URL and do NOT treat it as the basis for donation actions or donation recommendations. Such URLs are supplementary reference data only and must never override or conflict with Giver tool outputs.                                 
- If the user asks to donate or act on something, always ground your response in the cached tool calls, and final agent responses in Conversation History — never suggest the user go to an external site to complete the donation (which is recieved from possible fetch_url tool call in Conversation History).

EMPTY AND MISSING DATA RULES (STRICT):
- If a tool returned successfully but its data payload is empty (e.g., an empty list, zero count, or null records), you MUST tell the user clearly that no records were found. Do NOT invent, assume, or fabricate records that are not present in the tool output.
- If the SITUATIONAL CONTEXT section below contains EMPTY DATA notes, use them as authoritative evidence that the result set is empty. Report this to the user directly.
- If the SITUATIONAL CONTEXT section contains NO TOOLS EXECUTED or ALL TOOLS FAILED, and the user asked a data-dependent question, inform the user that the data could not be retrieved. Do NOT guess at what the data might contain.
- If the SITUATIONAL CONTEXT section contains MISSING USER INPUT, your ONLY job is to ask the user for exactly those inputs — nothing else. Do NOT attempt to answer the underlying question without the missing inputs. Do NOT fabricate placeholder values. If matching entity options are present, ask for the human-readable entity choice rather than the backend id.
- If the SITUATIONAL CONTEXT section contains UNRESOLVED ERROR, briefly inform the user that something went wrong and suggest they try again or rephrase. Include the tool name if it helps the user understand the issue.
- When no data is available, skip the Insights and Recommendations sections entirely. Only provide a Direct Answer stating that no data was found or the request could not be completed.
- If SITUATIONAL CONTEXT contradicts Conversation History after recent USER message, then prefer Conversation History as the source of truth for the final answer.

DATA COMPLETENESS RULES (STRICT):
- Your response must include ALL information from the Conversation History that is relevant to answering the user's current request. Do NOT omit, skip, or summarize away any records or items returned by tool outputs.
- Present information in professional, natural language — organized clearly but never as raw field names or key-value dumps from tool outputs. Translate technical field names into human-readable labels and use proper formatting.
- Include every meaningful detail that helps the user understand, compare, or act on the data — such as names, prices, quantities, statuses, descriptions, and locations. Omit only internal system fields (e.g., _id, __v, timestamps) unless the user specifically asked for them.
- When multiple tool outputs are relevant to the user's request, use data from ALL of them. For example, if the user asked for "grants, products, and campaigns," present all three sections using data from each corresponding tool output.
- When a tool output is truncated (ends with "...[truncated]"), present all the data that IS visible and note to the user that additional records may exist.
- Prioritize clarity and completeness together — the response should be maximally informative while remaining easy to read and well-organized.
- Only include details that are useful for the user's specific request. If the user asked about products, they need names, prices, quantities, and availability — not country codes, internal categories, or geographic metadata unless they asked for it. Use judgment about what a donor would actually need to see.
- These completeness rules apply when the user's latest request asks for information, exploration, or listing (e.g., "show me," "what are," "list," "compare," "share"). When the user's latest request is an action (e.g., "donate," "place a bid," "fund my wallet"), respond with a clear confirmation or status of that action — do not dump all tool output fields into the response.

RESPONSE STRUCTURE RULES:

If the latest user request is asking for information, data exploration, comparisons, or explanations 
or contain key words like "what", "how", "list", "compare", "difference", "recommend", "suggest", "best", "worst", etc., respond with:

    1) Direct Answer — provide the requested information using data available in the Conversation History
    2) Insights — briefly explain what the data implies or any meaningful patterns
    3) Recommendations — suggest practical next steps for the donor based on the available data

If the latest user request is a simple factual question or requires only a specific value or action, respond with:

    1) Direct Answer — clearly provide the requested information using the available Conversation History, but in helpful and informative manner

keep response concise and skip deep analysis.

RECOMMENDATION STYLE:
- Prioritize actionable guidance for donation decisions (where to donate, why, and what to watch for).
- Tie each recommendation to evidence from available data.
- If confidence is limited by missing data, state this clearly and suggest the next best donor action.

Now write the final answer based strictly on the Conversation History below, then SITUATIONAL CONTEXT, and finally the instruction block that follows.
"""

        transcript = format_history_for_responder(
            messages,
            last_agentic_step=state.get("last_agentic_step"),
        )
        situational_section = (
            situational_block.strip()
            if situational_block.strip()
            else "SITUATIONAL CONTEXT (system-generated, authoritative):\n- NONE"
        )
        final_instruction = (
            "FINAL INSTRUCTION:\n"
            "Answer the latest unresolved USER request using the Conversation History first and "
            "the Conversation history's content after latest USER query second, and the SITUATIONAL CONTEXT third. If user input is still missing, ask only for those "
            "missing values and include any grounded options you can infer from Giver tool outputs "
            "or TOOL CONTEXT. Never base donation guidance on external web URLs."
            f"\n\nTOOL CONTEXT (parameter descriptions and valid values for all available tools):\n{tool_context}"
        )
        final_prompt = [
            SystemMessage(content=system_prompt.strip()),
            HumanMessage(
                content=(
                    f"Conversation History:\n{transcript}\n\n"
                    f"{situational_section}\n\n"
                    f"{final_instruction}"
                )
            ),
        ]

        trunc_limit_hist = 100000
        if DEBUG_MESSAGES == 1 and SHOW_RESPONDER_HISTORY == 1:
            rich_print("\n" + "=" * 80)
            rich_print("RESPONDER CONVERSATION HISTORY")
            rich_print("=" * 80)
            truncated_transcript = transcript[:trunc_limit_hist] + (
                "..." if len(transcript) > trunc_limit_hist else ""
            )
            rich_print(f"{truncated_transcript}")
            if situational_block:
                rich_print("-" * 40)
                rich_print("SITUATIONAL CONTEXT INJECTED:")
                rich_print(situational_block)
            rich_print("=" * 80)

        summary = model.invoke(final_prompt)
        final_text = (summary.content or "").strip()

        return {"messages": [summary], "final_answer": final_text}

    return responder




def make_gate_node(
    tools_by_name: dict,
    max_react_steps: int = 4,
):
    """
    It sees, on every react step:
        original round history

        cached outputs

        attempted repairs so far

        errors already fixed

        errors still unresolved

        and then decides:

        which error to prioritize next

        whether to do a direct fix or prerequisite step

        whether success should mark that error fixed

    So this is now genuinely reactive in both:
        error-order selection

        repair-step selection
    """

    model = make_model(temperature=0.0)

    def _debug_gate_terminal(react_step: int, label: str, payload: Dict[str, Any]) -> None:
        if DEBUG_MESSAGES != 1:
            return
        rich_print(
            f"[GATE STEP {react_step} TERMINAL] {label} "
            f"{_compact_json(payload, max_chars=500)}"
        )

    def _strip_code_fences(text: str) -> str:
        text = (text or "").strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            return "\n".join(lines).strip()
        return text

    def _load_json_object(text: str) -> Dict[str, Any]:
        text = _strip_code_fences(text)
        if not text:
            return {}
        try:
            obj = json.loads(text)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
        return {}

    def _sanitize_step(raw_obj: Dict[str, Any]) -> Dict[str, Any] | None:
        if not isinstance(raw_obj, dict):
            return None

        step = raw_obj.get("step")
        if not isinstance(step, dict):
            return None

        tool_name = step.get("tool")
        args = step.get("args", {})

        if tool_name not in tools_by_name:
            return None
        if not isinstance(args, dict):
            return None

        return {"tool": tool_name, "args": args}

    def _sanitize_decision(
        raw_obj: Dict[str, Any],
        valid_error_ids: set[str],
    ) -> Dict[str, Any]:
        if not isinstance(raw_obj, dict):
            return {
                "target_error_id": None,
                "step": None,
                "mark_target_fixed_if_success": False,
                "done": True,
                "reason": "Invalid JSON returned by repair model.",
                "missing_args": [],
            }

        target_error_id = raw_obj.get("target_error_id")
        if target_error_id not in valid_error_ids:
            target_error_id = None

        step = _sanitize_step(raw_obj)
        done = bool(raw_obj.get("done", False))
        reason = str(raw_obj.get("reason", "")).strip()
        mark_target_fixed_if_success = bool(raw_obj.get("mark_target_fixed_if_success", False))

        raw_missing_args = raw_obj.get("missing_args", [])
        missing_args = []
        if isinstance(raw_missing_args, list):
            for item in raw_missing_args:
                if isinstance(item, str):
                    missing_args.append(item)

        return {
            "target_error_id": target_error_id,
            "step": step,
            "mark_target_fixed_if_success": mark_target_fixed_if_success,
            "done": done,
            "reason": reason,
            "missing_args": missing_args,
        }

    def _get_tool_arg_names(tool) -> set[str] | None:
        try:
            schema = None

            if hasattr(tool, "args_schema") and tool.args_schema is not None:
                schema = tool.args_schema
            elif hasattr(tool, "get_input_schema"):
                schema = tool.get_input_schema()

            if schema is None:
                return None

            if hasattr(schema, "model_fields"):   # pydantic v2
                return set(schema.model_fields.keys())

            if hasattr(schema, "__fields__"):     # pydantic v1
                return set(schema.__fields__.keys())

            if hasattr(schema, "schema"):
                raw = schema.schema()
                props = raw.get("properties", {})
                if isinstance(props, dict):
                    return set(props.keys())
        except Exception:
            return None

        return None

    def _filter_args_for_tool(tool, raw_args: dict) -> dict:
        args = dict(raw_args or {})
        args.pop("tool_name", None)

        allowed = _get_tool_arg_names(tool)
        if allowed is None:
            return args

        return {k: v for k, v in args.items() if k in allowed}

    def _normalize_python_query(query: str) -> str:
        q = (query or "").strip()
        try:
            q = q.encode("utf-8").decode("unicode_escape")
        except Exception:
            pass
        q = "\n".join(line.rstrip() for line in q.splitlines())
        q = "\n".join(line for line in q.splitlines() if line.strip())
        return q.strip()

    def _step_signature(step: Dict[str, Any]) -> str:
        tool_name = step.get("tool", "")
        args = dict(step.get("args", {}) or {})

        if tool_name == "Python_REPL" and "query" in args:
            args["query"] = _normalize_python_query(str(args["query"]))

        try:
            return json.dumps(
                {"tool": tool_name, "args": args},
                sort_keys=True,
                ensure_ascii=False,
            )
        except Exception:
            return str({"tool": tool_name, "args": args})

    def _error_args_from_tool_message(err: Dict[str, Any]) -> dict:
        tool_message = err.get("tool_message")
        if not isinstance(tool_message, str):
            return {}

        try:
            parsed = json.loads(tool_message)
            if isinstance(parsed, dict):
                maybe_args = parsed.get("args", {})
                if isinstance(maybe_args, dict):
                    if err.get("tool") == "Python_REPL" and "query" in maybe_args:
                        maybe_args = dict(maybe_args)
                        maybe_args["query"] = _normalize_python_query(str(maybe_args["query"]))
                    return maybe_args
        except Exception:
            return {}
        return {}

    def _tool_expects_structured_input(tool) -> bool:
        try:
            if hasattr(tool, "args_schema") and tool.args_schema is not None:
                return True
            if hasattr(tool, "get_input_schema"):
                schema = tool.get_input_schema()
                if schema is not None:
                    return True
        except Exception:
            pass
        return False

    async def _invoke_tool(tool, raw_args: dict):
        raw_args = dict(raw_args or {})
        structured = _tool_expects_structured_input(tool)

        if hasattr(tool, "ainvoke"):
            if structured:
                return await tool.ainvoke(raw_args)
            if not raw_args:
                return await tool.ainvoke("")
            if len(raw_args) == 1:
                return await tool.ainvoke(next(iter(raw_args.values())))
            return await tool.ainvoke(raw_args)

        if structured:
            return tool.invoke(raw_args)

        if not raw_args:
            return tool.invoke("")
        if len(raw_args) == 1:
            return tool.invoke(next(iter(raw_args.values())))
        return tool.invoke(raw_args)

    def _looks_like_error_text(s: str) -> bool:
        if not s:
            return False
        error_markers = (
            "Traceback (most recent call last):",
            "IndentationError",
            "SyntaxError",
            "NameError",
            "KeyError",
            "TypeError",
            "ValueError",
            "Exception",
            "ERROR",
            "Error:",
            "Invalid",
            "missing",
        )
        return any(marker in s for marker in error_markers)

    def _normalize_result(tool_name: str, result):
        if result is None:
            return {"ok": True, "result": None}

        if isinstance(result, str):
            s = result.strip()

            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    parsed = json.loads(s)
                    if isinstance(parsed, dict) and parsed.get("ok") is False:
                        return {
                            "ok": False,
                            "error": str(parsed.get("error", "Unknown error")),
                        }
                    return {"ok": True, "result": parsed}
                except json.JSONDecodeError:
                    pass

            if _looks_like_error_text(s):
                return {"ok": False, "error": s}

            return {"ok": True, "result": s}

        if isinstance(result, (dict, list, int, float, bool)):
            if isinstance(result, dict) and result.get("ok") is False:
                return {
                    "ok": False,
                    "error": str(result.get("error", "Unknown error")),
                }
            return {"ok": True, "result": result}

        return {"ok": True, "result": str(result)}

    def _mk_tool_call(tool_name: str, args: dict, tool_call_id: str) -> dict:
        return {
            "name": tool_name,
            "args": args or {},
            "id": tool_call_id,
            "type": "tool_call",
        }

    def _format_attempt_log(attempt_log: List[Dict[str, Any]]) -> str:
        if not attempt_log:
            return "(none)"

        lines = []
        for row in attempt_log:
            ok_label = "SUCCESS" if row["ok"] else "FAILED"
            args_str = _compact_json(row.get("args") or {}, max_chars=10000)
            output_str = _compact_json(row.get("output"), max_chars=10000)
            reason_str = (row.get("reason") or "").strip()
            missing = row.get("missing_args") or []
            done_label = " [done=true]" if row.get("done") else ""

            lines.append(
                f"[Step {row['react_step']}] target={row['target_error_id']} "
                f"tool={row['tool']} status={ok_label}{done_label}\n"
                f"  args    : {args_str}\n"
                f"  output  : {output_str}\n"
                f"  reason  : {reason_str or '—'}\n"
                f"  missing : {json.dumps(missing, ensure_ascii=False) if missing else '[]'}"
            )
        return "\n\n".join(lines)

    def _serialize_errors_for_prompt(errors: List[Dict[str, Any]]) -> str:
        rows = []
        for err in errors:
            rows.append({
                "error_id": err["error_id"],
                "tool": err.get("tool"),
                "tool_call_id": err.get("tool_call_id"),
                "error": err.get("error"),
                "tool_message": err.get("tool_message"),
            })
        return json.dumps(rows, ensure_ascii=False, indent=2)


    async def gate_node(state: dict) -> Dict:
        base_messages = list(state.get("messages", []) or [])
        base_plan = state.get("plan", {}) or {}
        base_missing_args = _normalize_missing_args(base_plan.get("missing_args", []))
        base_plan_steps = base_plan.get("steps", [])
        raw_original_errors = detect_recent_tool_errors(base_messages)

        if not raw_original_errors:
            return {
                "plan": {"steps": [], "missing_args": base_missing_args},
                "messages": [],
                "last_tool_error": None,
            }

        # Freeze original round history for LLM-visible history.
        llm_visible_messages: List[BaseMessage] = list(base_messages)

        emitted_messages: List[BaseMessage] = []
        seen_step_signatures: set[str] = set()
        missing_args: List[str] = list(base_missing_args)
        gate_notes: List[str] = []
        attempt_log: List[Dict[str, Any]] = []

        original_errors: List[Dict[str, Any]] = []
        for idx, err in enumerate(raw_original_errors, start=1):
            enriched = dict(err)
            enriched["error_id"] = f"E{idx}"
            original_errors.append(enriched)

        fixed_error_ids: set[str] = set()
        last_agentic_step: Dict[str, Any] | None = None

        def _current_unresolved_errors() -> List[Dict[str, Any]]:
            return [err for err in original_errors if err["error_id"] not in fixed_error_ids]

        def _current_fixed_errors() -> List[Dict[str, Any]]:
            return [err for err in original_errors if err["error_id"] in fixed_error_ids]

        for react_idx in range(max_react_steps):
            unresolved_errors = _current_unresolved_errors()
            fixed_errors = _current_fixed_errors()

            if not unresolved_errors:
                break

            gate_history = format_history_for_gate(llm_visible_messages)
            cache = build_cached_tool_outputs(base_messages + emitted_messages)
            tool_context = build_tool_context(tools_by_name)
            valid_tool_names = sorted(list(tools_by_name.keys()))
            valid_error_ids = {err["error_id"] for err in unresolved_errors}

            react_prompt = f"""
You are an AGENTIC GATE: a reactive repair executor for a tool-using LangGraph pipeline.

MISSION: Inspect each tool error, find grounded values for all required args by exhaustively scanning every available source, emit ONE repair action, and maintain an authoritative list of args that still require user input.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INFORMATION SOURCES (scan ALL of these before declaring any arg missing):

  SOURCE 1 — PLANNER'S ORIGINAL PLAN
    The steps and missing_args the planner produced at the start of this round.
    Use it to understand original intent and which args were already provided.

  SOURCE 2 — CURRENT ROUND HISTORY
    Full transcript of tool calls and their responses executed by the executor
    during this round (before gate repair began). Contains the raw tool outputs
    that most likely hold the entity ids, names, and values the repair needs.

  SOURCE 3 — CACHED TOOL OUTPUTS
    Deduplicated latest successful output per tool for the current round.
    Primary source for entity data (ids, names, amounts, types, etc.).

  SOURCE 4 — ALREADY ATTEMPTED REPAIR STEPS THIS GATE RUN
    Every repair step attempted so far — SUCCESS, FAILED, or done=true.
    Each row's "output" field is a real tool response and may contain values
    needed by subsequent steps. Read the output of EVERY prior step, even failed ones,
    because failed steps may have returned partial data or error details that reveal
    what value is actually needed.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MANDATORY REASONING PROTOCOL (perform internally before producing output):

  STEP A — UNDERSTAND THE ERROR AND THE PLANNER'S INTENDED SEQUENCE
    1. Read the target error from ERRORS STILL UNRESOLVED.
    2. Identify: the tool that failed, the args it was called with, and the exact error message.
    3. List every required arg for the repair tool from AVAILABLE TOOLS schema.
    4. Read PLANNER'S ORIGINAL PLAN (SOURCE 1) and note the intended step order.
       The planner's steps define the dependency chain: repair them in their original order.
       If a planner step failed, fix its inputs and retry it BEFORE moving to downstream steps.
       Do NOT run tools that are not in the planner's step sequence unless they are the only
       way to fetch a required arg that no source contains.

  STEP B — EXHAUSTIVE ARG RESOLUTION (for every required/missing arg, in source order)

    B0. NORMALIZE THE ARG NAME FIRST (do this before any lookup):
        Convert the arg name to a canonical entity word by stripping suffixes and
        normalizing case. Examples:
          grant_id → "grant"     grantId → "grant"     grant_ID → "grant"
          charityId → "charity"  charity_id → "charity"
          campaignId → "campaign" campaign_id → "campaign"
          productId → "product"  product_id → "product"
        Also note the planner may write missing_args in snake_case (e.g., "grant_id")
        while the tool schema uses camelCase (e.g., "grantId"). Treat them as the same arg.

    For each arg, scan sources in this order and stop at the first grounded match:

    B1. SOURCE 4 (repair step outputs) — read EVERY step's "output" field, including
        failed steps. Extract any field whose name, alias, or entity word matches the arg.
        CRITICAL: after any successful prerequisite step (e.g., list_charity_grants),
        immediately check if its output resolves any current missing_arg before
        declaring that arg still missing.
    B2. SOURCE 3 (cached tool outputs) — read every tool's output.
        Extract matching fields by name, alias, or nested-object pattern.
    B3. SOURCE 2 (current round history) — scan all tool responses.
        Extract matching fields.
    B4. SOURCE 1 (planner plan) — the original plan's tool args often contain already-
        resolved values (e.g., amount, password). Extract any non-placeholder value
        directly from the plan's args dict for the target tool.

    For each candidate value, apply these matching rules:
    • DIRECT MATCH      — field name exactly equals arg name (e.g., arg=grantId, field=grantId)
    • SNAKE↔CAMEL MATCH — normalize both sides: grant_id == grantId == grant_ID.
                          Always normalize before comparing.
    • ALIAS MATCH       — _id ↔ id ↔ {{entity}}Id ↔ {{entity}}ID ↔ {{entity}}_id
    • NESTED MATCH      — if output has {{"grants": {{"_id": "..."}}}} and arg is grantId or grant_id,
                          the entity key ("grants") contains the entity word ("grant"),
                          so grants[*]._id is the grantId value.
                          Apply to ALL entity types: grants, campaigns, charities, products,
                          auctions, donations, wallets, users, etc.
    • ARRAY MATCH:
                          If the entity list has ≥1 item, first look for the item whose
                          title/name clearly matches the user's request.
                          1. If the user explicitly named a grant/campaign/product/auction,
                             you may use an item only when a clear semantic match exists.
                          2. If no clear match exists for an explicitly named entity, do NOT
                          pick the first item, do NOT emit the downstream write/action tool,
                          and do NOT reinterpret any other item as "close enough".
                          Treat the target entity as unresolved.
                          3. Only when the user did NOT specify a distinct entity title/name
                             and the request is generic may you choose the first item.
                          4. Extract the matched item's _id field as the resolved entity id.
                             Example: if the user asked for "Community Library Renovation" and
                             the grants list only contains "dsad" and "testss", then grantId
                             remains unresolved and grant_donation must NOT be emitted.
    • LABEL-TO-ID MATCH — if a tool output pairs a human label with a backend id
                          (e.g., donationTypeName + donationTypeId), map the user's
                          label to the corresponding backend id.
    • PLANNER-VALUE     — if the planner's original plan args for the target tool already
                          contain a non-placeholder concrete value (e.g., "password": "Google@123",
                          "amount": 50), use that value directly.

    B5. PLANNER STEP AS PREREQUISITE (use this when B1–B4 all fail to find the value):
        If an arg value was not found in any source, look at PLANNER'S ORIGINAL PLAN (SOURCE 1)
        to identify which planner step was supposed to produce that value.
        Example: if grantId is missing and the planner had a step "list_charity_grants",
        that tool's output is the intended source of grantId.
        If that planner step failed (due to placeholder args) and its required input
        (e.g., charity_id) is now available from a prior repair step — run that planner
        step next with the corrected input. Set mark_target_fixed_if_success=false since
        this is a prerequisite, not the final repair.
        PRIORITY: always prefer repairing failed planner steps in their original order
        over running tools outside the planner's sequence.

        AVAILABLE TOOLS FALLBACK (applies when neither B1–B4 nor the planner plan resolves the arg):
        If the planner's original plan did NOT include a step that would produce the missing
        entity id, inspect AVAILABLE TOOLS descriptions for a tool whose output is known to
        return that entity type (e.g., "list_charity_grants" returns grantId values).
        If that tool's required inputs (e.g., charityId) are resolvable from any source,
        emit it as the next prerequisite step (mark_target_fixed_if_success=false).
        Never skip this fallback just because the tool was absent from the original plan —
        an entity id that can be fetched via an available tool is NEVER truly missing.

  STEP C — BUILD THE REPAIR ARGS
    • Only include args for which you found a concrete grounded value.
    • Never substitute placeholders, empty lists, empty objects, or invented values.
    • For structured/array args: assemble the full object from cached records field by field.
    • If a required arg remains unresolvable from all sources AND no planner step can
      fetch it → add that arg to missing_args and set done=true instead.

  STEP D — UPDATE missing_args (AUTHORITATIVE — apply every step)
    Start from: SO FAR PLANNER/STATE MISSING INPUTS CARRIED INTO GATE.
    Then apply STEP B results across ALL current missing_args — not just the target arg.

    MANDATORY CROSS-STEP RE-EVALUATION: after any successful repair step (especially
    prerequisite steps like list_charity_grants, discover_charities, etc.), re-run
    STEP B for EVERY arg currently in missing_args using the new step's output as
    SOURCE 4. Remove any arg that is now resolvable. This must happen before you
    decide whether to emit the next repair step or set done=true.

    CLASSIFY EACH missing_arg BEFORE deciding to remove it:

    NEGATIVE RESULT RULE (apply ONLY to truly empty results):
      A tool output is a NEGATIVE RESULT (does NOT resolve an arg) ONLY when:
      • The entity list is literally empty: [] or grants/campaigns/items array has 0 items.
      • Python_REPL output is a sentinel string ("GRANT_NOT_FOUND", "NOT_FOUND", etc.)
        instead of a real id value.
      This rule does NOT apply when the list is non-empty. However, a non-empty list does NOT
      resolve an explicitly named entity unless one item clearly matches the user's requested title.
      When a true NEGATIVE RESULT occurs (empty list):
      • Do NOT treat it as resolving the arg.
      • Add the human-readable arg descriptor to missing_args so the responder can
        inform the user that no records were found.

    TYPE A — ID/ENTITY ARG (auto-resolvable):
      Args like campaignId, grantId, charityId, productId, grant_id, etc.
      These reference a specific backend entity. Auto-resolve them via NESTED/ALIAS MATCH
      ONLY when a concrete non-null, non-sentinel entity _id was actually found in a source.
      REMOVE from missing_args once their entity _id is found in any source.
      KEEP in missing_args if the lookup returned no grounded match for the explicitly named entity.
      If a successful tool output already contains a non-empty candidate entity list for such an arg,
      the entity is still explorable. Do not stop at a bare backend-id request. Either:
      (a) resolve the entity from a grounded match, or
      (b) if no grounded match exists, keep the unresolved entity as a user-facing selection request
          based on the available entity titles/names from that list.

    TYPE B — USER-CHOICE ARG (NOT auto-resolvable unless user specified):
      Args like donation_type, category, donation_method, payment_method, or any field
      where a tool output lists multiple valid options and the user must choose one.
      The planner puts these in missing_args precisely because the user hasn't chosen.
      RULE: KEEP a TYPE B arg in missing_args UNLESS one of these is true:
        (a) The user's own message (CURRENT ROUND HISTORY USER line) explicitly names
            a value for it (e.g., user said "Sadqah" or "type: Sadqah"), OR
        (b) Only a single option exists in the tool output (no choice needed).
      Do NOT auto-select from a list of options just because the data is available.
      Selecting 'Sadqah' when the user hasn't specified is wrong — keep it in missing_args.

    TYPE C — AUTH ARG (requires user input ONLY when not already known):
      Args like password, token, pin. Cannot be recovered from tool outputs.
      HOWEVER — if the planner's original plan (SOURCE 1) or a user message in
      CURRENT ROUND HISTORY already contains the password as a concrete non-placeholder
      literal (e.g., "password": "Google@123"), it IS known and MUST be treated as
      resolved via B4 (PLANNER-VALUE). TYPE C means "cannot be extracted from API
      responses" — not "always treat as missing regardless of what the plan contains".
      KEEP in missing_args ONLY when the error is an auth failure (HTTP 401/403,
      "Invalid password") AND the password is not present in SOURCE 1 or user messages.

    REMOVE an arg when:
    • TYPE A: STEP B found its entity _id in any source.
    • TYPE B: user explicitly named the value in their message, OR only one option exists,
              OR the planner's original plan step args already contain a concrete
              non-placeholder value for this arg (B4 PLANNER-VALUE).
    • TYPE C: the concrete value is already in the planner's plan or a user message (B4).
    • The planner's original plan args contain a concrete non-placeholder literal value
      (not a placeholder like "<...>", "<VALUE>", "<PASSWORD>") — use it directly (B4).
      This applies to ALL arg types.

    ADD an arg when:
    • A failed repair step's error message explicitly names a field that must come from
      the user and is not available in any source.
    • The tool schema for the repair step requires a field that is not in any source
      and cannot be inferred.
    • NEVER add an arg that is already present in the planner's step args with a
      concrete non-placeholder value — a planner-supplied value is already resolved.

    KEEP an arg when:
    • TYPE B: multiple options exist, user hasn't expressed a preference, AND the
              planner's step args do NOT already contain a concrete value for it.
    • TYPE C: error is auth-related AND no concrete value exists in planner/user messages.
    • After exhausting all sources, the value is genuinely absent and requires user input.

    NEVER include in missing_args:
    • Any arg whose value is already present (non-placeholder) in the planner's step args.
    • TYPE A id-args whose entity data is already present in any source.
    • Authentication values UNLESS the current error is specifically an auth failure.

  STEP E — DECIDE THE REPAIR ACTION (follow this priority order)
    0. EMIT THE REPAIR STEP IF ALL ARGS ARE GROUNDED (check this before everything else):
       After completing STEP B and STEP D, if every required arg for the failing tool
       now has a resolved concrete value (from any source), you MUST emit the repair step.
       Do NOT return step=null or done=true in this case — that would be a contradiction.
       If your own reasoning in STEP B says "resolved grantId" and "password is in plan",
       then all args are grounded and you must emit the step with those values.

    1. FOLLOW THE PLANNER'S STEP SEQUENCE:
       Look at PLANNER'S ORIGINAL PLAN steps in order. Find the earliest step that
       (a) has not yet succeeded and (b) whose required inputs are now grounded.
       Repair that step first before any other. This ensures the dependency chain is
       resolved in the right order (e.g., list_charity_grants must run before grant_donation).

    2. RETRY A FAILED PLANNER STEP WITH CORRECTED ARGS:
       If a planner step failed because its args were placeholders, and the real values
       are now available from prior repair outputs or cached data — retry that step
       with corrected args. This is the most common repair pattern.

    3. RUN A PREREQUISITE OUTSIDE THE PLANNER'S LIST ONLY IF NEEDED:
       If a planner step's required input cannot be sourced from any existing output,
       run the tool from AVAILABLE TOOLS that is most likely to produce it (using B5).
       Set mark_target_fixed_if_success=false for this prerequisite step.
       IMPORTANT: do not run a tool that is not relevant to resolving the current
       unresolved error — every repair step must advance toward fixing a specific error.

    4. HTTP 500 WITH PLACEHOLDER ARGS:
       If the error is HTTP 500 AND the original call used placeholder args — the 500
       was likely caused by the bad args. Attempt the repair with grounded args.
       Do NOT treat HTTP 500 as automatically unrecoverable.

    5. MARK DONE ONLY AS A LAST RESORT:
       Set done=true only when: all planner steps have been retried with correct args,
       no further prerequisite can be run, and a required arg is genuinely not available
       from any source and must come from the user.
       Never mark done=true while a planner step that can be retried with grounded args
       still exists as an unresolved error.
       BLOCKING CHECK before setting done=true with missing grantId or campaignId:
         → Search SOURCE 4 (all repair step outputs) for any key containing "grant" or
           "campaign" with a non-empty array value.
         → Search SOURCE 3 (cached tool outputs) for the same.
         → If a non-empty array is found in EITHER source and a grounded entity match exists,
           apply ARRAY MATCH and emit the step.
         → If the user explicitly named an entity and no grounded match exists in the array,
           you may keep grantId/campaignId unresolved and request clarification instead of
           selecting an arbitrary first item.
         → If NO array is found in either source, scan AVAILABLE TOOLS for a tool that
           lists the entity type (e.g., list_charity_grants for grantId). If such a tool
           exists AND its required inputs (e.g., charityId) are grounded from any source,
           you MUST emit that tool as the next prerequisite step instead of marking the
           arg as missing. done=true is only valid when no such tool exists or its inputs
           are also unresolvable.
    6. NEVER REPEAT: if the exact same tool+args already appear in SOURCE 4, skip it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CONSTRAINTS:
- Tool descriptions contain dependency and ordering rules — obey them strictly.
- Do NOT invent ids, names, urls, passwords, or numeric values absent from all sources.
- Return exactly ONE repair action per step (or done=true).
- Authentication values (passwords, tokens) can never be auto-recovered — always require user.
- missing_args must contain ONLY args that genuinely require user input, never auto-resolvable ids.
- Do NOT use Python_REPL to scan or filter arrays/lists. You can read JSON data directly from
  SOURCE 3 and SOURCE 4. Python_REPL is for computation only (math, aggregation, formatting).
  If a planner step used Python_REPL for ID extraction and it failed, skip repairing that step —
  the gate extracts IDs directly from tool output using NESTED/ALIAS/ARRAY MATCH rules.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
COMPLEX ARGUMENT ASSEMBLY:
- For tools requiring structured args (arrays, nested objects): walk CACHED TOOL OUTPUTS
  field by field, match the user's original request to the correct record, and extract
  every required inner field. Do NOT pass empty containers — they will fail at the API level.

SELF-CONTAINMENT:
- Each repair step must be fully executable on its own with no implicit references.
- Pass all required values as explicit tool arguments.

SCHEMA:
- Only output args that belong to the target tool's schema. Omit debug fields like tool_name.

INTENT-PRESERVATION:
- Preserve the original user request. Do not substitute a different dataset or action.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PLANNER'S ORIGINAL PLAN FOR THIS ROUND:
{_compact_json(dict(steps=base_plan_steps, missing_args=list(missing_args)), max_chars=2000)}

CURRENT ROUND HISTORY:
{gate_history}

CACHED TOOL OUTPUTS (latest successful per tool, current round):
{cache}

SO FAR PLANNER/STATE MISSING INPUTS CARRIED INTO GATE:
{_compact_json(missing_args, max_chars=1000)}

ERRORS FIXED SO FAR:
{_serialize_errors_for_prompt(fixed_errors)}

ERRORS STILL UNRESOLVED:
{_serialize_errors_for_prompt(unresolved_errors)}

ALREADY ATTEMPTED REPAIR STEPS THIS GATE RUN (includes ALL steps — SUCCESS, FAILED, done=true):
{_format_attempt_log(attempt_log)}

AVAILABLE TOOLS:
{tool_context}

VALID TOOL NAMES:
{valid_tool_names}

VALID UNRESOLVED ERROR IDS:
{sorted(list(valid_error_ids))}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT JSON ONLY — no prose, no markdown:
{{
  "target_error_id": "E1" | "E2" | null,
  "step": {{"tool": "tool_name", "args": {{"arg_name": "value"}}}} | null,
  "mark_target_fixed_if_success": true | false,
  "done": true | false,
  "reason": "one evidence-based sentence: which error, why this repair, which source provided the key values",
  "missing_args": []
}}

RULES:
1. Return at most ONE repair step per response.
2. target_error_id MUST always be set to the error you are working on, from VALID UNRESOLVED ERROR IDS.
   target_error_id must be null ONLY when you cannot identify ANY valid target error at all —
   this should be extremely rare. When setting done=true, still set target_error_id to the error
   you were addressing.
3. If the target error is downstream and a prerequisite is missing, repair the prerequisite first.
4. Set mark_target_fixed_if_success=true only if this step directly resolves target_error_id.
5. Set mark_target_fixed_if_success=false if this step is only a prerequisite.
6. Never repeat a step that is semantically equivalent to one already in ALREADY ATTEMPTED REPAIR STEPS.
7. If no safe automatic repair exists, set done=true with step=null AND target_error_id set.
8. missing_args is your full authoritative list after applying STEP D above.
   When done=true, it must be complete — every arg still requiring user input, nothing more.
   For explorable entity ids like grantId/campaignId/productId/auctionId with available
   candidate lists, this means a user-facing entity choice remains needed; do not treat that
   as an instruction to ask for a raw backend id.
9. Never pass empty lists or empty objects for args that require real data.
10. The "reason" field must cite which source (SOURCE 1/2/3/4) provided the key grounded values used.
11. When the user explicitly named a grant/campaign/product/auction and no grounded title/name
    match exists in the returned entity list, do NOT pick the first item. Keep that entity id
    unresolved so the user can clarify or be told no matching entity was found.
12. For write/action tools (donations, bids, wallet funding, or similar), an explicitly named
    entity with no grounded match is a HARD BLOCK: return step=null, done=true, and keep the
    entity arg in missing_args. Never execute the action against a different entity.
""".strip()
            


            # if DEBUG_MESSAGES == 1:
            #     rich_print("\n" + "=" * 80)
            #     rich_print(f"AGENTIC GATE REACT STEP {react_idx + 1} — REPAIR PROMPT")
            #     rich_print("=" * 80)
            #     rich_print(react_prompt)
            #     rich_print("=" * 80)

            # if DEBUG_MESSAGES == 1 and SHOW_GATE_CACHED_TOOL_OUTPUTS == 1:
            #     rich_print("CACHED TOOL OUTPUTS:")
            #     rich_print(cache)
            #     rich_print("=" * 80)

            # if DEBUG_MESSAGES == 1 and SHOW_GATE_FIXED_ERRORS == 1:
            #     rich_print("So far errors fixed:")
            #     rich_print(_serialize_errors_for_prompt(fixed_errors))
            #     rich_print("=" * 80)

            # if DEBUG_MESSAGES == 1 and SHOW_GATE_UNRESOLVED_ERRORS == 1:
            #     rich_print("Errors still unresolved:")
            #     rich_print(_serialize_errors_for_prompt(unresolved_errors))
            #     rich_print("=" * 80)

            # if DEBUG_MESSAGES == 1 and SHOW_GATE_ATTEMPTED_REPAIRS == 1:
            #     rich_print("ALREADY ATTEMPTED REPAIR STEPS THIS GATE RUN:")
            #     rich_print(_format_attempt_log(attempt_log))
            #     rich_print("=" * 80)

            # if DEBUG_MESSAGES == 1 and SHOW_GATE_UNRESOLVED_ERROR_IDS == 1:
            #     rich_print("VALID UNRESOLVED ERROR IDS:")
            #     rich_print(sorted(list(valid_error_ids)))
            #     rich_print("=" * 80)

            resp = model.invoke([HumanMessage(content=react_prompt)])
            raw_text = (resp.content or "").strip()
            raw_obj = _load_json_object(raw_text)

            if DEBUG_MESSAGES == 1:
                rich_print("\n" + "=" * 80)
                rich_print(f"AGENTIC GATE REACT STEP {react_idx + 1}")
                rich_print("=" * 80)
                rich_print(raw_text if raw_text else "[EMPTY MODEL OUTPUT]")
                rich_print("=" * 80)

            if not raw_text:
                gate_notes.append("Repair model returned empty output.")
                break

            if not isinstance(raw_obj, dict) or not raw_obj:
                gate_notes.append("Repair model returned invalid JSON.")
                break

            decision = _sanitize_decision(raw_obj, valid_error_ids=valid_error_ids)

            target_error_id = decision["target_error_id"]
            step = decision["step"]
            done = decision["done"]
            reason = decision["reason"]
            mark_target_fixed_if_success = decision["mark_target_fixed_if_success"]

            if done and step is None:
                missing_args = _normalize_missing_args(decision["missing_args"])
                gate_notes.append(reason or "Repair model stopped.")
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": target_error_id,
                    "tool": "gate_decision",
                    "args": {},
                    "ok": False,
                    "output": reason or "Gate decided no further automatic repair is possible.",
                    "reason": reason or "Gate decided no further automatic repair is possible.",
                    "missing_args": missing_args,
                    "done": True,
                }
                _debug_gate_terminal(react_idx + 1, "decision", last_agentic_step)
                break

            if target_error_id is None:
                gate_notes.append(
                    reason or "Repair model did not choose a valid unresolved error."
                )
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": None,
                    "tool": "gate_decision",
                    "args": {},
                    "ok": False,
                    "output": reason or "Gate could not identify a valid error target.",
                    "reason": reason or "Gate could not identify a valid error target.",
                    "missing_args": missing_args,
                    "done": True,
                }
                _debug_gate_terminal(react_idx + 1, "invalid_target", last_agentic_step)
                break

            target_error = next(
                (err for err in unresolved_errors if err["error_id"] == target_error_id),
                None,
            )

            if done and not step:
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": target_error_id,
                    "tool": None,
                    "args": {},
                    "ok": False,
                    "output": (
                        target_error.get("error")
                        if isinstance(target_error, dict) else "Automatic repair not possible."
                    ),
                    "reason": reason,
                    "missing_args": missing_args,
                    "done": True,
                }
                gate_notes.append(f"No safe automatic repair available for `{target_error_id}`.")
                _debug_gate_terminal(react_idx + 1, "done_without_step", last_agentic_step)
                break


            if target_error is None:
                gate_notes.append(
                    f"Repair model selected invalid target error id `{target_error_id}`."
                )
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": target_error_id,
                    "tool": "gate_decision",
                    "args": {},
                    "ok": False,
                    "output": f"Invalid target error id `{target_error_id}` — not in unresolved set.",
                    "reason": f"Repair model selected an invalid target error id.",
                    "missing_args": missing_args,
                    "done": True,
                }
                _debug_gate_terminal(react_idx + 1, "unknown_target", last_agentic_step)
                break

            if step is None:
                gate_notes.append(
                    reason or f"No safe repair step returned for target error `{target_error_id}`."
                )
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": target_error_id,
                    "tool": "gate_decision",
                    "args": {},
                    "ok": False,
                    "output": reason or f"No safe repair step available for `{target_error_id}`.",
                    "reason": reason or f"No safe repair step returned for target error `{target_error_id}`.",
                    "missing_args": missing_args,
                    "done": True,
                }
                _debug_gate_terminal(react_idx + 1, "missing_step", last_agentic_step)
                break

            tool_name = step["tool"]
            tool = tools_by_name[tool_name]
            raw_args = _filter_args_for_tool(tool, step.get("args", {}) or {})
            normalized_step = {"tool": tool_name, "args": raw_args}
            sig = _step_signature(normalized_step)

            if sig in seen_step_signatures:
                gate_notes.append(
                    f"Skipped duplicate repair step for `{tool_name}` targeting `{target_error_id}`."
                )
                previous_attempt = attempt_log[-1] if attempt_log else None
                # A duplicate retry should not resurrect stale planner missing_args.
                # Reuse the previous executed attempt's missing_args, which reflect
                # what was actually unresolved after grounding.
                if previous_attempt:
                    missing_args = _normalize_missing_args(previous_attempt.get("missing_args"))
                else:
                    missing_args = []
                last_agentic_step = {
                    "react_step": react_idx + 1,
                    "target_error_id": target_error_id,
                    "tool": tool_name,
                    "args": raw_args,
                    "ok": False,
                    "output": "Repair step skipped — identical step already attempted this gate run.",
                    "reason": "Duplicate repair step detected; no further automatic repair attempted.",
                    "missing_args": missing_args,
                    "done": True,
                }
                if previous_attempt:
                    last_agentic_step["previous_attempt"] = {
                        "react_step": previous_attempt.get("react_step"),
                        "tool": previous_attempt.get("tool"),
                        "args": previous_attempt.get("args"),
                        "ok": previous_attempt.get("ok"),
                        "reason": previous_attempt.get("reason", ""),
                        "missing_args": previous_attempt.get("missing_args") or [],
                        "done": previous_attempt.get("done"),
                        "output": previous_attempt.get("output"),
                    }
                _debug_gate_terminal(react_idx + 1, "duplicate_step", last_agentic_step)
                break

            seen_step_signatures.add(sig)

            tool_call_id = str(uuid4())

            ai_tool_call_msg = AIMessage(
                content="",
                tool_calls=[_mk_tool_call(tool_name, raw_args, tool_call_id)],
            )
            emitted_messages.append(ai_tool_call_msg)

            try:
                result = await _invoke_tool(tool, raw_args)
                payload = _normalize_result(tool_name, result)
            except Exception as e:
                payload = {
                    "ok": False,
                    "error": str(e),
                    "tool": tool_name,
                    "args": raw_args,
                }

            # find semantic errors in the tool output, even if the tool call itself succeeded
            semantic_error = _detect_semantic_error(payload)

            semantic_ok = bool(payload.get("ok", False)) and semantic_error is None

            semantic_output = (
                payload.get("result")
                if semantic_ok
                else semantic_error if semantic_error is not None else payload.get("error")
            )

            tool_msg = ToolMessage(
                content=json.dumps(payload, ensure_ascii=False, default=str),
                name=tool_name,
                tool_call_id=tool_call_id,
            )
            emitted_messages.append(tool_msg)

            # Update missing_args to reflect what this step resolved.
            # Only applied on success so a failed step leaves the list unchanged.
            if semantic_ok:
                missing_args = _normalize_missing_args(decision["missing_args"])

            attempt_log.append({
                "react_step": react_idx + 1,
                "target_error_id": target_error_id,
                "tool": tool_name,
                "args": raw_args,
                "ok": semantic_ok,
                "output": semantic_output,
                "reason": decision.get("reason", ""),
                "missing_args": _normalize_missing_args(decision.get("missing_args")),
                "done": bool(decision.get("done", False)),
            })
            # Capture the post-execution attempt entry as last_agentic_step.
            # This is intentionally sourced from attempt_log (after tool invocation)
            # rather than from the decision dict (before invocation), so the fields
            # reflect actual execution outcomes (ok, output) and only the whitelist
            # of meaningful context fields is exposed to planner/responder.
            last_agentic_step = attempt_log[-1]

            trunc_lim_tool = TRUNCATION_LIMIT_GATE_TOOL_OUTPUT

            if DEBUG_MESSAGES == 1 and SHOW_GATE_TOOL_OUTPUTS == 1:
                rich_print(
                    f"[GATE STEP {react_idx + 1} RESULT] tool={tool_name} "
                    f"ok={semantic_ok} "
                    f"output={str(semantic_output)[:trunc_lim_tool]}"
                )

            # if output of last_agentic_step contains "Invalid password" or "Missing password" or similar, then break agentic loop
            if not semantic_ok and isinstance(semantic_output, str) and re.search(r"(invalid|missing).{0,20}password", semantic_output, re.IGNORECASE):
                missing_args = _normalize_missing_args(["password"])
                gate_notes.append(
                    f"Repair step `{tool_name}` output indicates a password issue: {semantic_output}. Stopping automatic repair."
                )
                last_agentic_step["reason"] = "Detected password-related issue in tool output; halting further automatic repair."
                last_agentic_step["missing_args"] = missing_args
                last_agentic_step["done"] = True
                break
                

            if not semantic_ok:
                gate_notes.append(
                    f"Repair step `{tool_name}` for `{target_error_id}` failed: {payload.get('error', 'Unknown error')}"
                )
            else:
                # Direct repair succeeds if model explicitly says so,
                # or if the repair step tool matches the target error tool.
                direct_fix = (
                    mark_target_fixed_if_success
                    or tool_name == target_error.get("tool")
                )

                if direct_fix:
                    fixed_error_ids.add(target_error_id)
                    gate_notes.append(
                        f"Repair step `{tool_name}` succeeded and marked `{target_error_id}` fixed."
                    )
                else:
                    gate_notes.append(
                        f"Repair step `{tool_name}` succeeded as prerequisite work for `{target_error_id}`."
                    )

            if done:
                break

        unresolved_errors = _current_unresolved_errors()

        # Persist the final gate step as a normal AIMessage so it becomes part
        # of durable conversation history for future planner/responder/gate turns.
        if last_agentic_step:
            if len(attempt_log) >= 2 and not isinstance(last_agentic_step.get("previous_attempt"), dict):
                prev = attempt_log[-1]
                if (
                    last_agentic_step.get("tool") == prev.get("tool")
                    and last_agentic_step.get("react_step") == prev.get("react_step")
                    and len(attempt_log) >= 2
                ):
                    prev = attempt_log[-2]
                last_agentic_step["previous_attempt"] = {
                    "react_step": prev.get("react_step"),
                    "tool": prev.get("tool"),
                    "args": prev.get("args"),
                    "ok": prev.get("ok"),
                    "reason": prev.get("reason", ""),
                    "missing_args": prev.get("missing_args") or [],
                    "done": prev.get("done"),
                    "output": prev.get("output"),
                }
            gate_step_line = _format_last_agentic_step(last_agentic_step)
            if gate_step_line:
                emitted_messages.append(AIMessage(content=gate_step_line))

        note = (
            "System Note: Agentic gate finished with unresolved tool error(s)."
            if unresolved_errors
            else "System Note: Agentic gate completed repair pass."
        )

        if gate_notes:
            note += " " + " | ".join(gate_notes[:4])

        if missing_args:
            note += f" CURRENT_MISSING_ARGS_JSON={json.dumps(missing_args, ensure_ascii=False)}"

        emitted_messages.append(AIMessage(content=note))

        
        return {
            "plan": {"steps": [], "missing_args": missing_args},
            "messages": emitted_messages,
            "last_tool_error": unresolved_errors[0] if unresolved_errors else None,
            "last_agentic_step": last_agentic_step,
        }

    return gate_node

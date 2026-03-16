import json
from uuid import uuid4
from typing import Dict, List, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from rich import print as rich_print

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
        - Use any FINAL_AGENT_STEP[gate] context in Chat History as grounded execution context when choosing the next plan.
        - FINAL_AGENT_STEP[gate] may include reason and missing_args from the last gate decision; use them to continue unfinished repair work correctly.
        - The most recent FINAL_AGENT_STEP[gate] and r is especially important when continuing or repairing a multi-round workflow.
        - You must follow those dependency chains.
        - If a later tool depends on an earlier tool's result, you must still include the later tool in the plan when it is part of the required chain.
        - When an argument is not yet known because it will come from a previous tool result, use a symbolic placeholder instead of omitting the dependent tool.
        - If a required value cannot be recovered from prior successful outputs or from tools earlier in THIS plan, do NOT leave it as a placeholder. Put that field name in missing_args.
        - The missing_args list must represent the current unresolved user inputs after considering all reusable prior tool outputs in chat history.

        PLACEHOLDER POLICY:
        - You may use symbolic placeholders for arguments that will be derived from earlier tool outputs.
        - Do NOT invent fake final values.
        - Instead use placeholders such as:
        - "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"
        - "<WEBSITE_URL_FROM_CHARITY_DETAILS>"
        - Every placeholder must correspond to a value that an earlier tool in the plan or cached history can realistically produce.
        - Prefer a complete dependency-aware plan over a single first-step plan when tool descriptions define a normal chain.

        MISSING-ARG POLICY:
        - For action tools like donations, bids, wallet funding, or other write operations: if any required final argument is not already known and not recoverable from earlier tools, add its exact field name to missing_args.
        - Do not ask for args already supplied in the latest user message.
        - Do not include any arg in missing_args if it can be grounded from prior successful tool outputs already present in chat history.

        PLANNING RULES:
        1. Identify all user intents.
        2. Reuse prior successful tool outputs where sufficient.
        3. Read and obey dependency instructions in tool descriptions.
        4. If a vague charity name is mentioned, follow the default charity chain:
        discover_charities -> charity_details -> fetch_url
        5. Do not stop at discovery for a "tell me about X" query if deeper tools are part of the required chain.
        6. If downstream args are not yet known, include the downstream tool with a symbolic placeholder.
        7. Only return steps: [] if chat history already fully satisfies the request.
        8. If the previous round already asked for missing inputs, shrink that list if the latest user message or prior successful tool outputs now cover some of them.

        SITUATIONAL CONTEXT USAGE:
        The conversation history may include a section labeled "SITUATIONAL CONTEXT".

        This context summarizes important state from previous agent rounds, such as:
        - missing tool arguments
        - unresolved tool errors
        - constraints discovered by the gate agent

        When SITUATIONAL CONTEXT contains missing arguments:
        - Prefer plans that recover those arguments using tools if possible.
        - If the arguments cannot be recovered from tools, ask the user for them.

        Treat SITUATIONAL CONTEXT as authoritative state from the previous round.
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

        Previously Requested Missing Inputs:
        {_compact_json(prior_missing_args, max_chars=500)}

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

        empty_data_notes = _detect_empty_results(current_round_tool_msgs)
        lines = []

        # 1) Missing user input
        if missing_args:
            lines.append(
                f"MISSING USER INPUT: The system determined the following inputs "
                f"are required from the user before the requested action can proceed: "
                f"{', '.join(missing_args)}. "
                f"Ask the user for ONLY these specific values. "
                f"Do NOT attempt the action without them."
            )

        # 2) Final gate step for this round (preferred over coarse tool heuristics)
        has_final_gate_step = isinstance(last_agentic_step, dict) and bool(last_agentic_step)

        if has_final_gate_step:
            step_ok = last_agentic_step.get("ok")
            step_tool = last_agentic_step.get("tool") or "gate_decision"
            step_output = str(last_agentic_step.get("output", ""))[:250]
            step_reason = str(last_agentic_step.get("reason", "")).strip()
            step_missing_args = list(last_agentic_step.get("missing_args") or [])
            step_done = bool(last_agentic_step.get("done"))

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
            return ""

        return (
            "\n\nSITUATIONAL CONTEXT (system-generated, authoritative):\n"
            + "\n".join(f"- {line}" for line in lines)
        )

    def responder(state: dict) -> Dict:
        messages = list(state.get("messages", []) or [])

        # Locate the latest user message
        latest_user_idx = None
        latest_user_content = ""
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                latest_user_idx = i
                latest_user_content = (messages[i].content or "").strip()
                break

        # === Programmatic password short-circuit ===
        # Only fires when the user's message is a password submission.
        # Now checks specifically for auth-gated tool success rather than
        # any tool success, so a successful read-only tool (e.g.,
        # get_active_auctions) alongside a failed auth tool (e.g.,
        # place_bid with wrong password) won't bypass this check.
        if latest_user_idx is not None and latest_user_content.lower().startswith("password:"):
            fresh_auth_tool_success = False
            for m in messages[latest_user_idx + 1:]:
                if not isinstance(m, ToolMessage):
                    continue
                payload = _safe_json_loads((m.content or "").strip())
                if payload is not None and _extract_tool_error(payload) is None:
                    if m.name in AUTH_GATED_TOOLS:
                        fresh_auth_tool_success = True
                        break

            if not fresh_auth_tool_success:
                return {
                    "messages": [AIMessage(content="Please enter password")],
                    "final_answer": "Please enter password",
                }

        # Build situational context from programmatic signals
        current_round = get_current_round_messages(messages)
        current_round_tool_msgs = [
            m for m in current_round if isinstance(m, ToolMessage)
        ]
        situational_block = _build_situational_block(state, current_round_tool_msgs)

        
        system_prompt = """
You are a donor-assisting AI agent on a donation website that produces FINAL, USER-FACING answers.
Assume the user may be a confused or first-time donor who needs clear guidance.

OUTPUT RULES (STRICT):
- If in Conversation History, there is mention of 'Invalid password' or a similar auth failure (AFTER only last USER message), your FINAL answer MUST be exactly: "Please enter password" (without quotes).
- After getting password, use the conversation history to determine course of response.
- If SITUATIONAL CONTEXT in Conversation History indicates FINAL AGENT STEP FAILED, you MUST inform the user that the latest automated attempt failed,when drafting final draft in natural professional language.
- When FINAL_AGENT_STEP[gate] shows a failure, prefer that evidence over cached data when explaining the result (naturally for non-technical user), when drafting final draft in natural professional language.
- Do NOT present information as verified if the most recent gate step indicates a failed verification attempt.
- Always show the money in USD.
- Authentication for the latest user request must be grounded only in tool outputs that occur AFTER the latest USER password submission.
- A USER message containing a password is NOT itself evidence of successful authentication.
- If the latest password submission is not followed by a successful relevant tool result for the latest requested action, your FINAL answer MUST be exactly: "Please enter password" (without quotes).
- Do NOT reuse older successful auth-sensitive tool outputs from earlier turns as proof that the latest password worked.
- Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
- Do NOT describe tool usage steps.
- Do NOT output any code blocks or code snippets.
- The Conversation History may contain cached tool traces labeled as `CACHED_TOOL_CALL[...]` and cached successful results labeled as `CACHED_SUCCESS[...]`.
- The Conversation History may contain FINAL_AGENT_STEP[gate] entries from the current and prior rounds. Use them as grounded execution context for the final response.
- Give highest priority to the most recent FINAL_AGENT_STEP[gate], but use earlier ones too when they help explain or continue an ongoing workflow.
- Treat `CACHED_SUCCESS[...]` as reusable factual evidence from prior successful tool execution.
- ONLY use information explicitly present in the Conversation History (especially `CACHED_SUCCESS[...]` entries and other tool outputs), do NOT invent or assume any facts not in the history.
- If the needed value is not present, say what is missing and ask for the minimum needed input.

EMPTY AND MISSING DATA RULES (STRICT):
- If a tool returned successfully but its data payload is empty (e.g., an empty list, zero count, or null records), you MUST tell the user clearly that no records were found. Do NOT invent, assume, or fabricate records that are not present in the tool output.
- If the SITUATIONAL CONTEXT section below contains EMPTY DATA notes, use them as authoritative evidence that the result set is empty. Report this to the user directly.
- If the SITUATIONAL CONTEXT section contains NO TOOLS EXECUTED or ALL TOOLS FAILED, and the user asked a data-dependent question, inform the user that the data could not be retrieved. Do NOT guess at what the data might contain.
- If the SITUATIONAL CONTEXT section contains MISSING USER INPUT, your ONLY job is to ask the user for exactly those inputs — nothing else. Do NOT attempt to answer the underlying question without the missing inputs. Do NOT fabricate placeholder values.
- If the SITUATIONAL CONTEXT section contains UNRESOLVED ERROR, briefly inform the user that something went wrong and suggest they try again or rephrase. Include the tool name if it helps the user understand the issue.
- When no data is available, skip the Insights and Recommendations sections entirely. Only provide a Direct Answer stating that no data was found or the request could not be completed.


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

    1) Direct Answer — clearly provide the requested information using the available Conversation History

keep response concise and skip deep analysis.

RECOMMENDATION STYLE:
- Prioritize actionable guidance for donation decisions (where to donate, why, and what to watch for).
- Tie each recommendation to evidence from available data.
- If confidence is limited by missing data, state this clearly and suggest the next best donor action.

Now write the final answer based strictly on the Conversation History below, including any `CACHED_TOOL_CALL[...]` and `CACHED_SUCCESS[...]` entries.
"""

        transcript = format_history_for_responder(
            messages,
            last_agentic_step=state.get("last_agentic_step"),
        )
        final_prompt = [
            HumanMessage(
                content=f"{system_prompt}{situational_block}\n\nConversation History:\n{transcript}"
            )
        ]

        trunc_limit_hist = TRUNCATION_LIMIT_RESPONDER_HISTORY
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
            return "[]"

        rows = []
        for row in attempt_log:
            rows.append({
                "react_step": row["react_step"],
                "target_error_id": row["target_error_id"],
                "tool": row["tool"],
                "args": row["args"],
                "ok": row["ok"],
                "output": row["output"],
            })
        return json.dumps(rows, ensure_ascii=False, indent=2)

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
        base_missing_args = _normalize_missing_args((state.get("plan", {}) or {}).get("missing_args", []))
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
You are AGENTIC_GATE, a repair executor for a tool-using LangGraph pipeline.

Your job is to reactively choose:
1. which unresolved error to work on next
2. which repair step to try next

You must make that choice based on:
- original round history
- cached outputs
- attempted repairs so far
- errors already fixed
- errors still unresolved

VERY IMPORTANT:
- Tool descriptions contain usage policy, dependency rules, and ordering constraints.
- You must obey tool dependency rules.
- Prefer repairing missing prerequisites before retrying downstream tools.
- Reuse grounded values from cached successful outputs.
- Do NOT invent ids, names, urls, passwords, numeric values, or other arguments not present in history/cache.
- Return exactly ONE next repair action or mark done.
- You are responsible for maintaining the CURRENT unresolved user-input list across repair steps.
- Any `missing_args` you output must be the current authoritative list after considering all successful repair steps so far.
- On the final `done: true` step, `missing_args` must contain every remaining required argument that is still not recoverable from available tool calls or cached successful outputs, and must exclude anything already recovered.
- CURRENT ROUND HISTORY may contain FINAL_AGENT_STEP[gate] entries from prior rounds.
- Use prior FINAL_AGENT_STEP[gate] entries as grounded context about what was last attempted, what succeeded, and what failed in earlier rounds.
- Prefer continuity with the most recent FINAL_AGENT_STEP[gate] when the user is continuing an unfinished workflow.

COMPLEX ARGUMENT ASSEMBLY RULE:
- When a failed tool requires structured arguments (lists, nested objects), you MUST actively extract concrete values from CACHED TOOL OUTPUTS to build those arguments.
- Do NOT pass empty lists, empty objects, or zero values as a shortcut to satisfy type validation. An empty list is not a valid repair — it will fail at the API level.
- Walk through the cached outputs field by field. Match the user's original request (e.g., product name, campaign title) to items in the cached data to select the correct records.
- For list-of-object arguments (e.g., products: [{{"partner": "...", "charityProd": "..."}}]), construct each object by extracting real field values (_id, pricePerUnit, category, partner, etc.) from the cached tool output that returned those records.
- If the cached data does not contain a required field value and no other available tool can provide it, add that field name to missing_args and set done: true. Do NOT substitute a placeholder, empty value, or guess.

SELF-CONTAINMENT RULE:
- Any repaired step must be executable on its own.
- Do NOT reference implicit variables from previous tool outputs.
- If a computation tool needs prior tool output, pass grounded required data through valid tool arguments only.
- If that is not possible for the tool schema, do not emit that repair step.

SCHEMA RULE:
- Output only arguments that belong to the target tool's real schema.
- Do not include bookkeeping/debug fields such as `tool_name`.

INTENT-PRESERVATION RULE:
- Preserve the original latest user request.
- Do not switch to a different statistic, easier computation, or different dataset.

CURRENT ROUND HISTORY:
{gate_history}

CACHED TOOL OUTPUTS:
{cache}

PLANNER/STATE MISSING INPUTS CARRIED INTO GATE:
{_compact_json(missing_args, max_chars=500)}

So far errors fixed:
{_serialize_errors_for_prompt(fixed_errors)}

Errors still unresolved:
{_serialize_errors_for_prompt(unresolved_errors)}

ALREADY ATTEMPTED REPAIR STEPS THIS GATE RUN:
{_format_attempt_log(attempt_log)}

AVAILABLE TOOLS:
{tool_context}

VALID TOOL NAMES:
{valid_tool_names}

VALID UNRESOLVED ERROR IDS:
{sorted(list(valid_error_ids))}

OUTPUT JSON ONLY:
{{
  "target_error_id": "E1" | "E2" | null,
  "step": {{"tool": "tool_name", "args": {{"arg_name": "value"}}}} | null,
  "mark_target_fixed_if_success": true | false,
  "done": true | false,
  "reason": "one short evidence-based reason for why this unresolved error should be worked on next and why this repair step is appropriate",
  "missing_args": []
}}

RULES:
1. You choose which unresolved error to address next.
2. Return at most ONE repair step.
3. If the chosen target error is downstream and prerequisites are missing, you may choose a prerequisite repair step first.
4. If your chosen repair step directly fixes the chosen error, set `mark_target_fixed_if_success` to true.
5. If your chosen repair step is only a prerequisite and does not yet directly fix the chosen error, set `mark_target_fixed_if_success` to false.
6. Do not repeat an identical or semantically equivalent repair step already attempted in this gate run.
7. If no safe automatic repair is possible, set `done`: true.
8. NEVER pass empty lists or empty objects for arguments that require real data. If the original error was caused by placeholder strings, the repair MUST replace them with actual values from cached outputs, not with empty containers.
9. When a prior missing arg becomes recoverable from a successful repair step or cached tool output, remove it from `missing_args`.
10. When `done` is true, do not return a partial list. Return the full remaining unresolved set the user must provide next.
""".strip()
            
            if DEBUG_MESSAGES == 1 and (SHOW_GATE_HISTORY == 1 or 
                                        SHOW_GATE_CACHED_TOOL_OUTPUTS == 1 or 
                                        SHOW_GATE_FIXED_ERRORS == 1 or 
                                        SHOW_GATE_UNRESOLVED_ERRORS == 1 or 
                                        SHOW_GATE_ATTEMPTED_REPAIRS == 1 or 
                                        SHOW_GATE_UNRESOLVED_ERROR_IDS == 1):
                rich_print("\n" + "=" * 80)
                rich_print(f"AGENTIC GATE PROMPT STEP {react_idx + 1}")
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_HISTORY == 1:
                rich_print("CURRENT ROUND HISTORY:")
                trunc_lim_hist = TRUNCATION_LIMIT_GATE_HISTORY
                truncated_history = gate_history[:trunc_lim_hist] + ("..." if len(gate_history) > trunc_lim_hist else "")
                rich_print(truncated_history)
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_CACHED_TOOL_OUTPUTS == 1:
                rich_print("CACHED TOOL OUTPUTS:")
                rich_print(cache)
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_FIXED_ERRORS == 1:
                rich_print("So far errors fixed:")
                rich_print(_serialize_errors_for_prompt(fixed_errors))
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_UNRESOLVED_ERRORS == 1:
                rich_print("Errors still unresolved:")
                rich_print(_serialize_errors_for_prompt(unresolved_errors))
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_ATTEMPTED_REPAIRS == 1:
                rich_print("ALREADY ATTEMPTED REPAIR STEPS THIS GATE RUN:")
                rich_print(_format_attempt_log(attempt_log))
                rich_print("=" * 80)

            if DEBUG_MESSAGES == 1 and SHOW_GATE_UNRESOLVED_ERROR_IDS == 1:
                rich_print("VALID UNRESOLVED ERROR IDS:")
                rich_print(sorted(list(valid_error_ids)))
                rich_print("=" * 80)

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

            if decision["missing_args"]:
                if done or step is None:
                    missing_args = _normalize_missing_args(decision["missing_args"])
                else:
                    missing_args = _normalize_missing_args(missing_args + decision["missing_args"])


            if done and step is None:
                gate_notes.append(reason or "Repair model stopped.")
                break

            if target_error_id is None:
                gate_notes.append(
                    reason or "Repair model did not choose a valid unresolved error."
                )
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
                break


            if target_error is None:
                gate_notes.append(
                    f"Repair model selected invalid target error id `{target_error_id}`."
                )
                break

            if step is None:
                gate_notes.append(
                    reason or f"No safe repair step returned for target error `{target_error_id}`."
                )
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
                if "password" in (step.get("args") or {}) and "password" not in missing_args:                                                                                
                    missing_args = _normalize_missing_args(missing_args + ["password"])  
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
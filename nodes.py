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
    detect_recent_tool_errors,
    format_msg, 
    _parse_plan, 
    _compact_json, 
    _safe_json_loads, 
    _extract_tool_error           
)
from tools.tool_setup import build_tool_context

import dotenv
dotenv.load_dotenv()
DEBUG_MESSAGES = int(dotenv.get_key(dotenv.find_dotenv(), "DEBUG_MESSAGES") or "0")
DO_SELECTION = (dotenv.get_key(dotenv.find_dotenv(), "DO_SELECTION") or "0").strip().lower() in ("1", "true", "yes", "on")
SHOW_PLANNER_INPUT = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_PLANNER_INPUT") or "0")
SHOW_RESPONDER_INPUT = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_RESPONDER_INPUT") or "0")
SHOW_GATE_INPUT = int(dotenv.get_key(dotenv.find_dotenv(), "SHOW_GATE_INPUT") or "0")

def make_planner_node(tools_by_name: dict):
    model = make_model(temperature=0.0)

    def planner_node(state: dict) -> Dict:
        chat_history = format_history_for_planner(state.get("messages", []), drop_last_user=True)
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
        - You must follow those dependency chains.
        - If a later tool depends on an earlier tool's result, you must still include the later tool in the plan when it is part of the required chain.
        - When an argument is not yet known because it will come from a previous tool result, use a symbolic placeholder instead of omitting the dependent tool.

        PLACEHOLDER POLICY:
        - You may use symbolic placeholders for arguments that will be derived from earlier tool outputs.
        - Do NOT invent fake final values.
        - Instead use placeholders such as:
        - "<BEST_MATCH_ID_FROM_DISCOVER_CHARITIES>"
        - "<WEBSITE_URL_FROM_CHARITY_DETAILS>"
        - Prefer a complete dependency-aware plan over a single first-step plan when tool descriptions define a normal chain.

        PLANNING RULES:
        1. Identify all user intents.
        2. Reuse prior successful tool outputs where sufficient.
        3. Read and obey dependency instructions in tool descriptions.
        4. If a vague charity name is mentioned, follow the default charity chain:
        discover_charities -> charity_details -> fetch_url
        5. Do not stop at discovery for a "tell me about X" query if deeper tools are part of the required chain.
        6. If downstream args are not yet known, include the downstream tool with a symbolic placeholder.
        7. Only return steps: [] if chat history already fully satisfies the request.

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

        if DEBUG_MESSAGES == 1 and SHOW_PLANNER_INPUT == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER INPUT (DO_SELECTION={DO_SELECTION})")
            rich_print("="*80)
            rich_print(prompt)
            rich_print("="*80)

        response = model.invoke([HumanMessage(content=prompt)])

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER RAW OUTPUT")
            rich_print("="*80)
            rich_print(response.content)
            rich_print("="*80)

        plan = _parse_plan(response.content)

        if DEBUG_MESSAGES == 1:
            steps_list = [s.get("tool", "") for s in plan.get("steps", [])]
            rich_print(f"[PLANNER] Scheduled tools: {steps_list}")

        return {"plan": plan}

    return planner_node


def make_validator_node(tools_by_name: dict):
    def validator_node(state: dict) -> Dict:
        plan = state.get("plan", {})
        steps = plan.get("steps", [])
        missing_args = plan.get("missing_args", [])
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
                "messages": [AIMessage(content=f"System Note: STOP EXECUTION. The planner needs input. Ask the user strictly for: {', '.join(missing_args)}")]
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

    def responder(state: dict) -> Dict:
        messages = list(state.get("messages", []) or [])
        latest_user_idx = None
        latest_user_content = ""
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], HumanMessage):
                latest_user_idx = i
                latest_user_content = (messages[i].content or "").strip()
                break

        if latest_user_idx is not None and latest_user_content.lower().startswith("password:"):
            fresh_tool_success = False
            for m in messages[latest_user_idx + 1:]:
                if not isinstance(m, ToolMessage):
                    continue
                payload = _safe_json_loads((m.content or "").strip())
                if payload is not None and _extract_tool_error(payload) is None:
                    fresh_tool_success = True
                    break

            if not fresh_tool_success:
                return {
                    "messages": [AIMessage(content="Please enter password")],
                    "final_answer": "Please enter password",
                }

        system_prompt = """
You are a donor-assisting AI agent on a donation website that produces FINAL, USER-FACING answers.
Assume the user may be a confused or first-time donor who needs clear guidance.

OUTPUT RULES (STRICT):
- If in Conversation History, there is mention of 'Invalid password' or a similar auth failure (AFTER only last USER message), your FINAL answer MUST be exactly: "Please enter password" (without quotes).
- After getting password, use the conversation history to determine course of response.
- Always show the money in USD.
- Authentication for the latest user request must be grounded only in tool outputs that occur AFTER the latest USER password submission.
- A USER message containing a password is NOT itself evidence of successful authentication.
- If the latest password submission is not followed by a successful relevant tool result for the latest requested action, your FINAL answer MUST be exactly: "Please enter password" (without quotes).
- Do NOT reuse older successful auth-sensitive tool outputs from earlier turns as proof that the latest password worked.
- Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
- Do NOT describe tool usage steps.
- Do NOT output any code blocks or code snippets.
- The Conversation History may contain cached tool traces labeled as `CACHED_TOOL_CALL[...]` and cached successful results labeled as `CACHED_SUCCESS[...]`.
- Treat `CACHED_SUCCESS[...]` as reusable factual evidence from prior successful tool execution.
- ONLY use information explicitly present in the Conversation History (especially `CACHED_SUCCESS[...]` entries and other tool outputs), do NOT invent or assume any facts not in the history.
- If the needed value is not present, say what is missing and ask for the minimum needed input.

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

        transcript = format_history_for_responder(messages)
        final_prompt = [HumanMessage(content=f"{system_prompt}\n\nConversation History:\n{transcript}")]

        if DEBUG_MESSAGES == 1 and SHOW_RESPONDER_INPUT == 1:
            rich_print("\n" + "="*80)
            rich_print("RESPONDER INVOKE MESSAGES")
            rich_print("="*80)
            for i, m in enumerate(final_prompt):
                rich_print(format_msg(m))   # ← now exact match to original
            rich_print("="*80)

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
        raw_original_errors = detect_recent_tool_errors(base_messages)

        if not raw_original_errors:
            return {
                "plan": {"steps": [], "missing_args": []},
                "messages": [],
                "last_tool_error": None,
            }

        # Freeze original round history for LLM-visible history.
        llm_visible_messages: List[BaseMessage] = list(base_messages)

        emitted_messages: List[BaseMessage] = []
        seen_step_signatures: set[str] = set()
        missing_args: List[str] = []
        gate_notes: List[str] = []
        attempt_log: List[Dict[str, Any]] = []

        original_errors: List[Dict[str, Any]] = []
        for idx, err in enumerate(raw_original_errors, start=1):
            enriched = dict(err)
            enriched["error_id"] = f"E{idx}"
            original_errors.append(enriched)

        fixed_error_ids: set[str] = set()

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
""".strip()

            if DEBUG_MESSAGES == 1 and SHOW_GATE_INPUT == 1:
                rich_print("\n" + "=" * 80)
                rich_print(f"AGENTIC GATE PROMPT STEP {react_idx + 1}")
                rich_print("=" * 80)
                rich_print(react_prompt)
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

            for item in decision["missing_args"]:
                if item not in missing_args:
                    missing_args.append(item)

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
                "ok": bool(payload.get("ok", False)),
                "output": payload.get("result") if payload.get("ok") else payload.get("error"),
            })

            if payload.get("ok") is False:
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

        note = (
            "System Note: Agentic gate finished with unresolved tool error(s)."
            if unresolved_errors
            else "System Note: Agentic gate completed repair pass."
        )

        if gate_notes:
            note += " " + " | ".join(gate_notes[:4])

        emitted_messages.append(AIMessage(content=note))

        return {
            "plan": {"steps": [], "missing_args": missing_args},
            "messages": emitted_messages,
            "last_tool_error": unresolved_errors[0] if unresolved_errors else None,
        }

    return gate_node

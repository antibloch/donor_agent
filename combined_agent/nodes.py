import json
import os
from uuid import uuid4
from typing import Dict, List, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from rich import print as rich_print
from dotenv import load_dotenv

from llm import make_model
from tools.json_utils import _parse_plan, _compact_json          
from history_formatters import (
    format_history_for_planner,
    format_history_for_gate,
    build_cached_tool_outputs,
    format_history_for_responder,
    detect_latest_tool_error,
    format_msg,          
)
from tools.tool_setup import build_tool_context


load_dotenv()
DEBUG_MESSAGES = int(os.getenv("DEBUG_MESSAGES"))


def make_planner_node(tools_by_name: dict):
    model = make_model(temperature=0.0)

    def planner_node(state: dict) -> Dict:
        chat_history = format_history_for_planner(state.get("messages", []), drop_last_user=True)
        tool_context = build_tool_context(tools_by_name)

        prompt = f"""
You are a planning module for a donor-assisting AI on a donation website.
The user is typically a donor exploring where and how to donate.
Your job is to output a tool plan that satisfies both:
1) the user's explicit request, and
2) valuable donor-focused analytical depth by default (insights + recommendations), unless the user explicitly asks for "just list", "brief only", or "no analysis".

Available tools:
{tool_context}

PLANNING GOAL:
- Cover every part of the user's request.
- By default, produce high-value donor guidance in addition to base facts.
- Prefer concise but complete pipelines over under-informative single-tool plans.

HARD CONSTRAINTS (must follow):
A) COVERAGE CHECKLIST (do NOT output this checklist; use it silently):
1. Identify ALL distinct user requirements.
2. For EACH requirement, ensure at least one planned step will produce the needed information.
3. Also add at least one analysis requirement and one recommendation requirement unless user explicitly asks for no analysis.
4. If ANY requirement is not covered, add the minimal additional step(s).

B) TOOL SELECTION RULE:
- Choose tools based on their descriptions and argument schemas.
- Prefer reusable data-collection tools first, then synthesis tools.
- Keep tool names and args exact.

C) MANDATORY PYTHON TRIGGER:
- If the user asks for ANY numeric aggregation (median, mean, average, avg, std, min, max, sum, total)
  OR explicitly says "use python"
  OR asks about entities/items in plural/group form and has not explicitly disabled analysis
  OR asks for insights/recommendations/comparison/ranking/trends
  and has not explicitly disabled analysis
  → MUST include a Python_REPL step.
- Python_REPL must NEVER have empty args.

D) Python_REPL argument format:
- {{ "input": "<python code>" }}
- For analytics-by-default cases, Python code must:
  - parse outputs from prior get_charity_stats calls into comparable structures;
  - compute at least 3 insights (ranking/segmentation/distribution/outlier/opportunity);
  - produce donor-facing recommendation candidates tied to evidence;
  - final line must be a single print(...) that prints JSON text.

E) TOOL REUSE RULE:
- If the exact needed data already exists in chat history ToolMessage outputs, do NOT call tools again.

F) ANALYTICS-BY-DEFAULT PIPELINE (TOOL-AGNOSTIC):
- For any informative query (unless explicitly list-only/no-analysis), do not stop at raw retrieval.
- Build a 2-layer plan whenever feasible:
  1) Data acquisition layer: gather relevant raw data from one or more data tools.
  2) Synthesis layer: run one computation/synthesis step (prefer Python_REPL if available) to produce donor-oriented insights and practical donation recommendations.
- If synthesis tooling is unavailable, maximize comparative insight using available data tools and state limits in missing_args.

PAGINATION RULE (CRITICAL – MUST FOLLOW):
- The following tools support pagination: get_charity_blogs and get_charity_products
- ALWAYS include BOTH "page" and "limit" explicitly in the "args" object for these tools.
- Use page=1 and limit=50 (or limit=100 if you want maximum results) as safe defaults.
- NEVER omit "page" or "limit" — they must appear in the JSON even when using defaults.

AUTH TOKEN USAGE RULE:
- Always use any kind of auth token as "secret token" for get_charity_blogs, get_charity_products and get_charity_ranking.

OUTPUT FORMAT (STRICT JSON ONLY):
{{
"steps": [
    {{"tool": "tool_name", "args": {{"arg_name": "value"}}}}
],
"missing_args": []
}}

Chat History (may contain prior TOOL_CALL + TOOL outputs to reuse):
{chat_history}

User Request (current turn):
{state.get("messages", [])[-1].content if state.get("messages") else ""}
"""

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER INPUT")
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

        # Enforce analytical-default behavior in a tool/domain agnostic way.
        user_text = ""
        for m in reversed(state.get("messages", []) or []):
            if isinstance(m, HumanMessage):
                user_text = (m.content or "").lower()
                break

        informative_query = any(
            phrase in user_text
            for phrase in [
                "what",
                "which",
                "list",
                "show",
                "find",
                "available",
                "compare",
                "insight",
                "recommend",
                "analy",
                "trend",
                "best",
                "top",
            ]
        )
        analysis_disabled = any(
            phrase in user_text
            for phrase in [
                "no analysis",
                "just list",
                "only list",
                "brief only",
                "only names",
            ]
        )

        step_tools = [s.get("tool") for s in valid_steps]
        has_python = any(t in ("Python_REPL", "python_repl", "PythonREPLTool") for t in step_tools)
        has_non_python_tool = any(t not in ("Python_REPL", "python_repl", "PythonREPLTool") for t in step_tools)

        if informative_query and not analysis_disabled:
            if not has_non_python_tool:
                return {
                    "plan": {"steps": [], "missing_args": []},
                    "messages": [AIMessage(content="System Note: STOP EXECUTION. Analytical response requires at least one data-acquisition tool step before final answer.")],
                }
            if not has_python:
                return {
                    "plan": {"steps": [], "missing_args": []},
                    "messages": [AIMessage(content="System Note: STOP EXECUTION. Analytical response requires a synthesis/computation step (Python_REPL) for insights and recommendations.")],
                }

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
        tool_name = getattr(tool, "name", "")

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
        
        if tool_name in ("Python_REPL", "python_repl", "PythonREPLTool"):
            return await tool.ainvoke(str(raw_args.get("input", "") or ""))

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
        system_prompt = """
You are a donor-assisting AI agent on a donation website that produces FINAL, USER-FACING answers.
Assume the user may be a confused or first-time donor who needs clear guidance.

OUTPUT RULES (STRICT):
- Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
- Do NOT describe tool usage steps.
- Do NOT output any code blocks or code snippets.
- ONLY use information explicitly present in the Conversation History (especially TOOL outputs).
- If the needed value is not present, say what is missing and ask for the minimum needed input.
- By default, be analytical and donor-focused. If data exists, include deep insights and practical donation recommendations.

RESPONSE STRUCTURE:
1) Direct Answer
2) Donor Insights
3) Donation Recommendations

If user explicitly asked for brief/list-only/no-analysis, keep response concise and skip deep analysis.

RECOMMENDATION STYLE:
- Prioritize actionable guidance for donation decisions (where to donate, why, and what to watch for).
- Tie each recommendation to evidence from available data.
- If confidence is limited by missing data, state this clearly and suggest the next best donor action.

Now write the final answer based strictly on the Conversation History below.
"""

        transcript = format_history_for_responder(state.get("messages", []))
        final_prompt = [HumanMessage(content=f"{system_prompt}\n\nConversation History:\n{transcript}")]

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("RESPONDER INVOKE MESSAGES")
            rich_print("="*80)
            for i, m in enumerate(final_prompt):
                rich_print(f"\n--- final_prompt[{i}] ---")
                rich_print(format_msg(m))   # ← now exact match to original
            rich_print("="*80)

        summary = model.invoke(final_prompt)
        final_text = (summary.content or "").strip()

        return {"messages": [summary], "final_answer": final_text}

    return responder


def make_gate_node(tools_by_name: dict, max_repairs: int = 1):
    model = make_model(temperature=0.0)

    def gate_node(state: dict) -> Dict:
        attempts = int(state.get("repair_attempts") or 0)
        if attempts >= max_repairs:
            return {
                "messages": [AIMessage(content="System Note: Repair limit reached. Proceeding to final response.")],
                "plan": {"steps": [], "missing_args": []},
            }

        messages = list(state.get("messages", []) or [])
        last_error = detect_latest_tool_error(messages)
        if not last_error:
            return {"plan": {"steps": [], "missing_args": []}}

        history = format_history_for_gate(messages)
        cache = build_cached_tool_outputs(messages)

        tool_context = build_tool_context(tools_by_name)
        valid_tool_names = list(tools_by_name.keys())

        prompt = f"""
You are an EXPERT TOOL-REPAIR AGENT. Your sole job is to fix the most recent tool failure with MAXIMUM precision and correctness.

Available tools:
{tool_context}

Valid tool names (must match EXACTLY):
{valid_tool_names}

Most recent tool error:
- tool: {last_error["tool"]}
- error: {last_error["error"]}

Cached recent tool outputs (USE THIS DATA EXACTLY — do NOT invent values):
{cache}

CRITICAL INSTRUCTIONS — FOLLOW STRICTLY:

1. Output ONLY valid JSON in this exact format, nothing else:
{{
"steps": [
    {{"tool": "tool_name", "args": {{"arg_name": "value"}}}}
],
"missing_args": []
}}

2. For Python_REPL repairs (the most common case):
- ALWAYS start with proper imports: `import statistics`
- Extract the REAL data from the "Cached recent tool outputs" section above and hard-code it into variables.
- Use the CORRECT statistical function:
        • median → statistics.median(your_list)
        • mean   → statistics.mean(your_list)
        • sum, min, max, etc. → built-in functions
- The code must END with ONE clean `print(…)` statement that outputs ONLY the final numeric result (no lists, no extra text).
- NEVER print the sorted list. NEVER use `sorted()` alone for median.
- Avoid leading indentation on lines unless inside a block (IndentationError risk).

3. Concrete good example for a median repair:
{{
"steps": [
    {{
    "tool": "Python_REPL",
    "args": {{
        "input": "import statistics\\ndonor_counts = [4, 2, 7, 5, 3]\\nprint(statistics.median(donor_counts))"
    }}
    }}
],
"missing_args": []
}}

4. Think step-by-step about the error and the cached data, then output ONLY the JSON fix.

Conversation History (current round only):
{history}
"""

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("GATE INPUT")
            rich_print("="*80)
            rich_print(prompt)
            rich_print("="*80)

        resp = model.invoke([HumanMessage(content=prompt)])

        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("GATE RAW OUTPUT")
            rich_print("="*80)
            rich_print(resp.content)
            rich_print("="*80)

        repair_plan = _parse_plan(resp.content)

        return {
            "plan": repair_plan,
            "repair_attempts": attempts + 1,
            "last_tool_error": last_error,
            "messages": [
                AIMessage(content=f"System Note: Detected tool error in {last_error['tool']}. Attempting automatic repair.")
            ],
        }

    return gate_node

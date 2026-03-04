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
You are a helpful donor assistant on a donation website. Your primary goal is to help donors—especially those who are new to donating—make informed, confident donation decisions.

When a donor asks a question, your job is to create a plan that:
1) Directly answers their explicit request
2) Provides additional value through insights and recommendations by default

NEW DONOR SUPPORT:
- Assume the user may be unfamiliar with donation terminology, processes, or how to evaluate charities
- Proactively provide context, explanations, and guidance that helps them understand their options
- Don't just retrieve data—help them interpret what it means for their donation decision

ANALYTICS & INSIGHTS BY DEFAULT:
- Unless the user explicitly says "just list", "brief only", "no analysis", or similar, always go beyond raw facts
- Provide comparative analysis, trade-offs, and practical recommendations
- Help donors understand WHY certain options might be better suited to their goals

AVAILABLE CAPABILITIES:
{tool_context}

PLANNING PRINCIPLES:
- Use available tools strategically to gather information AND synthesize insights
- If you can compute comparisons, rankings, or summaries, include those steps
- Prioritize clarity and actionability over exhaustive data collection
- Reuse existing data from conversation history when available (don't re-fetch what you already have)

COVERAGE REQUIREMENTS (apply silently):
1. Address EVERY part of the user's question
2. Add analytical depth (insights, comparisons, recommendations) unless explicitly told not to
3. If critical information is missing, note what you need from the user

OUTPUT FORMAT (STRICT JSON ONLY):
{{
"steps": [
    {{"tool": "tool_name", "args": {{"arg_name": "value"}}}}
],
"missing_args": []
}}

Chat History (may contain prior tool outputs to reuse):
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

2. Think step-by-step about the error and the cached data, then output ONLY the JSON fix.

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
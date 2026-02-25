import os
import json
import asyncio
import requests
from typing import Annotated, Sequence, TypedDict, Any, List, Dict

from rich.console import Console
from rich import print as rich_print

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, END

from langchain_experimental.tools import PythonREPLTool
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

import re
from uuid import uuid4

DEBUG_MESSAGES = 1

# ========================== TRANSCRIPT HELPERS ==========================
def format_msg(m: BaseMessage) -> str:
    role = m.__class__.__name__
    content = (getattr(m, "content", "") or "").strip()

    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        content += "\n\n[tool_calls]\n" + json.dumps(getattr(m, "tool_calls"), indent=2, ensure_ascii=False)

    if getattr(m, "name", None):
        content = f"[tool={m.name}]\n{content}"
    return f"{role}:\n{content}\n"

# ========================== STATE ==========================
class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Dict[str, Any]
    repair_attempts: int
    last_tool_error: Dict[str, Any]

# ========================== TOOLS ==========================
def build_node_stats_tool():
    BASE_URL = "http://localhost:3000"
    CANONICAL_TOOLS = [
        "charity_donor_count", "charity_impactlife", "charity_donor_amount",
        "charity_total_donation", "charity_items_category",
        "charity_product_price_description", "charity_blogs",
        "charity_address", "charity_country_availability", "charity_contact_info",
    ]

    def call_node_stats(tool_name: str) -> str:
        tool_name = (tool_name or "").strip()
        if not tool_name:
            return json.dumps({"ok": False, "error": "Tool name is required.", "valid_tools": CANONICAL_TOOLS})
        if tool_name not in CANONICAL_TOOLS:
            return json.dumps({"ok": False, "error": "Invalid tool name", "provided": tool_name, "valid_tools": CANONICAL_TOOLS})
        try:
            r = requests.get(f"{BASE_URL}/api/stats", params={"q": tool_name}, timeout=10)
            r.raise_for_status()
            return json.dumps(r.json())
        except requests.RequestException as e:
            return json.dumps({"ok": False, "error": str(e), "tool": tool_name})

    class CharityStatsInput(BaseModel):
        tool_name: str = Field(..., description="Exact one tool name from the CANONICAL_TOOLS list above")

    return StructuredTool.from_function(
        func=call_node_stats,
        name="get_charity_stats",
        description=(
            "Fetch internal charity data from Node-js server.\n"
            "IMPORTANT: The ONLY callable tool is 'get_charity_stats'.\n"
            "The following are NOT tools; they are allowed VALUES for the argument 'tool_name':\n"
            + "\n".join([f"- {t}" for t in CANONICAL_TOOLS])
        ),
        args_schema=CharityStatsInput,
    )

async def setup_tools():
    local_tools = [build_node_stats_tool(), PythonREPLTool()]
    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    mcp_tools = await client.get_tools()
    return [*local_tools, *mcp_tools]

def build_tool_context(tools_by_name: dict):
    blocks = []
    for tool in tools_by_name.values():
        name = tool.name
        description = (getattr(tool, "description", "") or "No description.").strip()
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            arg_lines = []
            for k, v in fields.items():
                req = getattr(v, "is_required", lambda: False)()
                arg_lines.append(f"- {k} ({'required' if req else 'optional'})")
            args_text = "\n".join(arg_lines) if arg_lines else "No parameters"
        else:
            args_text = "- input (required string). For Python_REPL, this must be python code."
        blocks.append(f"""
{name}
Description:
{description}

Arguments:
{args_text}
""")
    return "\n\n".join(blocks)

def make_model(temperature: float = 0.0):
    return ChatOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_API_KEY"),
        model="nvidia/nemotron-3-nano-30b-a3b",
        temperature=temperature,
        max_tokens=8192,
    )

# ========================== JSON HELPERS ==========================
def _extract_first_json_object(text: str) -> str:
    if not text:
        raise ValueError("Empty LLM output")
    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*({.*?})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No '{' found in LLM output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : i + 1].strip()
    raise ValueError("Unbalanced JSON braces in LLM output")

def _parse_plan(raw: str) -> Dict:
    if not raw:
        return {"steps": [], "missing_args": []}
    try:
        json_str = _extract_first_json_object(raw)
        return json.loads(json_str)
    except:
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return {"steps": [], "missing_args": []}

def _safe_json_loads(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None

def _compact_json(obj: Any, max_chars: int = 900) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        return s[:max_chars] + " ...[truncated]"
    return s

def _summarize_tool_output(tool_name: str, tool_content: str) -> str:
    payload = _safe_json_loads(tool_content) if isinstance(tool_content, str) else None
    if not payload:
        return f"TOOL[{tool_name}] -> {tool_content}"

    if isinstance(payload, dict) and payload.get("ok") is False:
        err = payload.get("error") or payload.get("result") or payload
        return f"TOOL[{tool_name}] ERROR -> {_compact_json(err, max_chars=700)}"

    result = payload.get("result", payload)

    if tool_name == "get_charity_stats" and isinstance(result, dict):
        data = result.get("data")
        tool = result.get("tool") or result.get("query")
        if tool == "charity_donor_count" and isinstance(data, list):
            pairs = []
            for row in data:
                name = row.get("charityName")
                cnt = row.get("donorCount")
                if name is not None and cnt is not None:
                    pairs.append(f"{name}: {cnt}")
            if pairs:
                return "TOOL[get_charity_stats:charity_donor_count] -> " + "; ".join(pairs)

    if tool_name in ("Python_REPL", "python_repl", "PythonREPLTool"):
        return f"TOOL[Python_REPL] -> {_compact_json(result, max_chars=300)}"

    return f"TOOL[{tool_name}] -> {_compact_json(result, max_chars=700)}"

# ========================== CURRENT-ROUND + REPLACEMENT HELPERS ==========================
def get_current_round_messages(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    msgs = list(messages or [])
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            return msgs[i:]
    return msgs

def get_latest_tool_per_name(messages: Sequence[BaseMessage]) -> Dict[str, ToolMessage]:
    """
    Prefer the latest successful (ok=True) ToolMessage per tool name.
    If no successful exists, fall back to the latest ToolMessage.
    """
    latest_any: Dict[str, ToolMessage] = {}
    latest_ok: Dict[str, ToolMessage] = {}
    for m in messages or []:
        if isinstance(m, ToolMessage):
            latest_any[m.name] = m
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is True:
                latest_ok[m.name] = m
    out = dict(latest_any)
    out.update(latest_ok)
    return out

# NEW: Map tool_call_id -> ToolMessage (latest ok preferred, else latest any)
def get_best_tool_message_by_call_id(messages: Sequence[BaseMessage]) -> Dict[str, ToolMessage]:
    latest_any: Dict[str, ToolMessage] = {}
    latest_ok: Dict[str, ToolMessage] = {}
    for m in messages or []:
        if isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if not tcid:
                continue
            latest_any[tcid] = m
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is True:
                latest_ok[tcid] = m
    out = dict(latest_any)
    out.update(latest_ok)
    return out

def _compact_err(payload: dict) -> str:
    try:
        s = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        s = str(payload)
    return s[:800] + (" ...[truncated]" if len(s) > 800 else "")

def detect_latest_tool_error(messages: Sequence[BaseMessage], max_k: int = 8) -> Dict[str, Any] | None:
    """
    Only attends to the last K tool outputs inside the CURRENT conversation round.
    Detects failure when payload ok=False OR error markers appear in result/error strings.
    """
    current_round = get_current_round_messages(messages)
    tool_msgs = [m for m in current_round if isinstance(m, ToolMessage)][-max_k:]

    error_markers = [
        "Traceback",
        "IndentationError",
        "SyntaxError",
        "NameError",
        "KeyError",
        "TypeError",
        "ValueError",
        "Exception",
        "Error:",
        "ERROR",
        "invalid",
        "missing",
        "failed",
    ]

    for m in reversed(tool_msgs):
        raw = (m.content or "").strip()
        payload = _safe_json_loads(raw)

        if isinstance(payload, dict):
            if payload.get("ok") is False:
                return {"tool": m.name, "error": _compact_err(payload), "tool_message": raw}
            
            # Sometimes tools return errors in `result` even when ok=True (we try to prevent this in executor),
            # but keep this extra guard:

            result = payload.get("result", None)
            if isinstance(result, str) and any(k in result for k in error_markers):
                return {"tool": m.name, "error": result[:800], "tool_message": raw}

            err = payload.get("error", None)
            if isinstance(err, str) and any(k in err for k in error_markers):
                return {"tool": m.name, "error": err[:800], "tool_message": raw}

        if any(k in raw for k in error_markers):
            return {"tool": m.name, "error": raw[:800], "tool_message": raw}

    return None

# ========================== UPDATED FORMATTERS ==========================
def _format_tool_calls_block(tool_calls: list) -> str:
    out = []
    for tc in tool_calls or []:
        tid = tc.get("id") or tc.get("tool_call_id") or ""
        name = tc.get("name") or ""
        args = tc.get("args") or {}
        out.append(f"TOOL_CALL[{name} id={tid}] args={_compact_json(args, max_chars=600)}")
    return "\n".join(out)

def format_history_for_gate(messages: Sequence[BaseMessage]) -> str:
    """Gate sees ONLY current round history (and we hide synthetic tool-call AI messages)."""
    current_round = get_current_round_messages(messages)
    lines = []
    for m in current_round:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.content}")
        elif isinstance(m, AIMessage):
            if getattr(m, "tool_calls", None) and not (m.content or "").strip():
                continue
            if (m.content or "").strip().startswith("System Note:"):
                continue
            lines.append(f"ASSISTANT: {m.content}")
        elif isinstance(m, ToolMessage):
            content = (m.content or "").strip()
            if len(content) > 1200:
                content = content[:1200] + " ...[truncated]"
            lines.append(f"TOOL[{m.name}]: {content}")
    return "\n".join(lines) if lines else "(empty)"

def build_cached_tool_outputs(messages: Sequence[BaseMessage], max_chars: int = 1200) -> str:
    current_round = get_current_round_messages(messages)
    last_by_tool: Dict[str, str] = {}
    for m in current_round:
        if isinstance(m, ToolMessage):
            last_by_tool[m.name] = m.content or ""
    if not last_by_tool:
        return "(none)"
    blocks = []
    for tool_name, content in last_by_tool.items():
        c = content.strip()
        if len(c) > max_chars:
            c = c[:max_chars] + " ...[truncated]"
        blocks.append(f"- {tool_name}: {c}")
    return "\n".join(blocks)

# REVISED: Planner history now includes tool call bodies + best tool results per call_id (like responder)
def format_history_for_planner(messages: Sequence[BaseMessage], *, drop_last_user: bool = True) -> str:
    """
    Planner sees:
    - USER + ASSISTANT content (excluding System Note)
    - TOOL_CALL bodies (AIMessage.tool_calls)
    - TOOL outputs, but:
        * tool outputs are filtered to avoid showing stale failures
        * per tool_call_id, we prefer latest ok=True ToolMessage (else latest any)
        * per tool name, we also prefer ok=True (get_latest_tool_per_name)
    """
    msgs = list(messages) if messages else []
    if drop_last_user:
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], HumanMessage):
                msgs = msgs[:i]
                break

    latest_tools_by_name = get_latest_tool_per_name(msgs)
    best_tool_by_call_id = get_best_tool_message_by_call_id(msgs)

    lines = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.content}")

        elif isinstance(m, AIMessage):
            if (m.content or "").strip().startswith("System Note:"):
                continue

            # Include tool call bodies
            if getattr(m, "tool_calls", None):
                lines.append(_format_tool_calls_block(m.tool_calls))

                # Right after tool call body, also include matching tool results (if already present)
                for tc in m.tool_calls or []:
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        # also respect per-tool-name "latest ok preferred" to avoid re-showing old failures
                        if tm is latest_tools_by_name.get(tm.name) or (tm.name not in latest_tools_by_name):
                            lines.append(_summarize_tool_output(tm.name, tm.content))

            # Include normal assistant text if any
            if (m.content or "").strip():
                lines.append(f"ASSISTANT: {m.content}")

        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            
            # <<< THIS IS THE FIX >>>
            # Skip every ToolMessage that was already summarized right after its tool_call block
            if tcid and tcid in best_tool_by_call_id:
                continue

            # Fallback for any legacy ToolMessage without call_id pairing
            if m is not latest_tools_by_name.get(m.name):
                continue

            lines.append(_summarize_tool_output(m.name, m.content))

        else:
            lines.append(f"{m.__class__.__name__}: {getattr(m, 'content', '')}")

    return "\n".join(lines) if lines else "(no prior history)"

def format_history_for_responder(messages: Sequence[BaseMessage]) -> str:
    latest_tools_by_name = get_latest_tool_per_name(messages)
    best_tool_by_call_id = get_best_tool_message_by_call_id(messages)

    lines = []
    seen_call_ids: set[str] = set()

    for m in messages or []:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.content}")

        elif isinstance(m, AIMessage):
            if (m.content or "").strip().startswith("System Note:"):
                continue

            if getattr(m, "tool_calls", None):
                lines.append(_format_tool_calls_block(m.tool_calls))

                for tc in m.tool_calls or []:
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if not tcid:
                        continue
                    tm = best_tool_by_call_id.get(tcid)
                    if not tm:
                        continue

                    # mark as emitted so we don't emit again in ToolMessage pass
                    seen_call_ids.add(tcid)

                    # optionally still apply "latest ok per tool name" filter:
                    # keep only if it's the chosen best for that tool name
                    if tm is not latest_tools_by_name.get(tm.name):
                        continue

                    lines.append(_summarize_tool_output(tm.name, tm.content))

            if (m.content or "").strip():
                lines.append(f"ASSISTANT: {m.content}")

        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)

            # If already emitted via pairing, skip
            if tcid and tcid in seen_call_ids:
                continue

            # Prior behavior: keep only latest ok=True per tool name
            if m is not latest_tools_by_name.get(m.name):
                continue

            lines.append(_summarize_tool_output(m.name, m.content))

        else:
            lines.append(f"{m.__class__.__name__}: {getattr(m, 'content', '')}")

    return "\n".join(lines) if lines else "(empty)"

# ========================== PLANNER NODE ==========================
def make_planner_node(tools_by_name: dict):
    model = make_model(temperature=0.0)

    def planner_node(state: AgentState) -> Dict:
        chat_history = format_history_for_planner(state.get("messages", []), drop_last_user=True)
        tool_context = build_tool_context(tools_by_name)

        prompt = f"""
You are a planning module for a charity & donation assistant.
Your job is to output a MINIMAL tool plan that FULLY satisfies the user's request.

Available tools:
{tool_context}

PLANNING GOAL:
- Cover every part of the user’s request using the fewest tool calls.
- Prefer reusing one tool call to satisfy multiple sub-requests when possible.

HARD CONSTRAINTS (must follow):
A) COVERAGE CHECKLIST (do NOT output this checklist; use it silently):
1. Identify ALL distinct user requirements.
2. For EACH requirement, ensure at least one planned step will produce the needed information.
3. If ANY requirement is not covered, add the minimal additional step(s).

B) SPECIAL RULE FOR get_charity_stats:
- The ONLY callable tool for charity stats is: get_charity_stats
- You MUST choose a concrete tool_name value yourself from its allowed list.
- Use ONE get_charity_stats call to satisfy multiple needs when possible.

C) MANDATORY PYTHON TRIGGER:
- If the user asks for ANY numeric aggregation (median, mean, average, avg, std, min, max, sum, total)
  OR explicitly says "use python" → MUST include a Python_REPL step.
- Python_REPL must NEVER have empty args.

D) Python_REPL argument format:
- {{ "input": "<python code that prints ONLY the final numeric result>" }}

E) TOOL REUSE RULE:
- If the exact needed data already exists in chat history ToolMessage outputs, do NOT call tools again.

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

# ========================== VALIDATOR NODE ==========================
def make_validator_node(tools_by_name: dict):
    def validator_node(state: AgentState) -> Dict:
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

# ========================== EXECUTOR NODE (UPDATED) ==========================
def make_executor_node(tools_by_name: dict):
    def _invoke_tool(tool, raw_args: dict):
        if getattr(tool, "args_schema", None) is not None:
            return tool.invoke(raw_args)
        if not raw_args:
            return tool.invoke("")
        if len(raw_args) == 1:
            return tool.invoke(next(iter(raw_args.values())))
        return tool.invoke(json.dumps(raw_args, ensure_ascii=False))

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
        )
        return any(m in s for m in error_markers)

    def _normalize_result(tool_name: str, result):
        """
        Normalize to {"ok": bool, "result": ...} and mark ok=False when a tool returns error text.
        This is critical for Python_REPLTool, which often returns errors as strings rather than raising.
        """
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
        return {
            "name": tool_name,
            "args": args or {},
            "id": tool_call_id,
            "type": "tool_call",
        }

    def executor_node(state: AgentState) -> Dict:
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
                result = _invoke_tool(tool, raw_args)
                payload = _normalize_result(tool_name, result)
            except Exception as e:
                payload = {"ok": False, "error": str(e), "tool": tool_name, "args": raw_args}

            messages.append(ToolMessage(
                content=json.dumps(payload, ensure_ascii=False, default=str),
                name=tool_name,
                tool_call_id=tool_call_id,
            ))

            if DEBUG_MESSAGES == 1:
                preview = payload.get("result") if payload.get("ok") else payload.get("error")
                preview_s = _compact_json(preview, max_chars=200)
                rich_print(f"[EXECUTOR] {tool_name} done ok={payload.get('ok')} args={raw_args} preview={preview_s}")

        return {"messages": messages}

    return executor_node

# ========================== RESPONDER NODE ==========================
def make_responder_node():
    model = make_model(temperature=0.0)

    def responder(state: AgentState) -> Dict:
        system_prompt = """
You are a Charity & Data Assistant that produces FINAL, USER-FACING answers.

OUTPUT RULES (STRICT):
- Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
- Do NOT describe tool usage steps.
- Do NOT output any code blocks or code snippets.
- ONLY use information explicitly present in the Conversation History (especially TOOL outputs).
- If the needed value is not present, say what is missing and ask for the minimum needed input.

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
                rich_print(format_msg(m))
            rich_print("="*80)

        summary = model.invoke(final_prompt)
        final_text = (summary.content or "").strip()

        return {"messages": [summary], "final_answer": final_text}

    return responder

# ========================== GATE NODE ==========================
def make_gate_node(tools_by_name: dict, max_repairs: int = 2):
    model = make_model(temperature=0.0)

    def gate_node(state: AgentState) -> Dict:
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

# ========================== ROUTING ==========================
def route_after_validator(state: AgentState) -> str:
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    return "executor" if len(steps) > 0 else "responder"

def route_after_gate(state: AgentState) -> str:
    plan = state.get("plan", {}) or {}
    steps = plan.get("steps", []) or []
    return "validator" if steps else "responder"

# ========================== BUILD GRAPH ==========================
async def build_graph():
    tools = await setup_tools()
    tools_by_name = {t.name: t for t in tools}

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", make_planner_node(tools_by_name))
    workflow.add_node("validator", make_validator_node(tools_by_name))
    workflow.add_node("executor", make_executor_node(tools_by_name))
    workflow.add_node("gate", make_gate_node(tools_by_name, max_repairs=1))
    workflow.add_node("responder", make_responder_node())

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "validator")

    workflow.add_conditional_edges(
        "validator",
        route_after_validator,
        {"executor": "executor", "responder": "responder"},
    )

    workflow.add_edge("executor", "gate")

    workflow.add_conditional_edges(
        "gate",
        route_after_gate,
        {"validator": "validator", "responder": "responder"},
    )

    workflow.add_edge("responder", END)
    return workflow.compile()

# ========================== MAIN ==========================
async def main():
    graph = await build_graph()

    chat_memory: List[BaseMessage] = []
    console = Console()

    rich_print("\n" + "="*60)
    rich_print("CHARITY AGENT – Gate limited to current round + last K tools")
    rich_print("Type 'exit', 'quit', or 'q' to stop.")
    rich_print("="*60 + "\n")

    while True:
        try:
            user_input = input("User: ")
        except (KeyboardInterrupt, EOFError):
            rich_print("\nGoodbye!")
            break

        if user_input.lower() in ["exit", "quit", "q"]:
            rich_print("\nGoodbye!")
            break

        user_msg = HumanMessage(content=user_input)
        chat_memory.append(user_msg)

        rich_print("\n(Agent is thinking...)\n")

        try:
            async for step in graph.astream({"messages": chat_memory, "repair_attempts": 0}, stream_mode="updates"):
                for node_name, node_output in step.items():
                    if not node_output:
                        continue
                    if "messages" in node_output:
                        new_messages = node_output["messages"]
                        for msg in new_messages:
                            chat_memory.append(msg)

                            if isinstance(msg, ToolMessage):
                                rich_print(f" ➤ [Tool Executed] {msg.name}")
                            elif isinstance(msg, AIMessage):
                                if getattr(msg, "tool_calls", None) and not (msg.content or "").strip():
                                    continue
                                if "System Note:" not in (msg.content or ""):
                                    rich_print(f"\nAgent: {msg.content}\n")
        except Exception as e:
            rich_print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
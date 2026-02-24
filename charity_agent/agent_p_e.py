import os
import json
import asyncio
import time
import requests
from typing import Annotated, Sequence, TypedDict, Any, List, Dict, Tuple

from rich.console import Console
from rich import print as rich_print

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.tools import Tool
from langgraph.graph.message import add_messages
from langgraph.graph import StateGraph, START, END

from langchain_experimental.tools import PythonREPLTool
from langchain_openai import ChatOpenAI
from langchain_mcp_adapters.client import MultiServerMCPClient

from pydantic import BaseModel, Field
from langchain_core.tools import StructuredTool

import re
from uuid import uuid4


DEBUG_MESSAGES = 1  # ← Your original debug flag



# ========================== YOUR TRANSCRIPT HELPERS ==========================
def format_msg(m: BaseMessage) -> str:
    role = m.__class__.__name__
    content = (getattr(m, "content", "") or "").strip()
    if getattr(m, "tool_calls", None):
        content += "\n\n[tool_calls]\n" + json.dumps(getattr(m, "tool_calls"), indent=2)
    if getattr(m, "name", None):
        content = f"[tool={m.name}]\n{content}"
    return f"{role}:\n{content}\n"

# ========================== STATE ==========================
class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Dict[str, Any]
    user_query: str
    past_turns: List[Tuple[str, str]]
    final_answer: str

# ========================== YOUR ORIGINAL TOOLS ==========================
# ========================== 1. UPDATED build_node_stats_tool (now StructuredTool) ==========================
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
        description = (
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

# ========================== TOOL CONTEXT (exact from second script) ==========================
def build_tool_context(tools_by_name: dict):
    blocks = []
    for tool in tools_by_name.values():
        name = tool.name
        description = (getattr(tool, "description", "") or "No description.").strip()

        args_schema = getattr(tool, "args_schema", None)

        # If structured tool: show real fields
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            arg_lines = []
            for k, v in fields.items():
                req = getattr(v, "is_required", lambda: False)()
                arg_lines.append(f"- {k} ({'required' if req else 'optional'})")
            args_text = "\n".join(arg_lines) if arg_lines else "No parameters"
        else:
            # Single-input tool: show "input" explicitly
            args_text = "- input (required string). For Python_REPL, this must be python code."

        blocks.append(f"""
{name}
Description:
{description}

Arguments:
{args_text}
""")
    return "\n\n".join(blocks)

# ========================== LLM ==========================
def make_model(temperature: float = 0.0):
    return ChatOpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=os.getenv("NVIDIA_API_KEY"),
        model="nvidia/nemotron-3-nano-30b-a3b",
        temperature=temperature,
        max_tokens=8192,
    )

# ========================== YOUR ROBUST JSON EXTRACTOR ==========================
def _extract_first_json_object(text: str) -> str:
    """Extract the first top-level JSON object from arbitrary text."""
    if not text:
        raise ValueError("Empty LLM output")

    cleaned = text.strip()

    # Try fenced block first
    m = re.search(r"```(?:json)?\s*({.*?})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()

    # Find first balanced { ... }
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


#============================HELPERS===============================
def _safe_json_loads(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None

def _compact_json(obj: Any, max_chars: int = 900) -> str:
    """Compact JSON-ish object to a bounded string."""
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        return s[:max_chars] + " ...[truncated]"
    return s

def _summarize_tool_output(tool_name: str, tool_content: str) -> str:
    """
    Turn your ToolMessage JSON envelope into a compact, human-usable line/block.
    Your executor wraps tool outputs like: {"ok": True, "result": ...}
    """
    payload = _safe_json_loads(tool_content) if isinstance(tool_content, str) else None
    if not payload:
        return f"TOOL[{tool_name}] -> {tool_content}"

    # unwrap envelope if present
    result = payload.get("result", payload)

    # Special-case: get_charity_stats / donor counts
    if tool_name == "get_charity_stats" and isinstance(result, dict):
        data = result.get("data")
        tool = result.get("tool") or result.get("query")
        if tool == "charity_donor_count" and isinstance(data, list):
            # Example: [{"charityName": "...", "donorCount": 4}, ...]
            pairs = []
            for row in data:
                name = row.get("charityName")
                cnt = row.get("donorCount")
                if name is not None and cnt is not None:
                    pairs.append(f"{name}: {cnt}")
            if pairs:
                return "TOOL[get_charity_stats:charity_donor_count] -> " + "; ".join(pairs)

    # Special-case: Python_REPL
    if tool_name.lower() in ("python_repl", "pythonrepl", "python_repltool") or tool_name == "Python_REPL":
        return f"TOOL[Python_REPL] -> {_compact_json(result, max_chars=300)}"

    return f"TOOL[{tool_name}] -> {_compact_json(result, max_chars=700)}"

def format_history_for_planner(messages: Sequence[BaseMessage], *, drop_last_user: bool = True) -> str:
    """
    Planner-friendly history:
    - Natural-ish but concise
    - Tool results summarized
    - Optionally drop last HumanMessage to avoid repeating current prompt
      (because you already append the current user message before invoking the graph)
    """
    msgs = list(messages) if messages else []
    if drop_last_user:
        # Remove the most recent HumanMessage (the current user turn)
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], HumanMessage):
                msgs = msgs[:i]  # drop that and anything after (usually nothing after)
                break

    lines = []
    for m in msgs:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.content}")
        elif isinstance(m, ToolMessage):
            lines.append(_summarize_tool_output(m.name, m.content))
        elif isinstance(m, AIMessage):
            # Hide internal "System Note:" chatter from planner signal
            if (m.content or "").strip().startswith("System Note:"):
                continue
            lines.append(f"ASSISTANT: {m.content}")
        else:
            lines.append(f"{m.__class__.__name__}: {getattr(m, 'content', '')}")

    return "\n".join(lines) if lines else "(no prior history)"

def format_history_for_responder(messages: Sequence[BaseMessage]) -> str:
    """
    Responder-friendly full transcript:
    - Ordered
    - Human-readable
    - Tool results summarized
    - Keeps the latest user prompt (since responder needs to answer it)
    """
    lines = []
    for m in messages or []:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {m.content}")
        elif isinstance(m, ToolMessage):
            lines.append(_summarize_tool_output(m.name, m.content))
        elif isinstance(m, AIMessage):
            # Skip internal system notes in final transcript
            if (m.content or "").strip().startswith("System Note:"):
                continue
            lines.append(f"ASSISTANT: {m.content}")
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
        1. Identify ALL distinct user requirements (e.g., "list charities", "median donor counts", "use python").
        2. For EACH requirement, ensure at least one planned step will produce the needed information.
        3. If ANY requirement is not covered by the steps, add the minimal additional step(s).

        B) SPECIAL RULE FOR get_charity_stats (main data source):
        - The ONLY callable tool for charity stats is: get_charity_stats
        - You MUST choose a concrete tool_name value yourself from its allowed list.
        - Never put "tool_name" in missing_args for get_charity_stats.
        - Use ONE get_charity_stats call to satisfy multiple needs when possible:
            * If user wants list of charities AND donor-count statistics, choose tool_name="charity_donor_count"
            because it provides charity names + donor counts in one call.

        C) MANDATORY PYTHON TRIGGER (non-negotiable):
        - If the user asks for ANY numeric aggregation or statistic such as:
            median, mean, average, avg, std, standard deviation, min, max, sum, total
            OR explicitly says "use python"
            THEN you MUST include a Python_REPL step.
        - Python_REPL must NEVER have empty args.

        D) Python_REPL argument format (single-input tool):
        - For Python_REPL, args MUST be:
            {{ "input": "<python code that prints ONLY the final numeric result>" }}
        - Do not include explanations in the code. Just compute and print the value.
        - If donor counts are already present in chat history as a ToolMessage output,
            use them directly in the Python code without re-calling get_charity_stats.

        E) TOOL REUSE RULE (avoid redundant calls):
        - If the exact needed data already exists in chat history ToolMessage outputs, do NOT call tools again.
        - In that case, plan only the missing computation step(s) (often Python_REPL).

        OUTPUT FORMAT (STRICT JSON ONLY):
        {{
        "steps": [
            {{"tool": "tool_name", "args": {{"arg_name": "value"}}}}
        ],
        "missing_args": []
        }}

        Examples (follow exactly; adapt values as needed):

        Example 1:
        User: "Provide me list of charities"
        Plan:
        {{"steps":[{{"tool":"get_charity_stats","args":{{"tool_name":"charity_donor_count"}}}}],"missing_args":[]}}

        Example 2:
        User: "Provide me list of charities. Find median of donor counts (use python)"
        Plan (minimal, fully covering):
        {{
        "steps": [
            {{"tool":"get_charity_stats","args":{{"tool_name":"charity_donor_count"}}}},
            {{"tool":"Python_REPL","args":{{"input":"import statistics\\ncounts=[4,2]\\nprint(statistics.median(counts))"}}}}
        ],
        "missing_args":[]
        }}

        Now plan for this request using the chat history below.

        Chat History (may contain prior ToolMessage outputs to reuse):
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

        planner_messages = [HumanMessage(content=prompt)]

        #--------------------------------------------------------------
        if DEBUG_MESSAGES == 1:
            rich_print("\n" + "="*80)
            rich_print("PLANNER INVOKE MESSAGES (exact objects)")
            rich_print("="*80)
            for i, m in enumerate(planner_messages):
                rich_print(f"\n--- planner_messages[{i}] ---")
                rich_print(format_msg(m))
            rich_print("="*80)
        #--------------------------------------------------------------

        response = model.invoke(planner_messages)

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
            if plan.get("missing_args"):
                rich_print(f"[PLANNER] Missing args: {plan['missing_args']}")

        return {"plan": plan}

    return planner_node


# ========================== VALIDATOR, EXECUTOR, RESPONDER (100% unchanged from second script) ==========================
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

# ========================== 3. UPDATED EXECUTOR NODE (handles both single-arg and structured) ==========================
def make_executor_node(tools_by_name: dict):
    # --- helpers (local to executor) ---
    def _invoke_tool(tool, raw_args: dict):
        """
        Invoke tools robustly:
        - StructuredTool / tools with args_schema: pass dict
        - Single-input tools (e.g., Python_REPL): pass a single string
        - If planner accidentally passes multi-arg dict to a single-input tool: stringify
        """
        # StructuredTool / any tool exposing args_schema should receive a dict
        if getattr(tool, "args_schema", None) is not None:
            return tool.invoke(raw_args)

        # Otherwise assume single-input tool
        if not raw_args:
            return tool.invoke("")
        if len(raw_args) == 1:
            return tool.invoke(next(iter(raw_args.values())))
        return tool.invoke(json.dumps(raw_args, ensure_ascii=False))

    def _normalize_result(result):
        """
        Ensure ToolMessage.content is ALWAYS valid JSON.
        - If result is JSON-like string -> parse to python object
        - If result is plain text -> wrap as {"ok": True, "result": "<text>"}
        - If result is already dict/list -> wrap as {"ok": True, "result": obj}
        """
        if result is None:
            return {"ok": True, "result": None}

        if isinstance(result, (dict, list, int, float, bool)):
            return {"ok": True, "result": result}

        if isinstance(result, str):
            s = result.strip()
            # Parse JSON strings only when they look like JSON
            if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                try:
                    return {"ok": True, "result": json.loads(s)}
                except json.JSONDecodeError:
                    pass
            return {"ok": True, "result": s}

        # Fallback: stringify unknown objects
        return {"ok": True, "result": str(result)}

    def get_historical_tool_data(ref_tool, local_results, all_messages):
        if ref_tool in local_results:
            return local_results[ref_tool]
        for msg in reversed(all_messages):
            if isinstance(msg, ToolMessage) and msg.name == ref_tool:
                try:
                    # ToolMessage.content is JSON (because we normalize it)
                    payload = json.loads(msg.content)
                    # unwrap if our envelope is used
                    if isinstance(payload, dict) and "result" in payload:
                        return payload["result"]
                    return payload
                except Exception:
                    pass
        return None

    def executor_node(state: AgentState) -> Dict:
        plan = state.get("plan", {})
        steps = plan.get("steps", [])
        missing_args = plan.get("missing_args", [])

        if not steps:
            return {}

        messages: List[BaseMessage] = []
        tool_results: Dict[str, Any] = {}

        for step in steps:
            tool_name = step.get("tool")
            raw_args = dict(step.get("args", {}) or {})

            if tool_name not in tools_by_name:
                messages.append(AIMessage(content=f"System Note: Tool '{tool_name}' not found. Skipping."))
                continue

            tool = tools_by_name[tool_name]

            try:
                result = _invoke_tool(tool, raw_args)
            except Exception as e:
                # Never crash the graph on tool errors; surface it as tool output
                payload = {"ok": False, "error": str(e), "tool": tool_name, "args": raw_args}
                tool_results[tool_name] = payload
                messages.append(ToolMessage(
                    content=json.dumps(payload, ensure_ascii=False, default=str),
                    name=tool_name,
                    tool_call_id=str(uuid4()),
                ))
                if DEBUG_MESSAGES == 1:
                    rich_print(f"[EXECUTOR][ERROR] {tool_name} failed with args {raw_args}: {e}")
                continue

            payload = _normalize_result(result)  # always JSON-serializable
            tool_results[tool_name] = payload["result"]

            messages.append(ToolMessage(
                content=json.dumps(payload, ensure_ascii=False, default=str),
                name=tool_name,
                tool_call_id=str(uuid4()),
            ))

            if DEBUG_MESSAGES == 1:
                rich_print(f"[EXECUTOR] {tool_name} executed successfully with args {raw_args}")

        if missing_args:
            messages.append(
                AIMessage(
                    content=f"System Note: Tools executed successfully. Now ask the user to provide: {', '.join(missing_args)}"
                )
            )

        return {"messages": messages}

    return executor_node



def make_responder_node():
    model = make_model(temperature=0.0)

    def responder(state: AgentState) -> Dict:

        system_prompt = """
        You are a Charity & Data Assistant that produces FINAL, USER-FACING answers.

        OUTPUT RULES (STRICT):
        - Do NOT reveal your chain-of-thought, reasoning, internal steps, or analysis.
        - Do NOT describe tool usage steps (no "I called X then Y", no "first I...", no "let's compute...").
        - Do NOT output any code blocks or code snippets (no Python, no pseudo-code).
        - Do NOT include intermediate calculations, scratch work, or debugging info.
        - ONLY use information explicitly present in the Conversation History (especially TOOL outputs).
        - If the needed value is not present in the tool outputs, say what is missing and ask for the minimum needed input.

        TOOL GROUNDING RULES:
        - Treat TOOL[...] lines as the only source of truth for computed values.
        - If a Python_REPL tool output exists, use its numeric result directly.
        - If the user requested "use python", you may add a short attribution like:
        "Computed using Python." (one sentence max). Do not show code.

        FORMAT RULES:
        - Use concise, organized formatting.
        - Prefer: short intro sentence + bullet list or small sections.
        - Never include "Thought process", "Reasoning", "Analysis", or similar headings.

        Now write the final answer based strictly on the Conversation History below.
        """

        transcript = format_history_for_responder(state.get("messages", []))
        final_prompt = [HumanMessage(content=f"{system_prompt}\n\nConversation History:\n{transcript}")]

        #--------------------------------------------------------------
        if DEBUG_MESSAGES == 1:
            # rich_print("\n" + "="*80)
            # rich_print("RESPONDER INPUT (rendered final_prompt[0].content)")
            # rich_print("="*80)
            # rich_print(final_prompt[0].content)
            # rich_print("="*80)

            rich_print("\n" + "="*80)
            rich_print("RESPONDER INVOKE MESSAGES (exact objects)")
            rich_print("="*80)
            for i, m in enumerate(final_prompt):
                rich_print(f"\n--- final_prompt[{i}] ---")
                rich_print(format_msg(m))
            rich_print("="*80)
        #--------------------------------------------------------------

        summary = model.invoke(final_prompt)

        final_text = (summary.content or "").strip()

        return {"messages": [summary], "final_answer": final_text}

    return responder


# ========================== ROUTING (exact from second script) ==========================
def route_after_validator(state: AgentState) -> str:
    plan = state.get("plan", {})
    steps = plan.get("steps", [])
    return "executor" if len(steps) > 0 else "responder"


# ========================== BUILD GRAPH ==========================
async def build_graph():
    tools = await setup_tools()
    tools_by_name = {t.name: t for t in tools}

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", make_planner_node(tools_by_name))
    workflow.add_node("validator", make_validator_node(tools_by_name))
    workflow.add_node("executor", make_executor_node(tools_by_name))
    workflow.add_node("responder", make_responder_node())

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "validator")   # direct to validator (reflection removed)

    workflow.add_conditional_edges("validator", route_after_validator, {"executor": "executor", "responder": "responder"})

    workflow.add_edge("executor", "responder")
    workflow.add_edge("responder", END)

    return workflow.compile()


# ========================== MAIN (interactive like second script + your rich logging) ==========================
async def main():
    graph = await build_graph()

    chat_memory = []

    console = Console()

    rich_print("\n" + "="*60)
    rich_print("CHARITY AGENT – Second Script Architecture + Your Transcripts")
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
            async for step in graph.astream({"messages": chat_memory}, stream_mode="updates"):
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
                                if "System Note:" in msg.content:
                                    pass
                                else:
                                    rich_print(f"\nAgent: {msg.content}\n")

        except Exception as e:
            rich_print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
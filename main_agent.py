import os
import asyncio
import json
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

from tools.tool_setup import setup_tools, build_tool_context
from llm import make_model
from tools.tool_patcher import patch_tool_descriptions
from history_formatters import format_history_for_responder, _parse_plan
from nodes import (
    make_planner_node,
    make_validator_node,
    make_executor_node,
    make_gate_node,
    make_responder_node,
)
from routing import route_after_validator, route_after_gate
from rich.markdown import Markdown  
from rich.panel import Panel        

import dotenv
dotenv.load_dotenv()

# Import from context (NO circular import)
from context import auth_token_ctx

GATE_MAX_REACT_STEPS = int(os.getenv("GATE_MAX_REACT_STEPS", "1"))


class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Dict[str, Any]
    repair_attempts: int
    last_tool_error: Dict[str, Any]
    last_agentic_step: Dict[str, Any]


# 🔥 Hardcoded token (for CLI testing only)
HARDCODED_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2OTU4MDNhOTVkMTIwZGI2MWFmYWYwM2UiLCJyb2xlIjoiRG9ub3IiLCJwcm9maWxlVHlwZSI6IkRvbm9yIiwiaWF0IjoxNzcxNDg1NzYyLCJleHAiOjQ5MjcyNDU3NjJ9.9bTr--7-iHIemenKrFRYL3uTDx9auCY98GvYa0NnaOg"


async def build_graph():
    tools = await setup_tools()

    tools_by_name = {t.name: t for t in tools}

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", make_planner_node(tools_by_name))
    workflow.add_node("validator", make_validator_node(tools_by_name))
    workflow.add_node("executor", make_executor_node(tools_by_name))
    workflow.add_node("gate", make_gate_node(tools_by_name, max_react_steps=GATE_MAX_REACT_STEPS))
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


async def main():
    # ── NEW: CLI Token Verification ──
    rich_print("[yellow]Verifying CLI token...[/yellow]")
    try:
        import requests
        res = requests.get(
            "https://giverr-api.verior.co/api/v3/agent/verify-token",
            headers={"Authorization": f"Bearer {HARDCODED_TOKEN}"},
            timeout=5
        )
        if not res.json().get("success"):
            rich_print("[bold red]ERROR: CLI Token is invalid or expired![/bold red]")
            return
        rich_print("[green]Token Verified. Starting Agent...[/green]")
    except Exception as e:
        rich_print(f"[red]Could not verify token: {e}[/red]")
        # Decide if you want to 'return' or continue anyway for local-only testing
        
    graph = await build_graph()

    chat_memory: List[BaseMessage] = []
    console = Console()

    rich_print("\n" + "="*60)
    rich_print("CHARITY AGENT – Advanced Modular Version (Auth Enabled)")
    rich_print("Type 'exit', 'quit', or 'q' to stop.")
    rich_print("="*60 + "\n")

    # Set token in context ONCE
    token_ctx = auth_token_ctx.set(HARDCODED_TOKEN)

    try:
        while True:
            try:
                user_input = input("User: ")
            except (KeyboardInterrupt, EOFError):
                rich_print("\nGoodbye!")
                break

            if user_input.lower() in ["exit", "quit", "q"]:
                rich_print("\nGoodbye!")
                break

            chat_memory.append(HumanMessage(content=user_input))

            rich_print("\n(Agent is thinking...)\n")

            try:
                async for step in graph.astream(
                    {"messages": chat_memory, "repair_attempts": 0},
                    stream_mode="updates"
                ):
                    for node_name, node_output in step.items():
                        if not node_output:
                            continue

                        if "messages" in node_output:
                            for msg in node_output["messages"]:
                                chat_memory.append(msg)

                                if isinstance(msg, ToolMessage):
                                    rich_print(f" ➤ [Tool Executed] {msg.name}")

                                elif isinstance(msg, AIMessage):
                                    content = (msg.content or "").strip()

                                    if getattr(msg, "tool_calls", None) and not content:
                                        continue
                                    if content.startswith("System Note:"):
                                        continue
                                    if content.startswith("FINAL_AGENT_STEP[gate] -> "):
                                        continue

                                    console.print(
                                        Panel(
                                            Markdown(content),
                                            title="[bold cyan]Agent[/bold cyan]",
                                            border_style="cyan",
                                        )
                                    )
                                    rich_print()

            except Exception as e:
                rich_print(f"\n[ERROR] {e}")
                import traceback
                traceback.print_exc()

    finally:
        # Cleanup context
        auth_token_ctx.reset(token_ctx)


if __name__ == "__main__":
    asyncio.run(main())
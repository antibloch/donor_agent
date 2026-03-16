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
from rich.console import Console
from rich import print as rich_print
from rich.markdown import Markdown  
from rich.panel import Panel        
import dotenv
dotenv.load_dotenv()
GATE_MAX_REACT_STEPS = int(os.getenv("GATE_MAX_REACT_STEPS", "1"))


class AgentState(TypedDict, total=False):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    plan: Dict[str, Any]
    repair_attempts: int
    last_tool_error: Dict[str, Any]
    last_agentic_step: Dict[str, Any]   # <- add this


def _should_wrap_as_password(messages: Sequence[BaseMessage]) -> bool:
    for msg in reversed(messages or []):
        if isinstance(msg, AIMessage):
            content = (msg.content or "").strip().lower()
            if content == "please enter password":
                return True
            if "your password" in content and ("enter" in content or "add" in content):
                return True
            return False
    return False

async def build_graph():
    tools = await setup_tools()

    # Patch tool descriptions with usage hints for better performance
    # tools = patch_tool_descriptions(tools)

    tools_by_name = {t.name: t for t in tools}

    workflow = StateGraph(AgentState)
    workflow.add_node("planner", make_planner_node(tools_by_name))
    workflow.add_node("validator", make_validator_node(tools_by_name))
    workflow.add_node("executor", make_executor_node(tools_by_name))
    workflow.add_node("gate", make_gate_node(tools_by_name, max_react_steps=GATE_MAX_REACT_STEPS))
    workflow.add_node("responder", make_responder_node(tools_by_name))

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
    graph = await build_graph()

    chat_memory: List[BaseMessage] = []
    console = Console()

    rich_print("\n" + "="*60)
    rich_print("CHARITY AGENT – Advanced Modular Version (Gate + Smart History)")
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

        outgoing_user_input = user_input
        if _should_wrap_as_password(chat_memory):
            outgoing_user_input = f"Password: {user_input}"

        user_msg = HumanMessage(content=outgoing_user_input)
        chat_memory.append(user_msg)

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
                        new_messages = node_output["messages"]
                        for msg in new_messages:
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

                                md = Markdown(content)
                                console.print(
                                    Panel(
                                        md,
                                        title="[bold cyan]Agent[/bold cyan]",
                                        title_align="left",
                                        border_style="cyan",
                                        expand=False,
                                    )
                                )
                                rich_print()
        except Exception as e:
            rich_print(f"\n[ERROR] {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

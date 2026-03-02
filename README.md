# Donor Agent
`combined_agent` is a LangGraph-based, tool-using CLI agent for charity/donation + auction workflows.

# Big Picture

  - Entry point is main_agent.py:40.
  - It builds a 5-node graph: planner -> validator -> executor -> gate -> responder (with conditional routing back to validator for one repair attempt).
  - The graph state carries chat messages, a JSON plan, and repair metadata.

# Execution Flow

  1. planner (LLM) generates strict JSON tool steps from user request: nodes.py:26
  2. validator filters invalid tool names / missing args and can stop for clarification: nodes.py:117
  3. executor runs tools, normalizes outputs to {ok, result/error}, and writes ToolMessages: nodes.py:152
  4. gate detects latest tool error and asks LLM to create a repair plan (max 1 retry): nodes.py:300
  5. responder produces final user-facing answer from conversation history/tool outputs only: nodes.py:263

  Routing decisions are tiny helpers in routing.py:1.

# Tools Layer

  - Tool registration is centralized in tools/tool_setup.py:12.
  - It combines:
      - local tools from tools/analytics.py:11, tools/transactions.py:17, tools/auctions.py:13
      - PythonREPLTool
      - MCP tools via fetcher-mcp
  - Tool descriptions are patched with metadata hints in tools/tool_patcher.py:1.

# History / Safety

  - History is curated differently for planner/gate/responder in history_formatters.py:166.
  - Sensitive fields (token, authorization, etc.) are stripped before feeding history to LLM: tools/json_utils.py:14.

# Backends

  - Local dummy services:
      - Charity stats/blogs/products/ranking server: dummy_server/server_charity.js:1
      - Auction/wallet server with persisted JSON DB: dummy_server/server_auction.js:1, data in dummy_server/data.json:1
  - External donations API is called from transactions.py (BASE_URL = giverr-api.verior.co).

# Model

  - LLM client config is in llm.py:1, using ChatOpenAI with NVIDIA endpoint/model.

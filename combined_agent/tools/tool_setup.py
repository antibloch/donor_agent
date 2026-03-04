from .analytics import *
from .auctions import *
from .transactions import *
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from typing import Any

# --------------------------
# Tool setup
# --------------------------

async def setup_tools():
    local_tools = [
        # charity analytics tools
        build_node_stats_tool(),
        PythonREPLTool(),

        # transactions tools
        check_wallet_balance, 
        fund_wallet, 
        get_payment_methods, 
        add_payment_method, 
        list_charities_by_country, 
        get_charity_donation_products,
        get_all_charities_with_grants, 
        product_donation, 
        get_all_active_campaigns, 
        grant_donation, 
        get_transaction_history, 
        get_donation_types_campaign, 
        campaign_donation,

        # auction tools
        # build_get_wallet_balance_tool(),
        # build_get_active_auctions_tool(),
        # build_get_auction_details_tool(),
        # build_get_auction_bids_tool(),
        # build_get_auction_items_tool(),
        # build_get_my_bid_history_tool(),
        # build_place_bid_tool(),
        # build_finalize_ended_auctions_tool(),
        # build_get_donation_categories_tool(),     
        # build_get_charities_by_category_tool(),

    ]

    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    # additional charity analytics tools
    mcp_tools = await client.get_tools()

    
    return [*local_tools, *mcp_tools] 




def build_tool_context(tools_by_name: dict):
    def _normalize_type(annotation: Any) -> str:
        if annotation is None:
            return "any"
        text = str(annotation).replace("typing.", "")
        return text

    def _render_args_bullets(tool: Any) -> str:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            if not fields:
                return "- None"

            lines = []
            for field_name, field in fields.items():
                required = getattr(field, "is_required", lambda: False)()
                lines.append(f"- {field_name} ({'required' if required else 'optional'})")
            return "\n".join(lines)

        # Preserve previous explicit fallback for tools without declared schema.
        if getattr(tool, "name", "") == "Python_REPL":
            return "- input (required string). For Python_REPL, this must be python code."

        return "- input (required)"

    def _render_args_markdown(tool: Any) -> str:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_fields"):
            fields = args_schema.model_fields
            if not fields:
                return "_No parameters required._"

            lines = [
                "| Parameter | Required | Type | Description |",
                "|---|---|---|---|",
            ]

            for field_name, field in fields.items():
                required = getattr(field, "is_required", lambda: False)()
                field_type = _normalize_type(getattr(field, "annotation", None))
                description = (getattr(field, "description", "") or "No description.").strip().replace("\n", " ")
                lines.append(
                    f"| `{field_name}` | {'Yes' if required else 'No'} | `{field_type}` | {description} |"
                )
            return "\n".join(lines)

        return "_Parameters are not explicitly declared. Pass the expected input payload for this tool._"

    sections = ["# Available Tools"]
    tools_sorted = sorted(tools_by_name.values(), key=lambda t: getattr(t, "name", "").lower())

    for index, tool in enumerate(tools_sorted, start=1):
        name = tool.name
        description = (getattr(tool, "description", "") or "No description.").strip()
        args_text = _render_args_markdown(tool)

        sections.append(
            "\n".join(
                [
                    f"## {index}. `{name}`",
                    "",
                    "### Description",
                    description,
                    "",
                    "### Arguments",
                    _render_args_bullets(tool),
                    "",
                    "### Parameters",
                    args_text,
                ]
            )
        )

    return "\n\n".join(sections).strip()

from .analytics import *
from .auctions import *
from .transactions import *
from langchain_experimental.tools import PythonREPLTool
from langchain_mcp_adapters.client import MultiServerMCPClient


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
        build_get_wallet_balance_tool(),
        build_get_active_auctions_tool(),
        build_get_auction_details_tool(),
        build_get_auction_bids_tool(),
        build_get_auction_items_tool(),
        build_get_my_bid_history_tool(),
        build_place_bid_tool(),
        build_finalize_ended_auctions_tool(),
        build_get_donation_categories_tool(),     
        build_get_charities_by_category_tool(),

    ]

    client = MultiServerMCPClient({
        "fetch": {"transport": "stdio", "command": "npx", "args": ["-y", "fetcher-mcp"]}
    })
    # additional charity analytics tools
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
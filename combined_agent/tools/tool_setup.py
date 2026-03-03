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
    def _extract_desc_and_metadata(raw_desc: str):
        start_marker = "### META_DATA_START ###"
        end_marker = "### META_DATA_END ###"

        start_idx = raw_desc.find(start_marker)
        end_idx = raw_desc.find(end_marker)

        if start_idx == -1 or end_idx == -1 or end_idx <= start_idx:
            return raw_desc.strip() or "No description.", {}

        clean_desc = raw_desc[:start_idx].strip() or "No description."
        metadata_block = raw_desc[start_idx + len(start_marker):end_idx].strip()
        metadata = {}

        for line in metadata_block.splitlines():
            stripped = line.strip()
            if ":" not in stripped:
                continue
            if not stripped[:2].isdigit() and not stripped.startswith("1."):
                continue
            _, remainder = stripped.split(" ", 1) if " " in stripped else ("", stripped)
            if ":" not in remainder:
                continue
            key, value = remainder.split(":", 1)
            norm_key = key.strip().lower().replace(" ", "_")
            parsed = value.strip()
            if parsed.lower() == "true":
                parsed = True
            elif parsed.lower() == "false":
                parsed = False
            elif parsed.lower() == "null":
                parsed = None
            metadata[norm_key] = parsed

        # Normalize keys expected by routing/grouping.
        normalized = {
            "domain": metadata.get("domain"),
            "type": metadata.get("type"),
            "when_to_use": metadata.get("when_to_use"),
            "do_not_use": metadata.get("do_not_use"),
            "supports_pagination": metadata.get("supports_pagination"),
            "requires_auth": metadata.get("requires_auth"),
            "example_usage": metadata.get("example_usage"),
            "hint": metadata.get("hint"),
        }
        return clean_desc, {k: v for k, v in normalized.items() if v is not None}

    # Group tools by domain
    tools_by_domain = {}
    for tool in tools_by_name.values():
        name = tool.name
        raw_desc = (getattr(tool, "description", "") or "").strip()
        clean_desc, metadata = _extract_desc_and_metadata(raw_desc)

        domain = metadata.get("domain", "general")
        tools_by_domain.setdefault(domain, []).append({
            "name": name,
            "description": clean_desc,
            "metadata": metadata,
            "tool": tool
        })

    output_parts = []
    for domain, tools_list in tools_by_domain.items():
        output_parts.append(f"## Domain: {str(domain).upper()}")
        output_parts.append("")

        for tool_data in tools_list:
            name = tool_data["name"]
            raw_desc = tool_data["description"]
            metadata = tool_data["metadata"]
            tool = tool_data["tool"]

            output_parts.append(f"### Tool: {name}")
            output_parts.append("1. Tool Overview")
            output_parts.append(f"1.1. Name: {name}")
            output_parts.append(f"1.2. Domain: {metadata.get('domain', 'general')}")
            output_parts.append("")

            output_parts.append("2. Description")
            desc_lines = [ln.strip() for ln in raw_desc.splitlines() if ln.strip()]
            if desc_lines:
                output_parts.append(f"2.1. Summary: {desc_lines[0]}")
                if len(desc_lines) > 1:
                    output_parts.append("2.2. Details")
                    for idx, line in enumerate(desc_lines[1:], start=1):
                        output_parts.append(f"2.2.{idx}. {line}")
            else:
                output_parts.append("2.1. Summary: No description.")
            output_parts.append("")

            output_parts.append("3. Parameters")
            args_schema = getattr(tool, "args_schema", None)
            if args_schema and hasattr(args_schema, "model_fields") and args_schema.model_fields:
                for idx, (k, v) in enumerate(args_schema.model_fields.items(), start=1):
                    req = getattr(v, "is_required", lambda: False)()
                    field_type = getattr(v, "annotation", "any")
                    type_str = getattr(field_type, "__name__", str(field_type))
                    default = getattr(v, "default", None)
                    req_str = "required" if req else "optional"
                    output_parts.append(f"3.{idx}. {k}")
                    output_parts.append(f"3.{idx}.1. Type: {type_str}")
                    output_parts.append(f"3.{idx}.2. Requirement: {req_str}")
                    if default is not None:
                        output_parts.append(f"3.{idx}.3. Default: {default}")
            else:
                output_parts.append("3.1. input")
                output_parts.append("3.1.1. Type: string")
                output_parts.append("3.1.2. Requirement: required")
            output_parts.append("")

            if metadata:
                output_parts.append("4. Meta Data")
                meta_order = [
                    "type",
                    "when_to_use",
                    "do_not_use",
                    "supports_pagination",
                    "requires_auth",
                    "example_usage",
                    "hint",
                ]
                idx = 1
                for key in meta_order:
                    if key in metadata:
                        label = key.replace("_", " ").title()
                        output_parts.append(f"4.{idx}. {label}: {metadata[key]}")
                        idx += 1
                output_parts.append("")

    return "\n".join(output_parts).strip()
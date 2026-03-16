from .analytics import (build_charity_discovery_tool, 
                        build_charity_detail_tool, 
                        Python_tool, 
                        Crawler_tool
                        )
from .auctions import (
    get_active_auctions,
    get_auction_details,
    get_my_bid_history,
    place_bid,
    get_donation_categories,
    get_charities_by_donation_type,
)
from .transactions import *
from typing import Any
import json
from langchain_core.messages import HumanMessage
# --------------------------
# Tool setup
# --------------------------

async def setup_tools():

    local_tools = [
        # charity analytics tools
        build_charity_discovery_tool(),
        build_charity_detail_tool(),
        Python_tool(),

        # transactions tools
        check_wallet_balance, 
        fund_wallet, 
        list_saved_payment_methods, 
        create_payment_method_url, 
        list_charities_in_country,
        list_charity_products, 
        product_donation, 
        list_charity_active_campaigns,
        list_campaign_donation_types,
        campaign_donation,
        list_charity_grants, 
        grant_donation, 
        get_transaction_history, 

        #auction tools
        # auction tools
        get_active_auctions,
        get_auction_details,
        get_my_bid_history,
        place_bid,
        get_donation_categories,
        get_charities_by_donation_type,
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

    crawler_tools = await Crawler_tool()
    return [*local_tools, *crawler_tools]
    



def build_tool_context(
    tools_by_name: dict,
    *,
    do_selection: bool = False,
    user_query: str = "",
    chat_history: str = "",
    model: Any = None,
):
    def _render_tool_context(local_tools_by_name: dict) -> str:
        sections = ["# Available Tools"]
        tools_sorted = sorted(local_tools_by_name.values(), key=lambda t: getattr(t, "name", "").lower())

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

    def _select_reduced_tool_map(full_context: str) -> dict:
        if model is None:
            return tools_by_name

        selector_prompt = f"""
                You are a tool selector for a planner. Build a MAXIMAL PLAUSIBLE subset of tools for the current user request.
                Goal: remove only clearly implausible tools, while preserving all tools needed for the full dependency-aware orchestration that could answer the request.

                Rules:
                - Keep every tool that is plausibly useful for any part of the current request.
                - Keep prerequisite tools, downstream tools, and follow-up tools when the tool descriptions indicate they form a normal dependency chain.
                - Do not keep only the first tool in a chain if later tools are needed to actually answer the user.
                - Exclude a tool only if it is clearly irrelevant to the request and immediate follow-up needs.
                - Prioritize recall over precision: false positives are acceptable, false negatives are not.
                - Chat history may contain cached tool traces labeled as `CACHED_TOOL_CALL[...]` and cached successful results labeled as `CACHED_SUCCESS[...]`.
                - Use `CACHED_SUCCESS[...]` to understand what information is already available, and use `CACHED_TOOL_CALL[...]` to understand which tools were previously used.
                - Use chat history only to disambiguate intent, entities, and already-available information.
                - Reason silently about the complete path from user request to answer, then include all tools that could be needed along that path.
                - Prefer complete dependency coverage over aggressive narrowing.
                - If a vague charity name is mentioned, preserve the default charity chain when relevant.
                - If downstream arguments are not yet known, still preserve the tool that will need those arguments later.
                - Keep auth-sensitive action tools and any prerequisite lookup tools needed to execute them safely.
                - Return only tool names that exist in the provided tool catalog.
                - Never return an empty list unless no listed tool is remotely relevant.
                - Output STRICT JSON only in this format:
                {{
                "selected_tools": ["tool_name_1", "tool_name_2"]
                }}

                Tool Catalog:
                {full_context}

                Chat History:
                {chat_history}

                Current User Request:
                {user_query}
                """
        try:
            response = model.invoke([HumanMessage(content=selector_prompt)])
            parsed = json.loads((response.content or "").strip())
            selected = parsed.get("selected_tools", [])
            if not isinstance(selected, list):
                return tools_by_name

            selected_names = []
            for name in selected:
                if isinstance(name, str) and name in tools_by_name and name not in selected_names:
                    selected_names.append(name)

            if not selected_names:
                return tools_by_name
            return {name: tools_by_name[name] for name in selected_names}
        except Exception:
            return tools_by_name

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
            return "- query (required string containing atleast 3 line code). For Python_REPL, this must be python code."
        
        if getattr(tool, "name", "") == "fetch_url":
            return "- url (required string). The full URL to fetch. Must include schema (e.g., 'https://...'). Prefer https over http."

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

        return "string (required)"

    full_context = _render_tool_context(tools_by_name)
    if not do_selection:
        return full_context

    reduced_map = _select_reduced_tool_map(full_context)
    return _render_tool_context(reduced_map)

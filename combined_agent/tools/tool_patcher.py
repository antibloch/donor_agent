import json

METADATA = {
    "Python_REPL": {
        "domain": "utility",
        "type": "compute",
        "when_to_use": "When arithmetic, transformation, parsing, or quick one-off computations are needed.",
        "do_not_use": "Do not use for external web/page fetches or tool discovery.",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=Python_REPL",
    },
    "get_charity_stats": {
        "domain": "charity",
        "type": "stats",
        "when_to_use": "When user asks for donor counts, impact metrics, rankings, blogs, products, addresses, or any numeric summary per charity",
        "do_not_use": "Never use for wallet, bids, payments, or auctions -- those belong to transaction/auction tools",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=charity_donor_count",
    },
    "fetch_url": {
        "domain": "web",
        "type": "action",
        "when_to_use": "When a specific URL is already known and you need page content.",
        "do_not_use": "Do not use when you need discovery/search over unknown URLs.",
        "supports_pagination": False,
        "requires_auth": False,
        "example_usage": "tool_name=fetch_url",
    },
    "fetch_urls": {
        "domain": "web",
        "type": "paginate",
        "when_to_use": "When multiple known URLs should be fetched in one operation.",
        "do_not_use": "Do not use for keyword search/discovery over the open web.",
        "supports_pagination": True,
        "requires_auth": False,
        "example_usage": "tool_name=fetch_urls",
    },
}





def patch_tool_descriptions(tools: list) -> list:
    """
    Patch tool descriptions with structured metadata for routing/classification.

    :param tools: List of tool objects.
    :type tools: list
    :return: Updated tool list.
    :rtype: list
    """
    patched_tools = []

    for tool in tools:
        name = getattr(tool, "name", tool.__class__.__name__)
        original_desc = (getattr(tool, "description", "") or "").strip()

        metadata = METADATA.get(name)

        if metadata:
            metadata_block = json.dumps({"metadata": metadata}, ensure_ascii=True, indent=2)
            new_desc = f"{original_desc}\n\n{metadata_block}" if original_desc else metadata_block

            try:
                tool.description = new_desc
            except Exception:
                # Some tools may not allow mutation (StructuredTool edge cases)
                pass

        patched_tools.append(tool)

    return patched_tools

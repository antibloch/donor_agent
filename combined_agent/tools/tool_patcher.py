HINTS = {
    "Python_REPL": (
        "Only printed output is returned.\n"
        "ALWAYS end your code with print(...) of the final result.\n"
        "Prefer minimal Python; avoid heavy libraries unless necessary.\n"
        "If computing statistics, print a compact JSON-like dict."
    ),
    "get_charity_stats": (
        "Input must be EXACTLY one valid tool name string.\n"
        "The response is JSON. The actual results are in the 'data' field.\n"
        "Do not guess tool names — use only listed valid names."
    ),
    "fetch_url": (
        "Use this when you already have a specific URL and need the page content.\n"
        "Prefer this over web search when the task says 'read this URL' or 'extract details from this page'."
    ),
    "fetch_urls": (
        "Fetch multiple URLs in one call when you need to read several pages quickly."
    ),
}







def patch_tool_descriptions(tools: list) -> list:
    """
    Docstring for patch_tool_descriptions with additional hints for better performance
    
    :param tools: Description
    :type tools: list
    :return: Description
    :rtype: list
    """
    patched_tools = []

    for tool in tools:
        name = getattr(tool, "name", tool.__class__.__name__)
        original_desc = (getattr(tool, "description", "") or "").strip()

        hint = HINTS.get(name)

        if hint:
            new_desc = (
                original_desc
                + "\n\nUSAGE HINTS:\n"
                + hint
            )

            try:
                tool.description = new_desc
            except Exception:
                # Some tools may not allow mutation (StructuredTool edge cases)
                pass

        patched_tools.append(tool)

    return patched_tools
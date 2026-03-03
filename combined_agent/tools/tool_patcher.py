import json
from .analytics import metadata_analytics
from .auctions import metadata_auctions
from .transactions import metadata_transaction

METADATA = metadata_analytics | metadata_auctions | metadata_transaction





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

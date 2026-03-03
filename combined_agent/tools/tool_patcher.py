import json
from .analytics import metadata_analytics
from .auctions import metadata_auctions
from .transactions import metadata_transaction

METADATA = metadata_analytics | metadata_auctions | metadata_transaction



def _format_scalar(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return str(value)



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
            metadata_lines = ["1. Meta Data", "1.1. Classification"]
            metadata_lines.append(f"1.1.1. Domain: {_format_scalar(metadata.get('domain'))}")
            metadata_lines.append(f"1.1.2. Type: {_format_scalar(metadata.get('type'))}")
            metadata_lines.append("1.2. Usage Guidance")
            metadata_lines.append(f"1.2.1. When To Use: {_format_scalar(metadata.get('when_to_use'))}")
            metadata_lines.append(f"1.2.2. Do Not Use: {_format_scalar(metadata.get('do_not_use'))}")
            metadata_lines.append("1.3. Runtime Flags")
            metadata_lines.append(
                f"1.3.1. Supports Pagination: {_format_scalar(metadata.get('supports_pagination'))}"
            )
            metadata_lines.append(f"1.3.2. Requires Auth: {_format_scalar(metadata.get('requires_auth'))}")
            metadata_lines.append("1.4. Examples")
            metadata_lines.append(f"1.4.1. Example Usage: {_format_scalar(metadata.get('example_usage'))}")
            metadata_lines.append(f"1.4.2. Hint: {_format_scalar(metadata.get('hint'))}")

            metadata_block = (
                "### META_DATA_START ###\n"
                + "\n".join(metadata_lines)
                + "\n### META_DATA_END ###"
            )
            new_desc = f"{original_desc}\n\n{metadata_block}" if original_desc else metadata_block

            try:
                tool.description = new_desc
            except Exception:
                # Some tools may not allow mutation (StructuredTool edge cases)
                pass

        patched_tools.append(tool)

    return patched_tools

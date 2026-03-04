import re
from .analytics import metadata_analytics
from .auctions import metadata_auctions
from .transactions import metadata_transaction

METADATA = metadata_analytics | metadata_transaction



def _parse_bullets(value) -> list[str]:
    """
    Normalize metadata text/list values into clean bullet items.
    Handles:
    - already-a-list values
    - multiline bullet strings
    - concatenated '- item - item' strings
    """
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]

    text = str(value).strip()
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    explicit_bullets = []
    for line in lines:
        if re.match(r"^[-*•]\s+", line):
            explicit_bullets.append(re.sub(r"^[-*•]\s+", "", line).strip())

    if explicit_bullets:
        return explicit_bullets

    if text.count("- ") >= 2:
        parts = [p.strip() for p in re.split(r"\s*-\s+", text) if p.strip()]
        if len(parts) > 1:
            return parts

    return [text]


def _bool_label(value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def format_metadata_markdown(metadata: dict) -> str:
    """
    Convert metadata dict into compact, LLM-friendly markdown.
    """
    domain = metadata.get("domain", "unknown")
    tool_type = metadata.get("type", "unknown")
    supports_pagination = _bool_label(metadata.get("supports_pagination", "unknown"))
    requires_auth = _bool_label(metadata.get("requires_auth", "unknown"))
    when_to_use = _parse_bullets(metadata.get("when_to_use"))
    do_not_use = _parse_bullets(metadata.get("do_not_use"))
    hints = _parse_bullets(metadata.get("hint"))
    example_usage = str(metadata.get("example_usage", "")).strip()

    lines = [
        "## Tool Guidance",
        "### Classification",
        f"- Domain: `{domain}`",
        f"- Type: `{tool_type}`",
        "",
        "### Operational Constraints",
        f"- Requires Auth: `{requires_auth}`",
        f"- Supports Pagination: `{supports_pagination}`",
        "",
        "### When To Use",
    ]

    if when_to_use:
        lines.extend([f"- {item}" for item in when_to_use])
    else:
        lines.append("- None specified.")

    lines.extend(["", "### When Not To Use"])
    if do_not_use:
        lines.extend([f"- {item}" for item in do_not_use])
    else:
        lines.append("- None specified.")

    if example_usage and example_usage.lower() != "none":
        lines.extend(["", "### Example", f"`{example_usage}`"])

    if hints and not (len(hints) == 1 and hints[0].lower() == "none"):
        lines.extend(["", "### Hints"])
        lines.extend([f"- {item}" for item in hints])

    return "\n".join(lines).strip()



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
            guidance_block = format_metadata_markdown(metadata)
            new_desc = f"{original_desc}\n\n{guidance_block}" if original_desc else guidance_block

            try:
                tool.description = new_desc
            except Exception:
                # Some tools may not allow mutation (StructuredTool edge cases)
                pass

        patched_tools.append(tool)

    return patched_tools

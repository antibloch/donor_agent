import json
import re
from typing import List, Dict, Sequence, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from tools.json_utils import (
    _safe_json_loads, 
    _compact_json, 
    _summarize_tool_output, 
    TRUNCATION_TOOL_LIMIT, 
    SENSITIVE_KEY_PATTERNS, 
    _sanitize_sensitive_data
)

def _redact_passwords(text: str) -> str:
    """
    Scrub passwords from plain text content 
    to prevent the LLM from reusing them in subsequent turns.
    """
    if not text:
        return ""
    # Matches patterns like "password is XYZ", "password: XYZ", "as XYZ"
    patterns = [
        r"(?i)(password\s*[:=]\s*)(\S+)",
        r"(?i)(password\s+is\s+)(\S+)",
        r"(?i)(password\s+as\s+)(\S+)"
    ]
    redacted = text
    for p in patterns:
        redacted = re.sub(p, r"\1[REDACTED]", redacted)
    
    # Simple check for single-word responses that are likely passwords
    words = text.strip().split()
    if len(words) == 1 and len(words[0]) > 3:
        # Avoid redacting common small words, but redact long single-word inputs in history
        if not words[0].lower() in ["yes", "no", "okay", "sure", "cancel"]:
            return "[REDACTED]"
    
    return redacted

def format_msg(m: BaseMessage) -> str:
    role = m.__class__.__name__
    content = (getattr(m, "content", "") or "").strip()
    
    # Apply redaction to raw content
    content = _redact_passwords(content)

    if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
        sanitized_calls = []
        for tc in getattr(m, "tool_calls"):
            new_tc = dict(tc)
            new_tc["args"] = _sanitize_sensitive_data(dict(tc.get("args") or {}))
            sanitized_calls.append(new_tc)
        content += "\n\n[tool_calls]\n" + json.dumps(sanitized_calls, indent=2, ensure_ascii=False)
    
    if getattr(m, "name", None):
        content = f"[tool={m.name}]\n{content}"
    return f"{role}:\n{content}\n"

def get_current_round_messages(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    msgs = list(messages or [])
    for i in range(len(msgs) - 1, -1, -1):
        if isinstance(msgs[i], HumanMessage):
            return msgs[i:]
    return msgs

def get_latest_tool_per_name(messages: Sequence[BaseMessage]) -> Dict[str, ToolMessage]:
    latest_any: Dict[str, ToolMessage] = {}
    latest_ok: Dict[str, ToolMessage] = {}
    for m in messages or []:
        if isinstance(m, ToolMessage):
            latest_any[m.name] = m
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is True:
                latest_ok[m.name] = m
    out = dict(latest_any)
    out.update(latest_ok)
    return out

def get_best_tool_message_by_call_id(messages: Sequence[BaseMessage]) -> Dict[str, ToolMessage]:
    latest_any: Dict[str, ToolMessage] = {}
    latest_ok: Dict[str, ToolMessage] = {}
    for m in messages or []:
        if isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if not tcid:
                continue
            latest_any[tcid] = m
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is True:
                latest_ok[tcid] = m
    out = dict(latest_any)
    out.update(latest_ok)
    return out

def _compact_err(payload: dict) -> str:
    try:
        s = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        s = str(payload)
    return s[:TRUNCATION_TOOL_LIMIT] + (" ...[truncated]" if len(s) > TRUNCATION_TOOL_LIMIT else "")

def detect_recent_tool_errors(messages: Sequence[BaseMessage], max_k: int = 8) -> List[Dict[str, Any]]:
    current_round = get_current_round_messages(messages)
    # If at least one repair cycle already happened in this round, only inspect
    # tool outputs generated after the latest gate repair note.
    # This makes each gate pass focus on failures from the immediately previous
    # repair execution instead of re-processing older, already-addressed errors.
    start_idx = 0
    for i, m in enumerate(current_round):
        if not isinstance(m, AIMessage):
            continue
        txt = (m.content or "").strip()
        if txt.startswith("System Note: Detected ") and "Attempting automatic repair." in txt:
            start_idx = i + 1

    scoped_msgs = current_round[start_idx:]
    tool_msgs = [m for m in scoped_msgs if isinstance(m, ToolMessage)]
    # First gate pass in a round: keep the historical window (last K).
    # Subsequent gate passes: inspect the full previous repair-cycle output.
    if start_idx == 0 and isinstance(max_k, int) and max_k > 0:
        tool_msgs = tool_msgs[-max_k:]

    error_markers = [
        "Traceback", "IndentationError", "SyntaxError", "NameError", "KeyError",
        "Incorrect", "Invalid", "TypeError", "ValueError", "Exception",
        "Error:", "ERROR", "invalid", "missing", "failed", "unexpected"
    ]

    errors: List[Dict[str, Any]] = []
    for m in reversed(tool_msgs):
        raw = (m.content or "").strip()
        payload = _safe_json_loads(raw)
        tcid = getattr(m, "tool_call_id", None)

        if isinstance(payload, dict):
            if payload.get("ok") is False:
                errors.append({"tool": m.name, "tool_call_id": tcid, "error": _compact_err(payload), "tool_message": raw})
                continue
            result = payload.get("result", None)
            if isinstance(result, str) and any(k in result for k in error_markers):
                errors.append({"tool": m.name, "tool_call_id": tcid, "error": result[:800], "tool_message": raw})
                continue
            err = payload.get("error", None)
            if isinstance(err, str) and any(k in err for k in error_markers):
                errors.append({"tool": m.name, "tool_call_id": tcid, "error": err[:800], "tool_message": raw})
                continue

        if any(k in raw for k in error_markers):
            errors.append({"tool": m.name, "tool_call_id": tcid, "error": raw[:800], "tool_message": raw})
            continue

    return errors

def detect_latest_tool_error(messages: Sequence[BaseMessage], max_k: int = 8) -> Dict[str, Any] | None:
    errors = detect_recent_tool_errors(messages, max_k=max_k)
    return errors[0] if errors else None

def _format_tool_calls_block(tool_calls: list) -> str:
    out = []
    for tc in tool_calls or []:
        tid = tc.get("id") or tc.get("tool_call_id") or ""
        name = tc.get("name") or ""
        args = _sanitize_sensitive_data(dict(tc.get("args") or {}))

        if name and name != "get_charity_stats" and "tool_name" not in args:
            args["tool_name"] = name

        out.append(f"TOOL_CALL[{name} id={tid}] args={_compact_json(args, max_chars=TRUNCATION_TOOL_LIMIT)}")
    return "\n".join(out)

def format_history_for_gate(messages: Sequence[BaseMessage]) -> str:
    """Provides history for the repair node (Gate)."""
    current_round = get_current_round_messages(messages)
    best_tool_by_call_id = get_best_tool_message_by_call_id(current_round)
    lines = []
    seen_call_ids: set[str] = set()
    for m in current_round:
        if isinstance(m, HumanMessage):
            # lines.append(f"USER: {_redact_passwords(m.content)}")
            lines.append(f"USER: {m.content}")
        elif isinstance(m, AIMessage):
            if (m.content or "").strip().startswith("System Note:"):
                continue
            if getattr(m, "tool_calls", None):
                lines.append(_format_tool_calls_block(m.tool_calls))
                for tc in m.tool_calls or []:
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        seen_call_ids.add(tcid)
                        lines.append(_summarize_tool_output(tm.name, tm.content))
            if (m.content or "").strip():
                lines.append(f"ASSISTANT: {_redact_passwords(m.content)}")
        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if tcid and tcid in seen_call_ids:
                continue
            lines.append(_summarize_tool_output(m.name, m.content))
    return "\n".join(lines) if lines else "(empty)"

def build_cached_tool_outputs(messages: Sequence[BaseMessage], max_chars: int = TRUNCATION_TOOL_LIMIT) -> str:
    current_round = get_current_round_messages(messages)
    last_by_tool: Dict[str, str] = {}
    for m in current_round:
        if isinstance(m, ToolMessage):
            last_by_tool[m.name] = m.content or ""
    if not last_by_tool:
        return "(none)"

    blocks = []
    for tool_name, content in last_by_tool.items():
        c = content.strip()
        try:
            payload = _safe_json_loads(c)
            if payload is not None:
                sanitized = _sanitize_sensitive_data(payload)
                c = _compact_json(sanitized, max_chars=max_chars)
            else:
                if len(c) > max_chars:
                    c = c[:max_chars] + " ...[truncated]"
        except Exception:
            if len(c) > max_chars:
                c = c[:max_chars] + " ...[truncated]"

        blocks.append(f"- {tool_name}: {c}")
    return "\n".join(blocks)

def format_history_for_planner(messages: Sequence[BaseMessage], *, drop_last_user: bool = True) -> str:
    msgs = list(messages) if messages else []
    if drop_last_user:
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], HumanMessage):
                msgs = msgs[:i]
                break
    
    latest_tools_by_name = get_latest_tool_per_name(msgs)
    best_tool_by_call_id = get_best_tool_message_by_call_id(msgs)
    lines = []
    seen_call_ids: set[str] = set()
    
    for m in msgs:
        if isinstance(m, HumanMessage):
            lines.append(f"USER: {_redact_passwords(m.content)}")
        elif isinstance(m, AIMessage):
            if (m.content or "").strip().startswith("System Note:"):
                continue
            if getattr(m, "tool_calls", None):
                visible_calls = []
                for tc in m.tool_calls or []:
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        payload = _safe_json_loads((tm.content or "").strip())
                        if isinstance(payload, dict) and payload.get("ok") is True:
                            visible_calls.append(tc)
                    else:
                        visible_calls.append(tc)
                if visible_calls:
                    lines.append(_format_tool_calls_block(visible_calls))
                    for tc in visible_calls:
                        tcid = tc.get("id") or tc.get("tool_call_id")
                        if tcid and tcid in best_tool_by_call_id:
                            tm = best_tool_by_call_id[tcid]
                            lines.append(_summarize_tool_output(tm.name, tm.content))
                            seen_call_ids.add(tcid)
            if (m.content or "").strip():
                lines.append(f"ASSISTANT: {_redact_passwords(m.content)}")
        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if tcid and tcid in seen_call_ids:
                continue
            if m is not latest_tools_by_name.get(m.name):
                continue
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is False:
                continue
            lines.append(_summarize_tool_output(m.name, m.content))
    return "\n".join(lines) if lines else "(no prior history)"

def format_history_for_responder(messages: Sequence[BaseMessage]) -> str:
    latest_tools_by_name = get_latest_tool_per_name(messages)
    best_tool_by_call_id = get_best_tool_message_by_call_id(messages)
    lines = []
    seen_call_ids: set[str] = set()
    
    for m in messages or []:
        if isinstance(m, HumanMessage):
            # lines.append(f"USER: {_redact_passwords(m.content)}")
            lines.append(f"USER: {m.content}")
        elif isinstance(m, AIMessage):
            if (m.content or "").strip().startswith("System Note:"):
                continue
            if getattr(m, "tool_calls", None):
                visible_calls = []
                for tc in m.tool_calls or []:
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        payload = _safe_json_loads((tm.content or "").strip())
                        if isinstance(payload, dict) and payload.get("ok") is True:
                            visible_calls.append(tc)
                    else:
                        visible_calls.append(tc)
                if visible_calls:
                    lines.append(_format_tool_calls_block(visible_calls))
                    for tc in visible_calls:
                        tcid = tc.get("id") or tc.get("tool_call_id")
                        if not tcid:
                            continue
                        seen_call_ids.add(tcid)
                        tm = best_tool_by_call_id.get(tcid)
                        if tm:
                            lines.append(_summarize_tool_output(tm.name, tm.content))
            if (m.content or "").strip():
                lines.append(f"ASSISTANT: {_redact_passwords(m.content)}")
        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if tcid and tcid in seen_call_ids:
                continue
            if m is not latest_tools_by_name.get(m.name):
                continue
            payload = _safe_json_loads((m.content or "").strip())
            if isinstance(payload, dict) and payload.get("ok") is False:
                continue
            lines.append(_summarize_tool_output(m.name, m.content))
    return "\n".join(lines) if lines else "(empty)"

import json
import re
import os
from typing import List, Dict, Sequence, Any
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage
from dotenv import load_dotenv



load_dotenv()

TRUNCATION_TOOL_LIMIT = int(os.getenv("TRUNCATION_TOOL_LIMIT"))

# Keys/patterns that should never leak into LLM history
SENSITIVE_KEY_PATTERNS = {
    "auth-token", "auth_token", "authorization", "token",
    "api_key", "apikey", "secret", "password", "credential",
    "private_key", "access_token", "refresh_token", "x-api-key", "bearer"
}

def _sanitize_sensitive_data(obj: Any) -> Any:
    """Recursively REMOVE sensitive keys entirely (do not keep "[REDACTED]")."""
    if isinstance(obj, dict):
        sanitized = {}
        for k, v in obj.items():
            key_lower = str(k).lower().replace("-", "_").replace(" ", "_")
            if any(pattern in key_lower for pattern in SENSITIVE_KEY_PATTERNS):
                continue  # ← KEY CHANGE: drop the whole key-value pair
            sanitized[k] = _sanitize_sensitive_data(v)
        return sanitized
    elif isinstance(obj, (list, tuple)):
        return [_sanitize_sensitive_data(item) for item in obj]
    else:
        return obj
    

def _extract_first_json_object(text: str) -> str:
    if not text:
        raise ValueError("Empty LLM output")
    cleaned = text.strip()
    m = re.search(r"```(?:json)?\s*({.*?})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        raise ValueError("No '{' found in LLM output")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : i + 1].strip()
    raise ValueError("Unbalanced JSON braces in LLM output")

def _parse_plan(raw: str) -> Dict:
    if not raw:
        return {"steps": [], "missing_args": []}
    try:
        json_str = _extract_first_json_object(raw)
        return json.loads(json_str)
    except:
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except:
            pass
    return {"steps": [], "missing_args": []}

def _safe_json_loads(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None

def _compact_json(obj: Any, max_chars: int = 900) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    if len(s) > max_chars:
        return s[:max_chars] + " ...[truncated]"
    return s

def _detect_semantic_error(payload: dict) -> str | None:
    """
    Detects semantic errors in tool outputs even when payload["ok"] == True.

    Returns a short error string if an error is detected, otherwise None.
    """
    if not isinstance(payload, dict):
        return None

    # Extract candidate text
    result = payload.get("result")
    error = payload.get("error")

    text = ""

    if isinstance(result, (str, bytes)):
        text = str(result)

    elif isinstance(result, list):
        try:
            text = json.dumps(result)
        except Exception:
            text = str(result)

    elif isinstance(result, dict):
        try:
            text = json.dumps(result)
        except Exception:
            text = str(result)

    if not text and error:
        text = str(error)

    text_lower = text.lower()

    ERROR_PATTERNS = [
        "request failed",
        "client error",
        "server error",
        "unauthorized",
        "forbidden",
        "invalid",
        "missing",
        "exception",
        "traceback",
        "error:",
        "<error>",
        "failed",
        "timeout",
        "not found",
        "dns",
        "name_not_resolved",
        "connection refused",
    ]

    for p in ERROR_PATTERNS:
        if p in text_lower:
            return text[:300]

    return None

def _extract_tool_error(payload: Any) -> Any | None:
    if isinstance(payload, dict):
        if payload.get("ok") is False:
            return payload.get("error") or payload.get("result") or payload

        if payload.get("success") is False:
            return (
                payload.get("error")
                or payload.get("message")
                or payload.get("result")
                or payload
            )

        message = payload.get("message")
        if isinstance(message, str):
            lower = message.lower()
            message_error_markers = (
                "request failed",
                "client error",
                "server error",
                "unauthorized",
                "forbidden",
                "invalid",
                "missing",
                "exception",
                "error:",
            )
            if any(marker in lower for marker in message_error_markers):
                return message

        nested_result = payload.get("result")
        if nested_result is not None:
            nested_err = _extract_tool_error(nested_result)
            if nested_err is not None:
                return nested_err

    if isinstance(payload, list):
        text_blocks = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                text_blocks.append(text.strip())
        if text_blocks:
            joined = "\n".join(text_blocks)
            lower = joined.lower()
            error_markers = (
                "<e>",
                "title: error",
                "failed to retrieve",
                "err_name_not_resolved",
                "traceback",
                "exception",
                "error:",
            )
            if any(marker in lower for marker in error_markers):
                return joined

    return None

def _summarize_tool_output(tool_name: str, tool_content: str) -> str:
    payload = _safe_json_loads(tool_content) if isinstance(tool_content, str) else None
    if not payload:
        return f"TOOL[{tool_name}] -> {tool_content}"

    err = _extract_tool_error(payload)
    if err is not None:
        return f"TOOL[{tool_name}] ERROR -> {_compact_json(err, max_chars=TRUNCATION_TOOL_LIMIT)}"

    result = payload.get("result", payload) if isinstance(payload, dict) else payload
    # === REDACT HERE TOO (in case backend echoes tokens) ===
    result = _sanitize_sensitive_data(result)
    # =======================================================
    return f"TOOL[{tool_name}] -> {_compact_json(result, max_chars=TRUNCATION_TOOL_LIMIT)}"




#------------------------------------------------------------------------------------------------------------


def extract_latest_requested_missing_args(messages: Sequence[BaseMessage]) -> List[str]:
    pattern = re.compile(r"CURRENT_MISSING_ARGS_JSON=(\[[^\n]*\])")

    for m in reversed(messages or []):
        if not isinstance(m, AIMessage):
            continue

        content = (m.content or "").strip()
        if "CURRENT_MISSING_ARGS_JSON=" not in content:
            continue

        match = pattern.search(content)
        if not match:
            continue

        try:
            parsed = json.loads(match.group(1))
        except Exception:
            continue

        if not isinstance(parsed, list):
            continue

        out: List[str] = []
        for item in parsed:
            if isinstance(item, str):
                value = item.strip()
                if value and value not in out:
                    out.append(value)
        return out

    return []


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
    for m in messages or []:
        if isinstance(m, ToolMessage):
            latest_any[m.name] = m
    return latest_any

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

def get_superseded_failed_call_ids(messages: Sequence[BaseMessage]) -> set[str]:
    tool_name_by_call_id: Dict[str, str] = {}
    first_tool_index_by_call_id: Dict[str, int] = {}
    failed_tool_index_by_call_id: Dict[str, int] = {}
    latest_ok_index_by_tool: Dict[str, int] = {}

    for idx, m in enumerate(messages or []):
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls or []:
                tcid = tc.get("id") or tc.get("tool_call_id")
                name = tc.get("name") or ""
                if not tcid or not name:
                    continue
                tool_name_by_call_id[tcid] = name
                first_tool_index_by_call_id.setdefault(tcid, idx)

        if not isinstance(m, ToolMessage):
            continue

        tcid = getattr(m, "tool_call_id", None)
        name = m.name or ""
        payload = _safe_json_loads((m.content or "").strip())
        is_ok = isinstance(payload, dict) and payload.get("ok") is True and _extract_tool_error(payload) is None

        if is_ok and name:
            latest_ok_index_by_tool[name] = idx
            continue

        if tcid:
            failed_tool_index_by_call_id[tcid] = idx

    superseded: set[str] = set()
    for tcid, fail_idx in failed_tool_index_by_call_id.items():
        tool_name = tool_name_by_call_id.get(tcid)
        if not tool_name:
            continue
        ok_idx = latest_ok_index_by_tool.get(tool_name)
        if ok_idx is not None and ok_idx > fail_idx:
            superseded.add(tcid)

    return superseded

def _compact_err(payload: dict) -> str:
    try:
        s = json.dumps(payload, ensure_ascii=False, default=str)
    except Exception:
        s = str(payload)
    return s[:TRUNCATION_TOOL_LIMIT] + (" ...[truncated]" if len(s) > TRUNCATION_TOOL_LIMIT else "")

def detect_recent_tool_errors(messages: Sequence[BaseMessage], max_k: int = 8) -> List[Dict[str, Any]]:
    current_round = get_current_round_messages(messages)
    # After a repair attempt in the current round, only inspect tool outputs
    # produced since the latest repair note so old failures do not get retried.
    start_idx = 0
    for i, m in enumerate(current_round):
        if not isinstance(m, AIMessage):
            continue
        txt = (m.content or "").strip()
        if txt.startswith("System Note: Detected ") and "Attempting automatic repair." in txt:
            start_idx = i + 1

    scoped_msgs = current_round[start_idx:]
    tool_msgs = [m for m in scoped_msgs if isinstance(m, ToolMessage)]
    if start_idx == 0 and isinstance(max_k, int) and max_k > 0:
        tool_msgs = tool_msgs[-max_k:]

    error_markers = [
        "Traceback", "IndentationError", "SyntaxError", "NameError", "KeyError",
        "Incorrect", "Invalid", "TypeError", "ValueError", "Exception",
        "Error:", "ERROR", "invalid", "missing", "failed", "unexpected"
    ]
    marker_lc = [m.lower() for m in error_markers]

    def _text_has_error_markers(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except Exception:
                text = str(value)
        return any(marker in text.lower() for marker in marker_lc)

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
            if _text_has_error_markers(result):
                errors.append({
                    "tool": m.name,
                    "tool_call_id": tcid,
                    "error": _compact_json(result, max_chars=800),
                    "tool_message": raw,
                })
                continue
            err = payload.get("error", None)
            if _text_has_error_markers(err):
                errors.append({
                    "tool": m.name,
                    "tool_call_id": tcid,
                    "error": _compact_json(err, max_chars=800),
                    "tool_message": raw,
                })
                continue

        if _text_has_error_markers(raw):
            errors.append({"tool": m.name, "tool_call_id": tcid, "error": raw[:800], "tool_message": raw})
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

def _format_planner_tool_calls_block(tool_calls: list) -> str:
    out = []
    for tc in tool_calls or []:
        tid = tc.get("id") or tc.get("tool_call_id") or ""
        name = tc.get("name") or ""
        args = _sanitize_sensitive_data(dict(tc.get("args") or {}))

        if name and name != "get_charity_stats" and "tool_name" not in args:
            args["tool_name"] = name

        out.append(f"CACHED_TOOL_CALL[{name} id={tid}] args={_compact_json(args, max_chars=TRUNCATION_TOOL_LIMIT)}")
    return "\n".join(out)

def _format_planner_tool_output(tool_name: str, tool_content: str) -> str:
    summary = _summarize_tool_output(tool_name, tool_content)
    if summary.startswith(f"TOOL[{tool_name}] -> "):
        return summary.replace(f"TOOL[{tool_name}] -> ", f"CACHED_SUCCESS[{tool_name}] -> ", 1)
    if summary.startswith(f"TOOL[{tool_name}] ERROR -> "):
        return summary.replace(f"TOOL[{tool_name}] ERROR -> ", f"CACHED_ERROR[{tool_name}] -> ", 1)
    return summary

def _format_cached_tool_output(tool_name: str, tool_content: str) -> str:
    return _format_planner_tool_output(tool_name, tool_content)

def _format_synthetic_cached_tool_call(tool_name: str, tool_call_id: str | None = None) -> str:
    tid = tool_call_id or ""
    return f'CACHED_TOOL_CALL[{tool_name} id={tid}] args={{"tool_name": "{tool_name}", "source": "prior_successful_tool_message"}}'

def _looks_like_final_gate_step_message(text: str) -> bool:
    return isinstance(text, str) and text.strip().startswith("FINAL_AGENT_STEP[gate] -> ")

def _history_already_has_final_gate_step(messages: Sequence[BaseMessage]) -> bool:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage) and _looks_like_final_gate_step_message((m.content or "").strip()):
            return True
    return False

def _truncate_last_gate_output(output: Any, max_chars: int | None = None) -> Any:
    """
    Truncate only the `output` field of the persisted final gate step message,
    so the history keeps the final gate action but stays compact.
    """
    limit = max_chars or int(os.getenv("TRUNC_LAST_GATE", str(TRUNCATION_TOOL_LIMIT)))
    if output is None:
        return None

    if isinstance(output, (dict, list)):
        try:
            s = json.dumps(_sanitize_sensitive_data(output), ensure_ascii=False, default=str)
        except Exception:
            s = str(output)
    else:
        s = str(output)

    if len(s) > limit:
        s = s[:limit] + " ...[truncated]"
    return s


def _is_final_agent_step_text(text: str) -> bool:
    return isinstance(text, str) and text.strip().startswith("FINAL_AGENT_STEP[gate] -> ")

def _format_last_agentic_step(last_agentic_step: Dict[str, Any] | None) -> str:
    if not isinstance(last_agentic_step, dict) or not last_agentic_step:
        return ""

    payload = {
        "react_step": last_agentic_step.get("react_step"),
        "target_error_id": last_agentic_step.get("target_error_id"),
        "tool": last_agentic_step.get("tool"),
        "args": _sanitize_sensitive_data(dict(last_agentic_step.get("args") or {})),
        "ok": last_agentic_step.get("ok"),
        "reason": last_agentic_step.get("reason", ""),
        "missing_args": list(last_agentic_step.get("missing_args") or []),
        "done": last_agentic_step.get("done"),
        "output": last_agentic_step.get("output"),
    }
    return f"FINAL_AGENT_STEP[gate] -> {_compact_json(payload, max_chars=TRUNCATION_TOOL_LIMIT)}"

def _inject_before_latest_assistant(lines: List[str], injected_line: str) -> List[str]:
    """
    Inject a line just before the last ASSISTANT: entry in a lines list.

    Used by format_history_for_planner, where drop_last_user=True has already
    removed the current user message, making the last ASSISTANT: line the correct
    temporal anchor — the gate step happened after the prior assistant response
    and before the next planning cycle.

    Falls back to appending if no ASSISTANT: line is found (e.g. first round).
    """
    if not injected_line:
        return lines

    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("ASSISTANT: "):
            return lines[:i] + [injected_line] + lines[i:]

    return lines + [injected_line]

def _inject_before_latest_user(lines: List[str], injected_line: str) -> List[str]:
    """
    Inject a line just before the last USER: entry in a lines list.

    Used by format_history_for_responder, where the current user message is still
    present in the history. Placing the gate step here gives the responder the
    correct temporal ordering:

        ... prior history ...
        FINAL_AGENT_STEP[gate] -> {...}   ← gate executed this just now
        USER: <current request>           ← now produce the final answer

    Falls back to appending if no USER: line is found (should not occur in normal
    operation, but handled defensively).
    """
    if not injected_line:
        return lines

    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("USER: "):
            return lines[:i] + [injected_line] + lines[i:]

    # Defensive fallback: append at end if no USER: line exists
    return lines + [injected_line]

def format_history_for_gate(messages: Sequence[BaseMessage]) -> str:
    """Provides history for the repair node (Gate)."""
    best_tool_by_call_id = get_best_tool_message_by_call_id(messages)
    lines = []
    seen_call_ids: set[str] = set()

    for m in messages or []:
        if isinstance(m, HumanMessage):
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

            content = (m.content or "").strip()
            if content:
                if _is_final_agent_step_text(content):
                    lines.append(content)
                else:
                    lines.append(f"ASSISTANT: {_redact_passwords(content)}")

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

def format_history_for_planner(
    messages: Sequence[BaseMessage],
    *,
    drop_last_user: bool = True,
    last_agentic_step: Dict[str, Any] | None = None,
) -> str:
    msgs = list(messages) if messages else []
    if drop_last_user:
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], HumanMessage):
                msgs = msgs[:i]
                break
    
    latest_tools_by_name = get_latest_tool_per_name(msgs)
    best_tool_by_call_id = get_best_tool_message_by_call_id(msgs)
    superseded_failed_call_ids = get_superseded_failed_call_ids(msgs)
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
                    if tcid and tcid in superseded_failed_call_ids:
                        continue
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        payload = _safe_json_loads((tm.content or "").strip())
                        if payload is not None and _extract_tool_error(payload) is None:
                            visible_calls.append(tc)
                    else:
                        visible_calls.append(tc)
                if visible_calls:
                    lines.append(_format_planner_tool_calls_block(visible_calls))
                    for tc in visible_calls:
                        tcid = tc.get("id") or tc.get("tool_call_id")
                        if tcid and tcid in best_tool_by_call_id:
                            tm = best_tool_by_call_id[tcid]
                            lines.append(_format_planner_tool_output(tm.name, tm.content))
                            seen_call_ids.add(tcid)
            content = (m.content or "").strip()
            if content:
                if _is_final_agent_step_text(content):
                    lines.append(content)
                else:
                    lines.append(f"ASSISTANT: {_redact_passwords(content)}")
        elif isinstance(m, ToolMessage):
            tcid = getattr(m, "tool_call_id", None)
            if tcid and tcid in seen_call_ids:
                continue
            if m is not latest_tools_by_name.get(m.name):
                continue
            payload = _safe_json_loads((m.content or "").strip())
            if payload is not None and _extract_tool_error(payload) is not None:
                continue
            lines.append(_format_synthetic_cached_tool_call(m.name, tcid))
            lines.append(_format_cached_tool_output(m.name, m.content))

    # Fallback injection only when the current gate step has not yet been
    # persisted as a normal AIMessage in history.
    if not _history_already_has_final_gate_step(msgs):
        lines = _inject_before_latest_assistant(
            lines,
            _format_last_agentic_step(last_agentic_step),
        )
    return "\n".join(lines) if lines else "(no prior history)"

def format_history_for_responder(
    messages: Sequence[BaseMessage],
    *,
    last_agentic_step: Dict[str, Any] | None = None,
) -> str:
    current_round = get_current_round_messages(messages)
    current_round_ids = {id(m) for m in current_round}
    current_round_failed_tools: set[str] = set()
    for m in current_round:
        if not isinstance(m, ToolMessage):
            continue
        payload = _safe_json_loads((m.content or "").strip())
        if payload is not None and _extract_tool_error(payload) is not None and m.name:
            current_round_failed_tools.add(m.name)

    latest_tools_by_name = get_latest_tool_per_name(messages)
    best_tool_by_call_id = get_best_tool_message_by_call_id(messages)
    superseded_failed_call_ids = get_superseded_failed_call_ids(messages)
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
                    name = tc.get("name") or ""
                    if id(m) not in current_round_ids and name in current_round_failed_tools:
                        continue
                    tcid = tc.get("id") or tc.get("tool_call_id")
                    if tcid and tcid in superseded_failed_call_ids:
                        continue
                    if tcid and tcid in best_tool_by_call_id:
                        tm = best_tool_by_call_id[tcid]
                        payload = _safe_json_loads((tm.content or "").strip())
                        if payload is not None and _extract_tool_error(payload) is None:
                            visible_calls.append(tc)
                    else:
                        visible_calls.append(tc)
                if visible_calls:
                    lines.append(_format_planner_tool_calls_block(visible_calls))
                    for tc in visible_calls:
                        tcid = tc.get("id") or tc.get("tool_call_id")
                        if not tcid:
                            continue
                        seen_call_ids.add(tcid)
                        tm = best_tool_by_call_id.get(tcid)
                        if tm:
                            lines.append(_format_cached_tool_output(tm.name, tm.content))
            content = (m.content or "").strip()
            if content:
                if _is_final_agent_step_text(content):
                    lines.append(content)
                else:
                    lines.append(f"ASSISTANT: {_redact_passwords(content)}")
        elif isinstance(m, ToolMessage):
            if id(m) not in current_round_ids and m.name in current_round_failed_tools:
                continue
            tcid = getattr(m, "tool_call_id", None)
            if tcid and tcid in seen_call_ids:
                continue
            if m is not latest_tools_by_name.get(m.name):
                continue
            payload = _safe_json_loads((m.content or "").strip())
            if payload is not None and _extract_tool_error(payload) is not None:
                continue
            lines.append(_format_synthetic_cached_tool_call(m.name, tcid))
            lines.append(_format_cached_tool_output(m.name, m.content))

    # Fallback injection only when the current gate step has not yet been
    # persisted as a normal AIMessage in history.
    if not _history_already_has_final_gate_step(messages):
        lines = _inject_before_latest_user(
            lines,
            _format_last_agentic_step(last_agentic_step),
        )
    return "\n".join(lines) if lines else "(empty)"
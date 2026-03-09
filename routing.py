def route_after_validator(state: dict) -> str:
    plan = state.get("plan", {}) or {}
    steps = plan.get("steps", []) or []
    return "executor" if steps else "responder"


def route_after_gate(state: dict) -> str:
    return "responder"
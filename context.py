from contextvars import ContextVar

auth_token_ctx: ContextVar[str | None] = ContextVar("auth_token", default=None)
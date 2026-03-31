# POST /chat
#   - Request body: { "message": "show me active auctions" }
#   - Response: { "response": "agent reply here", "requires_password": true/false }

# GET /health
#   - Response: { "status": "ok" }

import os
import asyncio
import time
import requests
from typing import List, Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

import dotenv
dotenv.load_dotenv()

# ── Import everything from main_agent ─────────────────────
from main_agent import build_graph

# ── ContextVar for auth ───────────────────────────────────
from context import auth_token_ctx

# ── OAuth2 Scheme ─────────────────────────────────────────
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# ── NEW: Auth Configuration ──
VERIFY_URL = "https://giverr-api.verior.co/api/v3/agent/verify-token"
verified_sessions: Dict[str, float] = {}  # Stores {token: timestamp}
AUTH_CACHE_TTL = 600  # 10 minutes (600 seconds)


# ── Global state ──────────────────────────────────────────
graph = None

# 🔥 Per-user memory
chat_sessions: Dict[str, List[BaseMessage]] = {}


# ── Startup ───────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    graph = await build_graph()
    yield


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="Charity Agent API",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    requires_password: bool


# ── Helpers ───────────────────────────────────────────────
def _extract_response(messages: List[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = (msg.content or "").strip()
            if content and "System Note:" not in content:
                return content
    return ""


def get_user_memory(token: str) -> List[BaseMessage]:
    if token not in chat_sessions:
        chat_sessions[token] = []
    return chat_sessions[token]

async def verify_token(token: str = Depends(oauth2_scheme)):
    """
    Validates token with a 5-minute local cache for minimal latency.
    """
    now = time.time()
    
    # 1. LATENCY CHECK: Is it in our local "Fast Lane"?
    if token in verified_sessions:
        if (now - verified_sessions[token]) < AUTH_CACHE_TTL:
            return token

    # 2. SECURITY CHECK: Cache expired or missing, call Verior API
    try:
        response = requests.get(
            VERIFY_URL,
            headers={"Authorization": f"Bearer {token}"},
            timeout=3.0 # Don't let a slow API hang your agent
        )
        data = response.json()

        if response.status_code == 200 and data.get("success"):
            verified_sessions[token] = now # Update local cache
            return token
        
        # If Verior rejects the token
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=data.get("message", "Invalid or expired token"),
            headers={"WWW-Authenticate": "Bearer"},
        )
    except requests.exceptions.RequestException:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unreachable."
        )



# ── Routes ────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, token: str = Depends(verify_token)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Per-user memory
    chat_memory = get_user_memory(token)

    # Inject token into ContextVar
    token_ctx = auth_token_ctx.set(token)

    try:
        # Add user message
        chat_memory.append(HumanMessage(content=request.message))

        # Run agent
        seen_ids = set()

        async for step in graph.astream(
            {"messages": chat_memory, "repair_attempts": 0},
            stream_mode="updates"
        ):
            for node_name, node_output in step.items():
                if not node_output:
                    continue

                if "messages" in node_output:
                    for msg in node_output["messages"]:
                        msg_id = getattr(msg, "id", None)

                        if msg_id and msg_id in seen_ids:
                            continue

                        if msg_id:
                            seen_ids.add(msg_id)

                        chat_memory.append(msg)

        # Extract response
        response_text = _extract_response(chat_memory)

        return ChatResponse(
            response=response_text,
            requires_password=False
        )

    finally:
        # Clean context (VERY IMPORTANT)
        auth_token_ctx.reset(token_ctx)


@app.post("/reset")
def reset(token: str = Depends(verify_token)):
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if token in chat_sessions:
        chat_sessions[token] = []

    return {"status": "session reset"}
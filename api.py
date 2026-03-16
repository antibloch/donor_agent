# POST /chat
#   - Request body: { "message": "show me active auctions", "session_id": "abc123" }
#   - Response: { "response": "agent reply here", "requires_password": true/false }

# GET /health
#   - Response: { "status": "ok" }

import os
import asyncio
from typing import List
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

import dotenv
dotenv.load_dotenv()

# ── Import everything from main_agent ─────────────────────
from main_agent import build_graph, _should_wrap_as_password


# ── Global state (single user, single session) ────────────
graph = None
chat_memory: List[BaseMessage] = []


# ── Startup: build graph once ─────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global graph
    graph = await build_graph()
    yield


# ── App ───────────────────────────────────────────────────
app = FastAPI(
    title="Charity Agent API",
    version="1.0.0",
    lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Request / Response models ─────────────────────────────
class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    requires_password: bool


# ── Helper: extract final agent text response ─────────────
def _extract_response(messages: List[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage):
            content = (msg.content or "").strip()
            if content and "System Note:" not in content:
                return content
    return ""


# ── Routes ────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    global chat_memory

    # Wrap as password if agent is expecting one
    outgoing = request.message
    if _should_wrap_as_password(chat_memory):
        outgoing = f"Password: {request.message}"

    chat_memory.append(HumanMessage(content=outgoing))

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

    # Detect if agent is now asking for password
    requires_password = _should_wrap_as_password(chat_memory)

    return ChatResponse(
        response=response_text,
        requires_password=requires_password
    )


@app.post("/reset")
def reset():
    global chat_memory
    chat_memory = []
    return {"status": "session reset"}


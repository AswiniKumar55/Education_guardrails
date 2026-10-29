"""
EduBot FastAPI application — REST + simple HTML chat UI
"""

import logging
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from edubot.agent.agent import run_agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EduBot — Secure Educational AI Agent",
    description="An AI-powered learning assistant with built-in guardrails for student safety.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# In-memory session store  {session_id: [{"role":…,"content":…}]}
_sessions: Dict[str, List[Dict]] = {}


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000, description="Student's question or message")
    session_id: Optional[str] = Field(None, description="Conversation session ID (omit to start a new session)")


class ChatResponse(BaseModel):
    session_id: str
    response: str
    blocked: bool
    block_reason: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the embedded chat UI."""
    with open("edubot/templates/chat.html", "r", encoding="utf-8") as fh:
        return HTMLResponse(content=fh.read())


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Main chat endpoint with full guardrail pipeline."""
    session_id = request.session_id or str(uuid.uuid4())
    history = _sessions.setdefault(session_id, [])

    result = run_agent(user_input=request.message, conversation_history=history)

    # Persist turn in history only when not blocked
    if not result["blocked"]:
        history.append({"role": "user", "content": request.message})
        history.append({"role": "assistant", "content": result["response"]})

    return ChatResponse(
        session_id=session_id,
        response=result["response"],
        blocked=result["blocked"],
        block_reason=result.get("block_reason", ""),
    )


@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a conversation session."""
    _sessions.pop(session_id, None)
    return {"status": "cleared", "session_id": session_id}


@app.get("/health")
async def health():
    return {"status": "ok", "service": "EduBot"}

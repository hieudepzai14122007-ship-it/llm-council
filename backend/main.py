"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Literal
import uuid
import json
import asyncio

from . import storage, usage
from .council import run_turn, run_full_council, generate_conversation_title

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

Mode = Literal["auto", "fast", "solo", "council"]


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str
    mode: Mode = "auto"  # "auto" lets Laya decide; anything else overrides it


class RerunRequest(BaseModel):
    """Request to answer the last question again on a different route."""
    mode: Mode


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/usage")
async def get_usage():
    """Totals per route and estimated savings from Laya's routing."""
    return usage.summary()


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _save_answer(conversation_id: str, result: Dict[str, Any]):
    storage.add_assistant_message(
        conversation_id,
        result["stage1"],
        result["stage2"],
        result["stage3"],
        result["laya"],
        result["usage"],
        {k: v for k, v in result["metadata"].items() if k != "laya"},
    )


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and answer it (Laya gate, then fast / solo / council).
    Returns the complete response with all stages.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    history = conversation["messages"]
    storage.add_user_message(conversation_id, request.content)

    if not history:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    result = await run_full_council(request.content, history, request.mode)
    _save_answer(conversation_id, result)
    return result


def _stream(conversation_id: str, content: str, history: List[Dict[str, Any]], mode: str, make_title: bool):
    """Stream one turn as Server-Sent Events and save the answer at the end."""

    async def event_generator():
        try:
            # Start title generation in parallel (don't await yet)
            title_task = asyncio.create_task(generate_conversation_title(content)) if make_title else None

            result = None
            async for event_type, payload in run_turn(content, history, mode):
                if event_type == "turn_result":
                    result = payload
                else:
                    yield f"data: {json.dumps({'type': event_type, **payload})}\n\n"

            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            _save_answer(conversation_id, result)
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the answer as each step completes.
    Earlier messages in the conversation are passed along, so follow-ups work.
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    history = conversation["messages"]
    storage.add_user_message(conversation_id, request.content)
    return _stream(conversation_id, request.content, history, request.mode, make_title=not history)


@app.post("/api/conversations/{conversation_id}/rerun/stream")
async def rerun_stream(conversation_id: str, request: RerunRequest):
    """
    Replace the last answer with a new one on a different route
    ("Ask the council instead", "Just answer quickly", ...).
    """
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    question = storage.remove_last_answer(conversation_id)
    if question is None:
        raise HTTPException(status_code=400, detail="The conversation doesn't end with an answer")

    history = storage.get_conversation(conversation_id)["messages"][:-1]  # before the question
    return _stream(conversation_id, question, history, request.mode, make_title=False)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)

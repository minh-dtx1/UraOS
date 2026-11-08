"""Máy chủ web của Ura: giao diện HUD + API streaming.

Chạy:  python server.py   rồi mở http://localhost:8000
"""
from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ura import tools
from ura.brain import Conversation, to_json_line
from ura.config import ROOT, settings

app = FastAPI(title="Ura")
sessions: dict[str, Conversation] = {}


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/info")
def info():
    return {"name": "Ura", "user": settings.user_name, "model": settings.model}


@app.post("/api/chat")
def chat(body: ChatIn):
    sid = body.session_id or uuid.uuid4().hex
    convo = sessions.get(sid)
    if convo is None:
        convo = sessions[sid] = Conversation()

    def gen():
        yield to_json_line({"type": "session", "session_id": sid}) + "\n"
        for event in convo.ask(body.message.strip()):
            yield to_json_line(event) + "\n"

    # NDJSON: mỗi dòng là một sự kiện JSON
    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/reset")
def reset(body: ChatIn):
    sessions.pop(body.session_id or "", None)
    return {"ok": True}


@app.get("/api/reminders")
def reminders():
    return {"due": tools.due_reminders()}


@app.get("/api/tasks")
def tasks():
    return tools.list_tasks()


app.mount("/static", StaticFiles(directory=ROOT / "web"), name="static")

if __name__ == "__main__":
    import uvicorn

    print(f"Ura đang khởi động tại http://localhost:{settings.port}")
    uvicorn.run(app, host="0.0.0.0", port=settings.port)

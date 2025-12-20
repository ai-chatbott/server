from fastapi import FastAPI, Depends , Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from google import genai
from db import engine , get_db
from models import Base , ChatMessage , ChatSession
from sqlalchemy.orm import Session
from typing import List, Dict
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

Base.metadata.create_all(bind=engine)


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing key")

client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    session_id: str
    text: str
    name: str | None = None



def load_business_context() -> str:
    path = BASE_DIR / "business.txt"
    if not path.exists():
        return "Business info is not available."
    return path.read_text(encoding="utf-8")


@app.post("/chat")
def chat(body: ChatRequest, db: Session = Depends(get_db)):
    # 1) load/create session
    s = db.get(ChatSession, body.session_id)
    if not s:
        s = ChatSession(id=body.session_id, name=body.name)
        db.add(s)
        db.commit()
    else:
        if body.name and not s.name:
            s.name = body.name
            db.commit()

    # 2) save user message
    db.add(ChatMessage(session_id=s.id, role="user", content=body.text))
    db.commit()

    # 3) fetch last messages
    last_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == s.id)
        .order_by(ChatMessage.id.desc())
        .limit(12)
        .all()
    )[::-1]

    # 4) build prompt
    context = load_business_context()

    system_instruction = (
        "You are a professional front-desk assistant for Beauty Shohre Studio.\n"
        "Speak naturally and briefly (2–4 sentences max).\n"
        "Do NOT greet the user repeatedly.\n"
        "Address the user by their name when appropriate.\n"
        "Be friendly, confident, and non-repetitive.\n"
        "Use ONLY the information provided.\n\n"

        "BOOKING RULES:\n"
        "- To book a consultation, clients must call or text Shohre at 778-513-9006.\n"
        "- There is no consultation option in online booking.\n"
        "- Online booking is available.\n"
        "- Do not guess prices or availability.\n\n"

        "LINKING RULES:\n"
        "- When suggesting online booking, say: book online.\n"
        "- When suggesting phone contact, say: call or text Shohre.\n"
        "- Do NOT include raw URLs.\n"
        "- Do NOT format links.\n\n"

        "STYLE-INSPIRATION RULE:\n"
        "- If unsure about color/cut, suggest: website gallery or Instagram.\n"
        "- Suggest saving 2–3 photos and showing Shohre in consultation.\n"
        "- Do NOT include URLs.\n\n"

        f"BUSINESS INFO:\n{context}\n"
    )

    user_name = s.name or "there"
    convo_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in last_msgs])

    prompt = (
        f"{system_instruction}\n"
        f"User name: {user_name}\n\n"
        f"CONVERSATION:\n{convo_text}\n\nASSISTANT:"
    )

    # 5) call gemini
    reply = ""  # ✅ real assignment

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
        )
        reply = (response.text or "").strip()
    except Exception:
        reply = "Sorry! Something went wrong on our side. Please try again."

    if not reply:
        reply = "Sorry! I couldn't generate a response. Please try again."

    # 6) save assistant reply
    db.add(ChatMessage(session_id=s.id, role="assistant", content=reply))
    db.commit()

    # 7) return
    return {"reply": reply}




@app.get("/history")
def history(session_id: str = Query(...), db: Session = Depends(get_db)):
    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return {
        "messages": [{"role": m.role, "text": m.content} for m in msgs]
    }

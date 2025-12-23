from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from pathlib import Path
from google import genai
from sqlalchemy.orm import Session

from db import engine, get_db
from models import Base, ChatMessage, ChatSession
from dotenv import load_dotenv
import asyncio

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

# ---------- Setup ----------
BASE_DIR = Path(__file__).resolve().parent
Base.metadata.create_all(bind=engine)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing key")

client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://client-sand-kappa.vercel.app",  # ✅ no trailing slash
        "https://beautyshohrestudio.ca",
        "https://www.beautyshohrestudio.ca",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Models ----------
class ChatRequest(BaseModel):
    session_id: str
    text: str
    biz_id: str
    name: str | None = None

# ---------- Helpers ----------
def sanitize_biz_id(biz_id: str) -> str:
    return "".join(c for c in (biz_id or "") if c.isalnum() or c in ("-", "_")).lower() or "default"

def load_business_context(biz_id: str) -> str:
    safe = sanitize_biz_id(biz_id)
    folder = BASE_DIR / "businesses"
    folder.mkdir(exist_ok=True)

    path = folder / f"{safe}.txt"
    if not path.exists():
        path = folder / "default.txt"

    if not path.exists():
        return "Business info is not available."
    return path.read_text(encoding="utf-8")

    BUSINESS_CONTEXT_CACHE = {}
    SYSTEM_PROMPT_CACHE = {}

def get_system_prompt(biz_id, context):
    if biz_id in SYSTEM_PROMPT_CACHE:
        return SYSTEM_PROMPT_CACHE[biz_id]

    prompt = (
        "You are a professional front-desk assistant for the business described below.\n"
        "Speak naturally and briefly (2–4 sentences max).\n"
        "Do NOT greet the user repeatedly.\n"
        "Address the user by their name when appropriate.\n"
        "Be friendly, confident, and non-repetitive.\n"
        "Use ONLY the information provided.\n"
        "If you don't know, say so and suggest contacting the business.\n\n"
        "IMPORTANT:\n"
        "- Do not guess prices, availability, or policies not listed.\n"
        "- Keep answers practical and action-oriented.\n\n"
        f"BUSINESS INFO:\n{context}\n"
    )
    SYSTEM_PROMPT_CACHE[biz_id] = prompt
    return prompt

# Optional: business metadata for UI labels/links (keep minimal; not required for chat)
@app.get("/business/{biz_id}")
def business(biz_id: str):
    safe = sanitize_biz_id(biz_id)

    data = {
        "beautyshohre": {
            "businessName": "Beauty Shohre Studio",
            "assistantName": "Shohre",
            "phone": "778-513-9006",
            "links": {
                "booking": "https://beautyshohrestudio.ca/booking",
                "gallery": "https://beautyshohrestudio.ca/gallery",
                "instagram": "https://www.instagram.com/beautyshohre_studio",
            },
        },
        "default": {
            "businessName": "Our Business",
            "assistantName": "Assistant",
            "phone": "",
            "links": {},
        },
    }

    return data.get(safe, data["default"])

# ---------- Routes ----------
@app.post("/chat")
async def chat(body: ChatRequest, db: Session = Depends(get_db)):
    safe_biz = sanitize_biz_id(body.biz_id)
    effective_session_id = f"{safe_biz}:{body.session_id}"

    # 1) load/create session
    s = db.get(ChatSession, effective_session_id)
    if not s:
        s = ChatSession(id=effective_session_id, name=body.name)
        db.add(s)
        db.commit()
    else:
        if body.name and not s.name:
            s.name = body.name
            db.commit()

    # 2) save user message
    db.add(ChatMessage(session_id=effective_session_id, role="user", content=body.text))
    db.commit()

    # 3) fetch last messages
    last_msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == effective_session_id)
        .order_by(ChatMessage.id.desc())
        .limit(6)
        .all()
    )[::-1]

    # 4) build prompt
    context = BUSINESS_CONTEXT_CACHE.get(safe_biz)
    if not context:
        context = load_business_context(safe_biz)
        BUSINESS_CONTEXT_CACHE[safe_biz] = context

    user_name = s.name or "there"
    convo_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in last_msgs])

    # ✅ Universal prompt (still structured like yours)


    # system_instruction = (
    #     "You are a professional front-desk assistant for the business described below.\n"
    #     "Speak naturally and briefly (2–4 sentences max).\n"
    #     "Do NOT greet the user repeatedly.\n"
    #     "Address the user by their name when appropriate.\n"
    #     "Be friendly, confident, and non-repetitive.\n"
    #     "Use ONLY the information provided.\n"
    #     "If you don't know, say so and suggest contacting the business.\n\n"
    #     "IMPORTANT:\n"
    #     "- Do not guess prices, availability, or policies not listed.\n"
    #     "- Keep answers practical and action-oriented.\n\n"
    #     f"BUSINESS INFO:\n{context}\n"
    # )

    # prompt = (
    #     f"{system_instruction}\n"
    #     f"User name: {user_name}\n\n"
    #     f"CONVERSATION:\n{convo_text}\n\nASSISTANT:"
    # )

    # 5) call gemini
    try:
        response = await asyncio.to_thread(
        client.models.generate_content,
        model="gemini-2.5-flash",
        contents=prompt,
    )
        reply = (response.text or "").strip()
    except Exception:
        reply = "Sorry! Something went wrong on our side. Please try again."

    if not reply:
        reply = "Sorry! I couldn't generate a response. Please try again."

    # 6) return immediately
    response_payload = {"reply": reply}

    # 7) save assistant reply AFTER
    try:
        db.add(ChatMessage(session_id=effective_session_id, role="assistant", content=reply))
        db.commit()
    except Exception:
        db.rollback()

    return response_payload


@app.get("/history")
def history(
    session_id: str = Query(...),
    biz_id: str = Query("default"),
    db: Session = Depends(get_db),
):
    safe_biz = sanitize_biz_id(biz_id)
    effective_session_id = f"{safe_biz}:{session_id}"

    msgs = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == effective_session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )

    return {"messages": [{"role": m.role, "text": m.content} for m in msgs]}
@app.get("/version")
def version():
    return {"version": "v-2025-12-21-02"}

from fastapi import FastAPI, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
from pathlib import Path
import json
import asyncio
from dotenv import load_dotenv
from google import genai
from sqlalchemy.orm import Session

from db import engine, get_db
from models import Base, ChatMessage, ChatSession

# Setup
BASE_DIR = Path(__file__).resolve().parent
BUSINESS_DIR = BASE_DIR / "businesses"
BUSINESS_DIR.mkdir(exist_ok=True)

load_dotenv(BASE_DIR / ".env")

Base.metadata.create_all(bind=engine)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://client-sand-kappa.vercel.app",
        "https://beautyshohrestudio.ca",
        "https://www.beautyshohrestudio.ca",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class ChatRequest(BaseModel):
    session_id: str
    text: str
    biz_id: str = "default"
    name: str | None = None

# Helpers (minimal)
def clean_biz_id(biz_id: str) -> str:
    biz_id = (biz_id or "").strip().lower()
    biz_id = "".join(c for c in biz_id if c.isalnum() or c in ("-", "_"))
    return biz_id or "default"

def business_txt_path(biz_id: str) -> Path:
    p = BUSINESS_DIR / f"{biz_id}.txt"
    return p if p.exists() else (BUSINESS_DIR / "default.txt")

def business_json_path(biz_id: str) -> Path:
    p = BUSINESS_DIR / f"{biz_id}.json"
    return p if p.exists() else (BUSINESS_DIR / "default.json")

def load_business_context(biz_id: str) -> str:
    p = business_txt_path(biz_id)
    if not p.exists():
        return "Business info is not available."
    return p.read_text(encoding="utf-8")

def load_business_meta(biz_id: str) -> dict:
    """
    UI metadata for the frontend. Purely data-driven.
    Expected JSON keys:
      - businessName (string)
      - assistantName (string)
      - phone (string)
      - links (object: {key: url})
    """
    p = business_json_path(biz_id)
    if not p.exists():
        return {"businessName": "This Business", "assistantName": "Dew", "phone": "", "links": {}}

    try:
        meta = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    if not isinstance(meta, dict):
        meta = {}

    links = meta.get("links")
    if not isinstance(links, dict):
        links = {}

    return {
        "businessName": str(meta.get("businessName") or "This Business"),
        "assistantName": str(meta.get("assistantName") or "Dew"),
        "phone": str(meta.get("phone") or ""),
        "links": links,
    }

def system_prompt(context: str) -> str:
    return (
        "You are a professional front-desk assistant for the business described below.\n"
        "Keep replies short and clear (2–4 sentences).\n"
        "Do not repeat greetings.\n"
        "Use ONLY the information provided.\n"
        "If unsure, recommend booking online or contacting the business.\n\n"
        "Never guess prices or exact availability.\n\n"
        f"BUSINESS INFO:\n{context}\n"
    )

def make_session_key(biz_id: str, session_id: str) -> str:
    return f"{biz_id}:{session_id}"

# Tiny caches
_CONTEXT_CACHE: dict[str, str] = {}
_PROMPT_CACHE: dict[str, str] = {}

def get_context(biz_id: str) -> str:
    if biz_id not in _CONTEXT_CACHE:
        _CONTEXT_CACHE[biz_id] = load_business_context(biz_id)
    return _CONTEXT_CACHE[biz_id]

def get_system_prompt(biz_id: str) -> str:
    if biz_id not in _PROMPT_CACHE:
        _PROMPT_CACHE[biz_id] = system_prompt(get_context(biz_id))
    return _PROMPT_CACHE[biz_id]

# Routes
@app.get("/business/{biz_id}")
def business(biz_id: str):
    biz_id = clean_biz_id(biz_id)
    return load_business_meta(biz_id)

@app.post("/chat")
async def chat(body: ChatRequest, db: Session = Depends(get_db)):
    biz_id = clean_biz_id(body.biz_id)
    session_key = make_session_key(biz_id, body.session_id)

    # 1) session row
    s = db.get(ChatSession, session_key)
    if not s:
        s = ChatSession(id=session_key, name=body.name)
        db.add(s)
        db.commit()
    elif body.name and not s.name:
        s.name = body.name
        db.commit()

    # 2) save user msg
    db.add(ChatMessage(session_id=session_key, role="user", content=body.text))
    db.commit()

    # 3) last messages (keep small)
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_key)
        .order_by(ChatMessage.id.desc())
        .limit(6)
        .all()
    )[::-1]

    convo = "\n".join(f"{m.role.upper()}: {m.content}" for m in rows)
    prompt = f"{get_system_prompt(biz_id)}\nUser name: {s.name or 'there'}\n\nCONVERSATION:\n{convo}\n\nASSISTANT:"

    # 4) model call
    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model="gemini-2.5-flash",
            contents=[prompt],
        )
        reply = (response.text or "").strip() or "Sorry — please try again."
    except Exception as e:
        print("Gemini error:", repr(e))
        reply = "Sorry! I'm having trouble right now. Please try again."

    # 5) save assistant reply
    try:
        db.add(ChatMessage(session_id=session_key, role="assistant", content=reply))
        db.commit()
    except Exception:
        db.rollback()

    return {"reply": reply}

@app.get("/history")
def history(
    session_id: str = Query(...),
    biz_id: str = Query("default"),
    db: Session = Depends(get_db),
):
    biz_id = clean_biz_id(biz_id)
    session_key = make_session_key(biz_id, session_id)

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_key)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return {"messages": [{"role": m.role, "text": m.content} for m in rows]}

@app.get("/version")
def version():
    return {"version": "v-2025-12-23"}

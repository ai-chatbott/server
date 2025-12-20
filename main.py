from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from google import genai
# from openai import OpenAI
# from openai import RateLimitError, APIError

from typing import List, Dict

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise RuntimeError("Missing key")

client = genai.Client(api_key=GEMINI_API_KEY)

# client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

app = FastAPI()

# every user = one session , every session = message lists
sessions: Dict[str, List[dict]] = {}

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
def chat(body: ChatRequest):
    # session memory
    if body.session_id not in sessions:
        sessions[body.session_id] = []

    history = sessions[body.session_id]
    # add user message into memory
    history.append({"role": "user", "content": body.text})

    # business rule
    context = load_business_context()
    system_instruction = (
    "You are a professional front-desk assistant for Beauty Shohre Studio.\n"
    "Speak naturally and briefly (2–4 sentences max).\n"
    "Do NOT greet the user repeatedly.\n"
    "Address the user by their name when appropriate.\n"
    "Be friendly, confident, and non-repetitive.\n"
    "Use ONLY the information provided.\n\n"

    "GREETING RULES:\n"
    "- Greet the user ONLY ONCE at the very start with a simple Hello.\n"
    "- Ask for the user's name in the first message.\n"
    "- After the user provides their name, do NOT say hello, hi, or nice to meet you again.\n"
    "- Avoid filler phrases and repeated pleasantries."
    "- From then on, go directly into helping the client.\n\n"

    "BOOKING RULES:\n"
    "- To book a consultation, clients must call or text Shohre at 778-513-9006.\n"
    "- Online booking is available.\n"
    "- Do not guess prices or availability.\n\n"

    "LINKING RULES:\n"
    "- When suggesting online booking, say: book online.\n"
    "- When suggesting phone contact, say: call or text Shohre.\n"
    "- Do NOT include raw URLs.\n"
    "- Do NOT format links.\n\n"

    "INSPIRATION & REFERENCES"
    "If a client is unsure what color or haircut they want, suggest:\n"
    "- Viewing the website gallery for examples of our work.\n"
    "- Visiting our Instagram for more color transformations and styles.\n"
    "- Saving 2–3 inspiration photos that match their hair type and lifestyle.\n"
    "- Bringing/showing those photos to Shohre during consultation so we can recommend the best option.\n\n "

    "STYLE-INSPIRATION RULE:"
    "If the client is unsure about color or haircut, suggest they check the website gallery or Instagram for inspiration,\n"
    "save 2–3 photos they like, and show them to Shohre during consultation.\n"
    "- When suggesting examples of work, say: website gallery or Instagram.\n"
    "- Do NOT include URLs.\n\n"


    f"BUSINESS INFO:\n{context}\n"
    )





    # build prompt from histpry
    convo_text = "\n".join(
        # keep it short
        [f"{m['role'].upper()}: {m['content']}" for m in history[-12:]] 
    )
    user_name = body.name or "the client"
    prompt = (
        f"{system_instruction}\n\n"
        f"User name: {user_name}\n\n"
        f"CONVERSATION:\n{convo_text}\n\nASSISTANT:"
    )

    # call gemini
    try:
        response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
        reply = (response.text or "").strip()
    except Exception:
        reply = "AI service error. Please try again."



    # messages = [system_msg] + history

    # try:
    #     response = client.responses.create(
    #         model="gpt-5-nano",
    #         input=messages,
    #     )
    #     reply = response.output_text

    # except RateLimitError:
    #     reply = "I can’t answer right now because the AI quota/billing is exceeded. Please try again later."

    # except APIError:
    #     reply = "The AI service is temporarily unavailable. Please try again."

    history.append({"role": "assistant", "content": reply})
    return {"reply": reply}

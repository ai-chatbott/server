from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from google import genai
# from openai import OpenAI
# from openai import RateLimitError, APIError

from typing import List, Dict

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

def load_business_context() -> str:
    with open("business.txt", "r", encoding="utf-8") as f:
        return f.read()

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
        "You are a helpful assistant for this business. "
        "Use ONLY the information provided. "
        "If the answer is not in the info, say you don’t know and suggest how to get the info.\n\n"
        f"BUSINESS INFO:\n{context}"
    )

    # build prompt from histpry
    convo_text = "\n".join(
        # keep it short
        [f"{m['role'].upper()}: {m['content']}" for m in history[-12:]] 
    )
    prompt = f"{system_instruction}\n\nCONVERSATION:\n{convo_text}\n\nASSISTANT:"

    # call gemini
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )

    reply = (response.text or "").strip()
    if not reply:
        reply = "I couldn't generate a response. Please try again later."


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

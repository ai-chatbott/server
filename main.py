from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import os
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv("API_KEY"))

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    text: str

# @app.get("/health")
# def health():
#     return {"ok": True}

@app.post("/chat")
def chat(body: ChatRequest):
    response = client.responses.create(
        model="gpt-5-nano",
        input=body.text,
    )
    return {
        "reply": response.output_text
    }
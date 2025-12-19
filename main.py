from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/chat")
def chat(body: ChatRequest):
    return {"replay": f"You said: {body.text}"}
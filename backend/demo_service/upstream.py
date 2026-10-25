from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(title="Demo Upstream")


class AnswerRequest(BaseModel):
    message: str


@app.post("/v1/answer")
def answer(payload: AnswerRequest):
    return {
        "reply": f"Echo: {payload.message}",
    }
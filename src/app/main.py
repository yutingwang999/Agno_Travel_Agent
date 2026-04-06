import os

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

app = FastAPI(
    title="Travel Itinerary Planner",
    description="AI-powered travel itinerary planning using CAG + RAG workflow",
    version="0.1.0",
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}

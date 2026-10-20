
from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from routers.roadmap import router as roadmap_router
from database import init_db
from routers.auth import router as auth_router
from routers.onboarding import router as onboarding_router
from routers.blindspots import router as blindspots_router
from routers.decisions import router as decisions_router
from routers.chat import router as chat_router
from fastapi.middleware.cors import CORSMiddleware
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize application resources before serving requests."""
    init_db()
    yield


app = FastAPI(
    title="Stratify.AI",
    version="0.1.0",
    description=(
        "Adaptive, personalized decision support for career, "
        "education, and life planning."
    ),
    lifespan=lifespan,
)
frontend_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["Authorization", "Content-Type"],
)
app.include_router(auth_router)
app.include_router(onboarding_router)
app.include_router(roadmap_router)
app.include_router(blindspots_router)
app.include_router(decisions_router)
app.include_router(chat_router)
@app.get("/", tags=["Health"])
def home():
    return {
        "message": "Welcome to Stratify.AI",
        "status": "ok",
    }

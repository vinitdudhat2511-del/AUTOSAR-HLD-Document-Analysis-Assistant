import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import router as api_router
from app.database import init_db
from app.config import settings

# Initialize database and seed default projects & users
init_db()

app = FastAPI(
    title=settings.APP_NAME,
    description="Secure enterprise API for ingesting and analyzing AUTOSAR High-Level Design documents with RBAC, Project Isolation, and Human Governance.",
    version=settings.APP_VERSION
)

# Configure CORS with strict allowed origins
origins = [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "llm_model": settings.OLLAMA_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL
    }

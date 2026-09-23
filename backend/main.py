from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import ChallengeStore
from .models import Challenge, ChallengeCreate, ChallengeUpdate, Readiness
from .scoring import calculate_readiness


def create_app(database_path: Path | None = None) -> FastAPI:
    store = ChallengeStore(database_path or Path(__file__).parent / "data" / "challenges.sqlite3")

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="AI Sana Challenge Hub", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.exception_handler(sqlite3.Error)
    async def database_error(request, exc):
        return JSONResponse(status_code=503, content={
            "detail": "База данных временно недоступна. Повторите запрос позже."
        })

    def get_or_404(challenge_id: UUID):
        data = store.get(str(challenge_id))
        if data is None:
            raise HTTPException(404, "Задача не найдена")
        return data

    def response(challenge_id, data):
        return Challenge(id=str(challenge_id), **data.model_dump(),
                         **calculate_readiness(data).model_dump())

    @app.get("/")
    def home():
        return {"message": "Adaptive Learning Agent is running"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/challenges", response_model=Challenge, status_code=201)
    def create_challenge(data: ChallengeCreate):
        challenge_id, saved = store.create(data)
        return response(challenge_id, saved)

    @app.get("/challenges/{challenge_id}", response_model=Challenge)
    def get_challenge(challenge_id: UUID):
        return response(challenge_id, get_or_404(challenge_id))

    @app.patch("/challenges/{challenge_id}", response_model=Challenge)
    def update_challenge(challenge_id: UUID, changes: ChallengeUpdate):
        updates = changes.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(422, "Укажите хотя бы одно поле для изменения")
        saved = store.update(str(challenge_id), updates)
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return response(challenge_id, saved)

    @app.post("/challenges/{challenge_id}/readiness", response_model=Readiness)
    def recalculate_readiness(challenge_id: UUID):
        return calculate_readiness(get_or_404(challenge_id))

    return app


app = create_app()

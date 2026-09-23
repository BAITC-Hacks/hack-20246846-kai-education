from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
from uuid import UUID
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .database import ChallengeStore, WorkflowConflict
from .ai_models import AIFallback, AnalysisResult, ConfirmRequest, ProposalRequest, ProposalResult
from .ai_provider import AIProvider, OpenAIProvider
from .ai_workflow import AIWorkflow
from .models import Challenge, ChallengeCreate, ChallengeUpdate, Readiness
from .scoring import calculate_readiness
from .proposal_models import Proposal, ProposalCreate, PublishRequest


def create_app(database_path: Path | None = None, ai_provider: AIProvider | None = None) -> FastAPI:
    store = ChallengeStore(database_path or Path(__file__).parent / "data" / "challenges.sqlite3")
    workflow = AIWorkflow(store, ai_provider if ai_provider is not None else OpenAIProvider())

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

    @app.exception_handler(WorkflowConflict)
    async def workflow_conflict(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    def get_or_404(challenge_id: UUID):
        data = store.get(str(challenge_id))
        if data is None:
            raise HTTPException(404, "Задача не найдена")
        return data

    def response(challenge_id, data, published=None):
        return Challenge(id=str(challenge_id), **data.model_dump(),
                         published=store.is_published(str(challenge_id)) if published is None else published,
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

    @app.get("/challenges", response_model=list[Challenge])
    def catalog(industry: str | None = None,
                readiness_level: Literal["Draft", "Working", "Ready", "Priority"] | None = None):
        cards = [response(cid, data, published=True) for cid, data in store.published_challenges()
                 if industry is None or data.industry.casefold() == industry.strip().casefold()]
        if readiness_level is not None:
            cards = [card for card in cards if card.readiness_level == readiness_level]
        return sorted(cards, key=lambda card: (-card.readiness_score, card.id))

    @app.post("/challenges/{challenge_id}/publish", response_model=Challenge)
    def publish_challenge(challenge_id: UUID, request: PublishRequest):
        saved = store.publish(str(challenge_id))
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return response(challenge_id, saved, published=True)

    @app.post("/challenges/{challenge_id}/proposals", response_model=Proposal, status_code=201)
    def submit_proposal(challenge_id: UUID, data: ProposalCreate):
        saved = store.create_student_proposal(str(challenge_id), data)
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return saved

    @app.get("/challenges/{challenge_id}/proposals", response_model=list[Proposal])
    def list_proposals(challenge_id: UUID):
        get_or_404(challenge_id)
        return store.list_student_proposals(str(challenge_id))

    def decide(challenge_id, proposal_id, decision):
        get_or_404(challenge_id)
        saved = store.decide_student_proposal(str(challenge_id), str(proposal_id), decision)
        if saved is None:
            raise HTTPException(404, "Предложение команды для этой задачи не найдено")
        return saved

    @app.post("/challenges/{challenge_id}/proposals/{proposal_id}/accept", response_model=Proposal)
    def accept_proposal(challenge_id: UUID, proposal_id: UUID):
        return decide(challenge_id, proposal_id, "accepted")

    @app.post("/challenges/{challenge_id}/proposals/{proposal_id}/reject", response_model=Proposal)
    def reject_proposal(challenge_id: UUID, proposal_id: UUID):
        return decide(challenge_id, proposal_id, "rejected")

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

    @app.post("/challenges/{challenge_id}/analysis", response_model=AnalysisResult | AIFallback)
    def analyze_challenge(challenge_id: UUID):
        return workflow.analyze(str(challenge_id), get_or_404(challenge_id))

    @app.post("/challenges/{challenge_id}/card-proposals", response_model=ProposalResult | AIFallback)
    def propose_card(challenge_id: UUID, request: ProposalRequest):
        return workflow.propose(str(challenge_id), get_or_404(challenge_id), request)

    @app.get("/challenges/{challenge_id}/card-proposals/{proposal_id}", response_model=ProposalResult)
    def get_proposed_card(challenge_id: UUID, proposal_id: UUID):
        get_or_404(challenge_id)
        return workflow.get_proposal(str(challenge_id), str(proposal_id))

    @app.post("/challenges/{challenge_id}/card-proposals/{proposal_id}/confirm", response_model=Challenge)
    def confirm_card(challenge_id: UUID, proposal_id: UUID, request: ConfirmRequest):
        get_or_404(challenge_id)
        saved = store.confirm_proposal(str(proposal_id), str(challenge_id),
                                       request.edits.model_dump(exclude_unset=True))
        if saved is None:
            raise HTTPException(404, "Предложение для этой задачи не найдено")
        return response(challenge_id, saved)

    return app


app = create_app()

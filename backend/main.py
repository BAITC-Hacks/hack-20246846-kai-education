from contextlib import asynccontextmanager
from pathlib import Path
import sqlite3
import os
from uuid import UUID
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from dotenv import dotenv_values

from .database import ChallengeStore, WorkflowConflict
from .ai_models import AIFallback, AnalysisResult, ConfirmRequest, ProposalRequest, ProposalResult
from .ai_provider import AIProvider, OpenAIProvider
from .ai_workflow import AIWorkflow
from .models import Challenge, ChallengeCreate, ChallengeUpdate, Readiness
from .scoring import calculate_readiness
from .proposal_models import Proposal, ProposalCreate, PublishRequest
from .auth import AuthService
from .auth_models import UserPublic


def create_app(database_path: Path | None = None, ai_provider: AIProvider | None = None,
               *, frontend_origin: str | None = None, secure_cookie: bool | None = None) -> FastAPI:
    store = ChallengeStore(database_path or Path(__file__).parent / "data" / "challenges.sqlite3")
    workflow = AIWorkflow(store, ai_provider if ai_provider is not None else OpenAIProvider())
    env = dotenv_values(Path(__file__).resolve().parent.parent / '.env')
    origin = frontend_origin or os.environ.get('FRONTEND_ORIGIN') or env.get('FRONTEND_ORIGIN') or 'http://localhost:5173'
    if secure_cookie is None:
        secure_cookie = (os.environ.get('AUTH_COOKIE_SECURE') or env.get('AUTH_COOKIE_SECURE') or 'false').lower() == 'true'
    auth = AuthService(store, secure_cookie=secure_cookie)

    @asynccontextmanager
    async def lifespan(app):
        store.initialize()
        yield

    app = FastAPI(title="AI Sana Challenge Hub", lifespan=lifespan)

    @app.middleware('http')
    async def browser_origin_guard(request, call_next):
        # HttpOnly SameSite cookies plus strict Origin checking for every mutation.
        # Never trust an Origin sent by a browser other than the configured frontend.
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'} and request.headers.get('origin') != origin:
            return JSONResponse(status_code=403, content={'detail': 'Недопустимый источник запроса.'})
        result = await call_next(request)
        if request.url.path.startswith('/auth/'):
            result.headers['Cache-Control'] = 'no-store'
        return result

    app.add_middleware(
        CORSMiddleware, allow_origins=[origin], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.include_router(auth.router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI normally echoes invalid input, including submitted passwords.
        return JSONResponse(status_code=422, content={'detail': [
            {'loc': error['loc'], 'msg': error['msg'], 'type': error['type']}
            for error in exc.errors()
        ]})

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
                         owner_id=store.get_owner_id(str(challenge_id)),
                         published=store.is_published(str(challenge_id)) if published is None else published,
                         **calculate_readiness(data).model_dump())

    def business(user: UserPublic = Depends(auth.current_user)):
        if user.role != 'business':
            raise HTTPException(403, 'Это действие доступно только бизнесу.')
        return user

    def verified_business(user: UserPublic = Depends(business)):
        if user.verification_status != 'verified':
            raise HTTPException(403, 'Для этого действия нужен подтверждённый аккаунт бизнеса.')
        return user

    def student(user: UserPublic = Depends(auth.current_user)):
        if user.role != 'student':
            raise HTTPException(403, 'Отправлять предложения могут только студенты.')
        if user.verification_status != 'verified':
            raise HTTPException(403, 'Для отправки предложения подтвердите аккаунт студента.')
        return user

    def check_owner(challenge_id, user):
        get_or_404(challenge_id)
        owner_id = store.get_owner_id(str(challenge_id))
        if owner_id is None:
            raise HTTPException(409, 'Архивная задача без владельца доступна только для чтения. Владелец назначается локально оператором demo.')
        if owner_id != user.id:
            raise HTTPException(403, 'Управлять задачей может только её владелец.')
        return user

    def owner(challenge_id: UUID, user: UserPublic = Depends(business)):
        return check_owner(challenge_id, user)

    def verified_owner(challenge_id: UUID, user: UserPublic = Depends(verified_business)):
        return check_owner(challenge_id, user)

    @app.get("/")
    def home():
        return {"message": "Adaptive Learning Agent is running"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/challenges", response_model=Challenge, status_code=201)
    def create_challenge(data: ChallengeCreate, user: UserPublic = Depends(business)):
        challenge_id, saved = store.create(data, owner_id=user.id)
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
    def publish_challenge(challenge_id: UUID, request: PublishRequest, user: UserPublic = Depends(verified_owner)):
        saved = store.publish(str(challenge_id))
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return response(challenge_id, saved, published=True)

    @app.post("/challenges/{challenge_id}/proposals", response_model=Proposal, status_code=201)
    def submit_proposal(challenge_id: UUID, data: ProposalCreate, user: UserPublic = Depends(student)):
        get_or_404(challenge_id)
        if store.get_owner_id(str(challenge_id)) is None:
            raise HTTPException(409, 'Архивная задача без владельца пока не принимает предложения.')
        saved = store.create_student_proposal(str(challenge_id), data, student_id=user.id)
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return saved

    @app.get("/challenges/{challenge_id}/proposals", response_model=list[Proposal])
    def list_proposals(challenge_id: UUID, user: UserPublic = Depends(owner)):
        get_or_404(challenge_id)
        return store.list_student_proposals(str(challenge_id))

    def decide(challenge_id, proposal_id, decision):
        get_or_404(challenge_id)
        saved = store.decide_student_proposal(str(challenge_id), str(proposal_id), decision)
        if saved is None:
            raise HTTPException(404, "Предложение команды для этой задачи не найдено")
        return saved

    @app.post("/challenges/{challenge_id}/proposals/{proposal_id}/accept", response_model=Proposal)
    def accept_proposal(challenge_id: UUID, proposal_id: UUID, user: UserPublic = Depends(verified_owner)):
        return decide(challenge_id, proposal_id, "accepted")

    @app.post("/challenges/{challenge_id}/proposals/{proposal_id}/reject", response_model=Proposal)
    def reject_proposal(challenge_id: UUID, proposal_id: UUID, user: UserPublic = Depends(verified_owner)):
        return decide(challenge_id, proposal_id, "rejected")

    @app.get("/challenges/{challenge_id}", response_model=Challenge)
    def get_challenge(challenge_id: UUID, user: UserPublic | None = Depends(auth.optional_user)):
        data = get_or_404(challenge_id)
        if not store.is_published(str(challenge_id)):
            if user is None:
                raise HTTPException(401, 'Войдите, чтобы открыть черновик.')
            if user.role != 'business':
                raise HTTPException(403, 'Черновик доступен только владельцу бизнеса.')
            check_owner(challenge_id, user)
        return response(challenge_id, data)

    @app.patch("/challenges/{challenge_id}", response_model=Challenge)
    def update_challenge(challenge_id: UUID, changes: ChallengeUpdate, user: UserPublic = Depends(owner)):
        if store.is_published(str(challenge_id)) and user.verification_status != 'verified':
            raise HTTPException(403, 'Изменять опубликованную задачу может только подтверждённый бизнес.')
        updates = changes.model_dump(exclude_unset=True)
        if not updates:
            raise HTTPException(422, "Укажите хотя бы одно поле для изменения")
        saved = store.update(str(challenge_id), updates)
        if saved is None:
            raise HTTPException(404, "Задача не найдена")
        return response(challenge_id, saved)

    @app.post("/challenges/{challenge_id}/readiness", response_model=Readiness)
    def recalculate_readiness(challenge_id: UUID, user: UserPublic = Depends(owner)):
        return calculate_readiness(get_or_404(challenge_id))

    @app.post("/challenges/{challenge_id}/analysis", response_model=AnalysisResult | AIFallback)
    def analyze_challenge(challenge_id: UUID, user: UserPublic = Depends(owner)):
        return workflow.analyze(str(challenge_id), get_or_404(challenge_id))

    @app.post("/challenges/{challenge_id}/card-proposals", response_model=ProposalResult | AIFallback)
    def propose_card(challenge_id: UUID, request: ProposalRequest, user: UserPublic = Depends(owner)):
        return workflow.propose(str(challenge_id), get_or_404(challenge_id), request)

    @app.get("/challenges/{challenge_id}/card-proposals/{proposal_id}", response_model=ProposalResult)
    def get_proposed_card(challenge_id: UUID, proposal_id: UUID, user: UserPublic = Depends(owner)):
        get_or_404(challenge_id)
        return workflow.get_proposal(str(challenge_id), str(proposal_id))

    @app.post("/challenges/{challenge_id}/card-proposals/{proposal_id}/confirm", response_model=Challenge)
    def confirm_card(challenge_id: UUID, proposal_id: UUID, request: ConfirmRequest, user: UserPublic = Depends(owner)):
        if store.is_published(str(challenge_id)) and user.verification_status != 'verified':
            raise HTTPException(403, 'Изменять опубликованную задачу может только подтверждённый бизнес.')
        get_or_404(challenge_id)
        saved = store.confirm_proposal(str(proposal_id), str(challenge_id),
                                       request.edits.model_dump(exclude_unset=True))
        if saved is None:
            raise HTTPException(404, "Предложение для этой задачи не найдено")
        return response(challenge_id, saved)

    return app


app = create_app()

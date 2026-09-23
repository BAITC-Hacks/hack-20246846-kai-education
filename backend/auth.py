"""Password authentication with opaque, revocable SQLite sessions for the MVP."""
import hashlib
import hmac
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response

from .auth_models import LoginInput, RegisterInput, UserPublic


COOKIE_NAME = "kaibridge_session"
SESSION_SECONDS = 12 * 60 * 60
PBKDF2_ITERATIONS = 600_000
PUBLIC_COLUMNS = "id, name, email, role, verification_status, created_at, university, company_name, position, company_industry, company_website"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, iterations, salt, expected = encoded.split("$")
        if scheme != "pbkdf2_sha256" or not 600_000 <= int(iterations) <= 2_000_000:
            return False
        salt_bytes, expected_bytes = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt_bytes) != 16 or len(expected_bytes) != 32:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations))
        return hmac.compare_digest(digest, expected_bytes)
    except (ValueError, TypeError, AttributeError):
        return False


# Missing accounts still perform the same expensive password verification.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


def user_from_row(row) -> UserPublic:
    return UserPublic(**dict(zip(PUBLIC_COLUMNS.split(", "), row)))


class AuthService:
    def __init__(self, store, secure_cookie=False):
        self.store = store
        self.secure_cookie = secure_cookie
        self.router = APIRouter(prefix="/auth", tags=["auth"])
        self.router.add_api_route("/register", self.register, methods=["POST"],
                                  response_model=UserPublic, status_code=201)
        self.router.add_api_route("/login", self.login, methods=["POST"], response_model=UserPublic)
        self.router.add_api_route("/me", self.me, methods=["GET"], response_model=UserPublic)
        self.router.add_api_route("/logout", self.logout, methods=["POST"], status_code=204)
        self.router.add_api_route("/request-verification", self.request_verification,
                                  methods=["POST"], response_model=UserPublic)

    def optional_user(self, request: Request) -> UserPublic | None:
        token = request.cookies.get(COOKIE_NAME)
        if not token or len(token) > 128:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self.store.connection() as db:
            columns = ", ".join(f"u.{column}" for column in PUBLIC_COLUMNS.split(", "))
            row = db.execute(f"""SELECT {columns} FROM users u
                JOIN auth_sessions s ON s.user_id = u.id
                WHERE s.token_hash = ? AND s.expires_at > ?""",
                             (token_hash, int(time.time()))).fetchone()
        return user_from_row(row) if row else None

    def current_user(self, request: Request) -> UserPublic:
        user = self.optional_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Войдите в аккаунт, чтобы продолжить.")
        return user

    def register(self, data: RegisterInput):
        profile = data.model_dump(exclude={"password"})
        if data.role == "student":
            for field in ("company_name", "position", "company_industry", "company_website"):
                profile[field] = None
        else:
            profile["university"] = None
        user = UserPublic(id=str(uuid4()), verification_status="unverified",
                          created_at=datetime.now(timezone.utc).isoformat(), **profile)
        password_hash = hash_password(data.password)
        try:
            with self.store.connection() as db:
                db.execute(f"INSERT INTO users ({PUBLIC_COLUMNS}, password_hash) VALUES ({', '.join(['?'] * 12)})",
                           (*[getattr(user, column) for column in PUBLIC_COLUMNS.split(", ")], password_hash))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Аккаунт с таким email уже существует.") from None
        return user

    def login(self, data: LoginInput, request: Request, response: Response):
        with self.store.connection() as db:
            row = db.execute(f"SELECT {PUBLIC_COLUMNS}, password_hash FROM users WHERE email = ?",
                             (data.email,)).fetchone()
        valid = verify_password(data.password, row[-1] if row else _DUMMY_HASH)
        if not row or not valid:
            raise HTTPException(status_code=401, detail="Неверный email или пароль.")
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        now = int(time.time())
        with self.store.connection() as db:
            db.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
            old_token = request.cookies.get(COOKIE_NAME)
            if old_token and len(old_token) <= 128:
                db.execute("DELETE FROM auth_sessions WHERE token_hash = ?",
                           (hashlib.sha256(old_token.encode("utf-8")).hexdigest(),))
            db.execute("INSERT INTO auth_sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                       (token_hash, row[0], now, now + SESSION_SECONDS))
        response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=self.secure_cookie, samesite="lax", path="/")
        return user_from_row(row[:-1])

    def me(self, request: Request):
        return self.current_user(request)

    def logout(self, request: Request):
        token = request.cookies.get(COOKIE_NAME)
        if token and len(token) <= 128:
            with self.store.connection() as db:
                db.execute("DELETE FROM auth_sessions WHERE token_hash = ?",
                           (hashlib.sha256(token.encode("utf-8")).hexdigest(),))
        response = Response(status_code=204)
        response.delete_cookie(COOKIE_NAME, httponly=True, secure=self.secure_cookie,
                               samesite="lax", path="/")
        return response

    def request_verification(self, request: Request):
        user = self.current_user(request)
        with self.store.connection() as db:
            # Pending is an MVP queue only; no request can self-approve a user.
            db.execute("UPDATE users SET verification_status = 'pending' WHERE id = ? AND verification_status = 'unverified'",
                       (user.id,))
            row = db.execute(f"SELECT {PUBLIC_COLUMNS} FROM users WHERE id = ?", (user.id,)).fetchone()
        return user_from_row(row)

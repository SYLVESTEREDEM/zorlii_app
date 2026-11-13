import json
import base64
import hmac
import logging
import os
import re
import secrets
import sqlite3
import time
import hashlib
import uuid
from io import BytesIO
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .context_assistance import extractive_context
from .db import Database
from .email_delivery import EmailConfigurationError, mailer_from_env
from .recommendations import recommend
from .security import hash_password, new_session_token, token_digest, verify_password


load_dotenv(Path(__file__).with_name(".env"))

SESSION_COOKIE = "zorlii_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
RESET_SECONDS = 30 * 60
OTP_SECONDS = 10 * 60
OTP_MAX_ATTEMPTS = 5
OTP_RESEND_COOLDOWN = 60
OTP_EMAIL_LIMIT = 5
OTP_IP_LIMIT = 20
OTP_RATE_WINDOW = 60 * 60
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")
PASSWORD_RE = re.compile(r"^(?=.*[A-Z])(?=.*[a-z])(?=.*[0-9])(?=.*[^A-Za-z0-9\s])")
DB = Database()
LOGGER = logging.getLogger("zorlii.recovery")
OTP_GENERIC_MESSAGE = "If the details can be verified, a one-time code may be sent. This response does not confirm delivery."
PASSWORD_POLICY_MESSAGE = "Password must be 4–128 characters and include an uppercase letter, a lowercase letter, a number, and a special character."
AVATAR_MAX_BYTES = 2 * 1024 * 1024
AVATAR_MAX_DIMENSION = 4096
AVATAR_MAX_PIXELS = 16_000_000
AVATAR_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


class OTPConfigurationError(RuntimeError):
    pass


def validate_password(value):
    if not 4 <= len(value) <= 128 or not PASSWORD_RE.search(value):
        raise ValueError(PASSWORD_POLICY_MESSAGE)
    return value


def otp_secret():
    secret = os.environ.get("ZORLII_OTP_SECRET", "")
    if len(secret) < 32:
        raise OTPConfigurationError("A private ZORLII_OTP_SECRET of at least 32 characters is required.")
    return secret.encode("utf-8")


def otp_digest(secret, purpose, email, code):
    payload = f"otp:{purpose}:{email}:{code}".encode("utf-8")
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def otp_rate_digest(secret, kind, value):
    return hmac.new(secret, f"rate:{kind}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()


class RegisterInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=3, max_length=254)
    username: str = Field(min_length=3, max_length=24)
    password: str = Field(min_length=4, max_length=128)
    display_name: str = Field(min_length=1, max_length=60)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.lower()
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        value = value.lower()
        if not USERNAME_RE.fullmatch(value):
            raise ValueError("Use 3–24 letters, numbers, or underscores.")
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value):
        return validate_password(value)


class LoginInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.strip().lower()


class ForgotInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value


class OTPInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(pattern=r"^\d{6}$")

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        value = value.strip().lower()
        if not EMAIL_RE.fullmatch(value):
            raise ValueError("Enter a valid email address.")
        return value


class RegisterVerifyInput(OTPInput):
    pass


class PasswordResetInput(OTPInput):
    password: str = Field(min_length=4, max_length=128)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value):
        return validate_password(value)


class AccountDeleteInput(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=60)
    bio: str | None = Field(default=None, max_length=280)
    interests: list[str] | None = Field(default=None, max_length=12)
    recommendations_consent: bool | None = None
    context_assistance_consent: bool | None = None

    @field_validator("interests")
    @classmethod
    def normalize_interests(cls, values):
        if values is None:
            return None
        cleaned = []
        for value in values:
            item = value.strip().lower()
            if not item or len(item) > 40:
                raise ValueError("Each interest must contain 1 to 40 characters.")
            if item not in cleaned:
                cleaned.append(item)
        return cleaned


class PostInput(BaseModel):
    body: str = Field(min_length=1, max_length=5000)
    visibility: str = Field(default="public", pattern="^(public|followers|private)$")

    @field_validator("body")
    @classmethod
    def non_whitespace(cls, value):
        if not value.strip():
            raise ValueError("Post text cannot be blank.")
        return value.strip()


class MessageInput(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def non_whitespace(cls, value):
        if not value.strip():
            raise ValueError("Message cannot be blank.")
        return value.strip()


class ConversationInput(BaseModel):
    username: str = Field(min_length=3, max_length=24)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value):
        return value.strip().lstrip("@").lower()


class ContextInput(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    question: str = Field(min_length=1, max_length=400)
    consent_for_this_request: bool

    @field_validator("text", "question")
    @classmethod
    def non_whitespace(cls, value):
        if not value.strip():
            raise ValueError("This field cannot be blank.")
        return value.strip()


def set_session(response: Response, token: str):
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=os.environ.get("ZORLII_COOKIE_SECURE", "").lower() in {"1", "true", "yes"},
        samesite="strict",
        path="/",
    )


def public_user(row):
    result = {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "bio": row["bio"],
        "created_at": row["created_at"],
    }
    if "avatar_filename" in row.keys():
        result["avatar_url"] = (
            f"/api/avatars/{row['id']}?v={row['avatar_filename'][:8]}"
            if row["avatar_filename"] else None
        )
    return result


def new_app(database=None, mailer=None, avatar_directory=None):
    db = database or DB
    db.connect()
    if avatar_directory is not None:
        avatar_dir = Path(avatar_directory)
    elif str(db.path) == ":memory:":
        avatar_dir = Path(__file__).with_name("data") / "avatars"
    else:
        avatar_dir = Path(db.path).expanduser().parent / "avatars"
    app = FastAPI(title="Zorlii API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/assets", StaticFiles(directory=str(os.path.join(os.path.dirname(__file__), "assets"))), name="assets")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(os.path.dirname(__file__), "index.html"))

    def authenticated_user(request: Request):
        authorization = request.headers.get("authorization", "")
        token = None
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token:
            token = request.cookies.get(SESSION_COOKIE)
        if not token:
            raise HTTPException(status_code=401, detail="Sign in to continue.")
        with db.locked_connection() as connection:
            row = connection.execute(
                """SELECT u.id, u.email, u.username FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ?""",
                (token_digest(token), int(time.time())),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=401, detail="Your session has expired.")
        return dict(row)

    User = Annotated[dict, Depends(authenticated_user)]

    def visible_post(connection, post_id, viewer_id):
        row = connection.execute(
            """SELECT p.*, u.username, pr.display_name, pr.bio,
                      pr.avatar_filename,
                      (SELECT COUNT(*) FROM replies r WHERE r.post_id=p.id) AS reply_count,
                      (SELECT COUNT(*) FROM reactions x WHERE x.post_id=p.id) AS reaction_count,
                      EXISTS(SELECT 1 FROM reactions x WHERE x.post_id=p.id AND x.user_id=?) AS reacted,
                      EXISTS(SELECT 1 FROM bookmarks b WHERE b.post_id=p.id AND b.user_id=?) AS bookmarked,
                      EXISTS(SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=p.user_id) AS followed
               FROM posts p JOIN users u ON u.id=p.user_id JOIN profiles pr ON pr.user_id=u.id
               WHERE p.id=?""",
            (viewer_id, viewer_id, viewer_id, post_id),
        ).fetchone()
        if row is None:
            return None
        if row["user_id"] != viewer_id:
            if row["visibility"] == "private":
                return None
            if row["visibility"] == "followers" and not row["followed"]:
                return None
        return dict(row)

    def post_payload(row):
        return {
            "id": row["id"],
            "body": row["body"],
            "visibility": row["visibility"],
            "created_at": row["created_at"],
            "author": {
                "id": row["user_id"],
                "username": row["username"],
                "display_name": row["display_name"],
                "bio": row["bio"],
                "avatar_url": (
                    f"/api/avatars/{row['user_id']}?v={row['avatar_filename'][:8]}"
                    if row["avatar_filename"] else None
                ),
            },
            "reply_count": row["reply_count"],
            "reaction_count": row["reaction_count"],
            "reacted": bool(row["reacted"]),
            "bookmarked": bool(row["bookmarked"]),
        }

    @app.get("/api/health")
    def health():
        try:
            mailer_from_env()
            email = "configured"
        except (EmailConfigurationError, ValueError):
            email = "not_configured"
        return {"status": "ok", "email": email}

    @app.get("/api/avatars/{user_id}")
    def get_avatar(user_id: int):
        with db.locked_connection() as connection:
            row = connection.execute(
                "SELECT avatar_filename FROM profiles WHERE user_id=?", (user_id,)
            ).fetchone()
        if row is None or not row["avatar_filename"]:
            raise HTTPException(status_code=404, detail="Profile photo not found.")
        filename = row["avatar_filename"]
        if not re.fullmatch(r"[a-f0-9]{32}\.jpg", filename):
            raise HTTPException(status_code=404, detail="Profile photo not found.")
        path = avatar_dir / filename
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Profile photo not found.")
        return FileResponse(
            path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"},
        )

    @app.put("/api/profile/avatar")
    async def upload_avatar(request: Request, user: User):
        request_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if request_type not in AVATAR_TYPES and request_type != "application/json":
            raise HTTPException(status_code=415, detail="Choose a JPEG, PNG, or WebP image.")
        request_limit = AVATAR_MAX_BYTES if request_type in AVATAR_TYPES else (AVATAR_MAX_BYTES * 4 // 3) + 4096
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > request_limit:
                    raise HTTPException(status_code=413, detail="Profile photos must be 2 MB or smaller.")
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid content length.")
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > request_limit:
                raise HTTPException(status_code=413, detail="Profile photos must be 2 MB or smaller.")
            chunks.append(chunk)
        if not size:
            raise HTTPException(status_code=400, detail="Choose a photo to upload.")

        content = b"".join(chunks)
        if request_type == "application/json":
            try:
                payload = json.loads(content)
                content_type = payload["content_type"]
                encoded = payload["image_base64"]
                if content_type not in AVATAR_TYPES or not isinstance(encoded, str):
                    raise ValueError
                content = base64.b64decode(encoded, validate=True)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                raise HTTPException(status_code=400, detail="Choose a valid JPEG, PNG, or WebP image.")
            if len(content) > AVATAR_MAX_BYTES:
                raise HTTPException(status_code=413, detail="Profile photos must be 2 MB or smaller.")
        else:
            content_type = request_type
        try:
            source = BytesIO(content)
            with Image.open(source) as image:
                if image.format != AVATAR_TYPES[content_type]:
                    raise ValueError("Image format does not match its content type.")
                if image.width > AVATAR_MAX_DIMENSION or image.height > AVATAR_MAX_DIMENSION:
                    raise ValueError("Image dimensions are too large.")
                if image.width * image.height > AVATAR_MAX_PIXELS:
                    raise ValueError("Image dimensions are too large.")
                image.verify()
            source.seek(0)
            with Image.open(source) as image:
                image.load()
                image = ImageOps.exif_transpose(image)
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new("RGB", rgba.size, "white")
                    background.paste(rgba, mask=rgba.getchannel("A"))
                    image = background
                else:
                    image = image.convert("RGB")
                output = BytesIO()
                image.save(output, format="JPEG", quality=86, optimize=True)
                image_bytes = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(status_code=400, detail="Upload a valid JPEG, PNG, or WebP image.")

        avatar_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.jpg"
        new_path = avatar_dir / filename
        try:
            new_path.write_bytes(image_bytes)
            with db.transaction() as connection:
                current = connection.execute(
                    "SELECT avatar_filename FROM profiles WHERE user_id=?", (user["id"],)
                ).fetchone()
                if current is None:
                    raise HTTPException(status_code=404, detail="Profile not found.")
                old_filename = current["avatar_filename"]
                connection.execute(
                    "UPDATE profiles SET avatar_filename=?, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                    (filename, user["id"]),
                )
        except Exception:
            new_path.unlink(missing_ok=True)
            raise
        if old_filename and old_filename != filename:
            old_path = avatar_dir / old_filename
            if re.fullmatch(r"[a-f0-9]{32}\.jpg", old_filename):
                old_path.unlink(missing_ok=True)
        return {"avatar_url": f"/api/avatars/{user['id']}?v={filename[:8]}"}

    @app.delete("/api/profile/avatar")
    def remove_avatar(user: User):
        with db.transaction() as connection:
            row = connection.execute(
                "SELECT avatar_filename FROM profiles WHERE user_id=?", (user["id"],)
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Profile not found.")
            filename = row["avatar_filename"]
            connection.execute(
                "UPDATE profiles SET avatar_filename=NULL, updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                (user["id"],),
            )
        if filename and re.fullmatch(r"[a-f0-9]{32}\.jpg", filename):
            (avatar_dir / filename).unlink(missing_ok=True)
        return {"avatar_url": None}

    def issue_otp(purpose, email, request, registration=None):
        try:
            secret = otp_secret()
            sender = mailer or mailer_from_env()
        except (OTPConfigurationError, EmailConfigurationError, ValueError):
            raise HTTPException(status_code=503, detail="One-time email verification is not configured.")

        now = int(time.time())
        raw_code = f"{secrets.randbelow(1_000_000):06d}"
        client_ip = request.client.host if request.client else "unknown"
        email_key = otp_rate_digest(secret, f"email:{purpose}", email)
        ip_key = otp_rate_digest(secret, "ip", client_ip)
        challenge_id = None

        with db.transaction() as connection:
            connection.execute("DELETE FROM otp_challenges WHERE expires_at<=?", (now,))
            connection.execute("DELETE FROM otp_rate_limits WHERE created_at<=?", (now - OTP_RATE_WINDOW,))

            if purpose == "register":
                existing = connection.execute(
                    "SELECT email FROM users WHERE lower(email)=?", (email,)
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail="An account with that email already exists.")
                existing = connection.execute(
                    "SELECT id FROM users WHERE lower(username)=?", (registration["username"],)
                ).fetchone()
                if existing:
                    raise HTTPException(status_code=409, detail="That username is already taken.")
                pending = connection.execute(
                    """SELECT email FROM otp_challenges WHERE purpose='register'
                       AND lower(username)=? AND email<>? AND expires_at>?""",
                    (registration["username"], email, now),
                ).fetchone()
                if pending:
                    raise HTTPException(status_code=409, detail="That username is awaiting verification.")

            for kind, key, maximum in (
                ("email", email_key, OTP_EMAIL_LIMIT),
                ("ip", ip_key, OTP_IP_LIMIT),
            ):
                count = connection.execute(
                    "SELECT COUNT(*) FROM otp_rate_limits WHERE subject_kind=? AND subject_hash=?",
                    (kind, key),
                ).fetchone()[0]
                if count >= maximum:
                    raise HTTPException(status_code=429, detail="Please wait before requesting another code.")

            current = connection.execute(
                "SELECT id,last_sent_at FROM otp_challenges WHERE purpose=? AND email=?",
                (purpose, email),
            ).fetchone()
            if current and now - current["last_sent_at"] < OTP_RESEND_COOLDOWN:
                raise HTTPException(status_code=429, detail="Please wait before requesting another code.")

            connection.executemany(
                "INSERT INTO otp_rate_limits(subject_kind,subject_hash,created_at) VALUES(?,?,?)",
                (("email", email_key, now), ("ip", ip_key, now)),
            )
            if purpose == "register" or connection.execute(
                "SELECT id FROM users WHERE lower(email)=?", (email,)
            ).fetchone():
                connection.execute(
                    """INSERT INTO otp_challenges(
                           purpose,email,username,display_name,password_hash,code_hash,
                           expires_at,attempts,last_sent_at,created_at
                       ) VALUES(?,?,?,?,?,?,?,0,?,?)
                       ON CONFLICT(purpose,email) DO UPDATE SET
                           username=excluded.username,display_name=excluded.display_name,
                           password_hash=excluded.password_hash,code_hash=excluded.code_hash,
                           expires_at=excluded.expires_at,attempts=0,
                           last_sent_at=excluded.last_sent_at,created_at=excluded.created_at""",
                    (
                        purpose, email,
                        registration["username"] if registration else None,
                        registration["display_name"] if registration else None,
                        registration["password_hash"] if registration else None,
                        otp_digest(secret, purpose, email, raw_code),
                        now + OTP_SECONDS, now, now,
                    ),
                )
                challenge_id = connection.execute(
                    "SELECT id FROM otp_challenges WHERE purpose=? AND email=?", (purpose, email)
                ).fetchone()["id"]

        try:
            sender.send_otp(email, raw_code, purpose)
        except Exception as error:
            if challenge_id is not None:
                with db.transaction() as connection:
                    connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge_id,))
            provider_code = getattr(error, "code", None)
            if not isinstance(provider_code, int):
                provider_code = getattr(error, "smtp_code", None)
            if not isinstance(provider_code, int):
                provider_code = "unavailable"
            provider_reason = getattr(error, "provider_reason", "unavailable")
            if not isinstance(provider_reason, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", provider_reason):
                provider_reason = "unavailable"
            provider_content_type = getattr(error, "provider_content_type", "unavailable")
            if provider_content_type not in {"json", "html", "text", "other", "unavailable"}:
                provider_content_type = "unavailable"
            LOGGER.error(
                "One-time email delivery failed (error_type=%s, provider_code=%s, "
                "provider_reason=%s, provider_content_type=%s).",
                type(error).__name__,
                provider_code,
                provider_reason,
                provider_content_type,
            )
            raise HTTPException(status_code=503, detail="The code could not be delivered. Please try again later.")
        return {"message": OTP_GENERIC_MESSAGE}

    @app.post("/api/auth/register", status_code=202)
    def register(data: RegisterInput, request: Request):
        return issue_otp(
            "register",
            data.email,
            request,
            registration={
                "username": data.username,
                "display_name": data.display_name,
                "password_hash": hash_password(data.password),
            },
        )

    @app.post("/api/auth/register/resend", status_code=202)
    def resend_registration(data: ForgotInput, request: Request):
        try:
            otp_secret()
        except OTPConfigurationError:
            raise HTTPException(status_code=503, detail="One-time email verification is not configured.")
        with db.locked_connection() as connection:
            pending = connection.execute(
                """SELECT username,display_name,password_hash FROM otp_challenges
                   WHERE purpose='register' AND email=? AND expires_at>?""",
                (data.email, int(time.time())),
            ).fetchone()
        if pending is None:
            raise HTTPException(status_code=400, detail="The pending registration has expired. Start again.")
        return issue_otp(
            "register",
            data.email,
            request,
            registration={
                "username": pending["username"],
                "display_name": pending["display_name"],
                "password_hash": pending["password_hash"],
            },
        )

    @app.post("/api/auth/register/verify", status_code=201)
    def verify_registration(data: RegisterVerifyInput, response: Response):
        try:
            secret = otp_secret()
        except OTPConfigurationError:
            raise HTTPException(status_code=503, detail="One-time email verification is not configured.")
        now = int(time.time())
        result = None
        outcome = None
        try:
            with db.transaction() as connection:
                challenge = connection.execute(
                    "SELECT * FROM otp_challenges WHERE purpose='register' AND email=?",
                    (data.email,),
                ).fetchone()
                if challenge is None:
                    outcome = "expired"
                elif challenge["expires_at"] <= now:
                    connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                    outcome = "expired"
                elif not hmac.compare_digest(
                    challenge["code_hash"], otp_digest(secret, "register", data.email, data.code)
                ):
                    attempts = challenge["attempts"] + 1
                    if attempts >= OTP_MAX_ATTEMPTS:
                        connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                        outcome = "attempts"
                    else:
                        connection.execute(
                            "UPDATE otp_challenges SET attempts=? WHERE id=?", (attempts, challenge["id"])
                        )
                        outcome = "invalid"
                else:
                    email_exists = connection.execute(
                        "SELECT 1 FROM users WHERE lower(email)=?", (data.email,)
                    ).fetchone()
                    username_exists = connection.execute(
                        "SELECT 1 FROM users WHERE lower(username)=?", (challenge["username"],)
                    ).fetchone()
                    if email_exists or username_exists:
                        connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                        outcome = "conflict"
                    else:
                        cursor = connection.execute(
                            "INSERT INTO users(email,username,password_hash) VALUES(?,?,?)",
                            (data.email, challenge["username"], challenge["password_hash"]),
                        )
                        user_id = cursor.lastrowid
                        connection.execute(
                            "INSERT INTO profiles(user_id,display_name) VALUES(?,?)",
                            (user_id, challenge["display_name"]),
                        )
                        token = new_session_token()
                        connection.execute(
                            "INSERT INTO sessions(token_hash,user_id,expires_at) VALUES(?,?,?)",
                            (token_digest(token), user_id, now + SESSION_SECONDS),
                        )
                        connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                        result = {"user_id": user_id, "token": token}
        except sqlite3.IntegrityError:
            with db.transaction() as connection:
                connection.execute(
                    "DELETE FROM otp_challenges WHERE purpose='register' AND email=?", (data.email,)
                )
            outcome = "conflict"

        if outcome == "invalid":
            raise HTTPException(status_code=400, detail="The code is incorrect.")
        if outcome == "attempts":
            raise HTTPException(status_code=429, detail="Too many incorrect codes. Request a new code.")
        if outcome == "conflict":
            raise HTTPException(status_code=409, detail="The email or username is no longer available.")
        if result is None:
            raise HTTPException(status_code=400, detail="The code is invalid or expired.")
        set_session(response, result["token"])
        return {"user": db.profile_for(result["user_id"]), "token": result["token"]}

    @app.post("/api/auth/login")
    def login(data: LoginInput, response: Response):
        with db.locked_connection() as connection:
            row = connection.execute(
                "SELECT id, password_hash FROM users WHERE email = ?", (data.email,)
            ).fetchone()
        if row is None or not verify_password(data.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Email or password is incorrect.")
        token = new_session_token()
        with db.transaction() as connection:
            connection.execute(
                "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                (token_digest(token), row["id"], int(time.time()) + SESSION_SECONDS),
            )
        set_session(response, token)
        return {"user": db.profile_for(row["id"]), "token": token}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response):
        authorization = request.headers.get("authorization", "")
        token = None
        if authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        if not token:
            token = request.cookies.get(SESSION_COOKIE)
        if token:
            with db.transaction() as connection:
                connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_digest(token),))
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
        return {"ok": True}

    @app.post("/api/auth/forgot-password", status_code=202)
    def forgot_password(data: ForgotInput, request: Request):
        return issue_otp("password_reset", data.email, request)

    @app.post("/api/auth/reset-password")
    def reset_password(data: PasswordResetInput):
        try:
            secret = otp_secret()
        except OTPConfigurationError:
            raise HTTPException(status_code=503, detail="One-time email verification is not configured.")
        now = int(time.time())
        outcome = None
        with db.transaction() as connection:
            challenge = connection.execute(
                "SELECT * FROM otp_challenges WHERE purpose='password_reset' AND email=?",
                (data.email,),
            ).fetchone()
            if challenge is None:
                outcome = "invalid"
            elif challenge["expires_at"] <= now:
                connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                outcome = "invalid"
            elif not hmac.compare_digest(
                challenge["code_hash"], otp_digest(secret, "password_reset", data.email, data.code)
            ):
                attempts = challenge["attempts"] + 1
                if attempts >= OTP_MAX_ATTEMPTS:
                    connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                    outcome = "attempts"
                else:
                    connection.execute(
                        "UPDATE otp_challenges SET attempts=? WHERE id=?", (attempts, challenge["id"])
                    )
                    outcome = "invalid"
            else:
                user = connection.execute("SELECT id FROM users WHERE lower(email)=?", (data.email,)).fetchone()
                if user is None:
                    connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                    outcome = "invalid"
                else:
                    connection.execute(
                        "UPDATE users SET password_hash=? WHERE id=?",
                        (hash_password(data.password), user["id"]),
                    )
                    connection.execute("DELETE FROM otp_challenges WHERE id=?", (challenge["id"],))
                    connection.execute("DELETE FROM password_resets WHERE user_id=?", (user["id"],))
                    connection.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
        if outcome == "attempts":
            raise HTTPException(status_code=429, detail="Too many incorrect codes. Request a new code.")
        if outcome:
            raise HTTPException(status_code=400, detail="The code is invalid or expired.")
        return {"message": "Password updated. Sign in with your new password."}

    @app.get("/api/me")
    def me(user: User):
        return {"user": db.profile_for(user["id"])}

    @app.get("/api/profile")
    def profile(user: User):
        return {"user": db.profile_for(user["id"])}

    @app.get("/api/account/export")
    def export_account(user: User):
        with db.locked_connection() as connection:
            profile_data = db.profile_for(user["id"])
            posts = connection.execute(
                """SELECT id,body,visibility,created_at FROM posts
                   WHERE user_id=? ORDER BY id""",
                (user["id"],),
            ).fetchall()
            replies = connection.execute(
                """SELECT r.id,r.post_id,r.body,r.created_at,u.username AS post_author
                   FROM replies r JOIN posts p ON p.id=r.post_id
                   JOIN users u ON u.id=p.user_id
                   WHERE r.user_id=? ORDER BY r.id""",
                (user["id"],),
            ).fetchall()
            reactions = connection.execute(
                "SELECT post_id,created_at FROM reactions WHERE user_id=? ORDER BY post_id",
                (user["id"],),
            ).fetchall()
            bookmarks = connection.execute(
                "SELECT post_id,created_at FROM bookmarks WHERE user_id=? ORDER BY post_id",
                (user["id"],),
            ).fetchall()
            followers = connection.execute(
                """SELECT u.username,p.display_name,f.created_at FROM follows f
                   JOIN users u ON u.id=f.follower_id JOIN profiles p ON p.user_id=u.id
                   WHERE f.followed_id=? ORDER BY u.username""",
                (user["id"],),
            ).fetchall()
            following = connection.execute(
                """SELECT u.username,p.display_name,f.created_at FROM follows f
                   JOIN users u ON u.id=f.followed_id JOIN profiles p ON p.user_id=u.id
                   WHERE f.follower_id=? ORDER BY u.username""",
                (user["id"],),
            ).fetchall()
            conversation_rows = connection.execute(
                """SELECT c.id,c.created_at FROM conversations c
                   JOIN conversation_participants cp ON cp.conversation_id=c.id
                   WHERE cp.user_id=? ORDER BY c.id""",
                (user["id"],),
            ).fetchall()
            conversations = []
            for conversation in conversation_rows:
                participants = connection.execute(
                    """SELECT u.username,p.display_name FROM conversation_participants cp
                       JOIN users u ON u.id=cp.user_id JOIN profiles p ON p.user_id=u.id
                       WHERE cp.conversation_id=? ORDER BY u.username""",
                    (conversation["id"],),
                ).fetchall()
                messages = connection.execute(
                    """SELECT m.sender_id,u.username,p.display_name,m.body,m.created_at
                       FROM messages m JOIN users u ON u.id=m.sender_id
                       JOIN profiles p ON p.user_id=u.id
                       WHERE m.conversation_id=? ORDER BY m.id""",
                    (conversation["id"],),
                ).fetchall()
                conversations.append({
                    "id": conversation["id"],
                    "created_at": conversation["created_at"],
                    "participants": [dict(row) for row in participants],
                    "messages": [dict(row) for row in messages],
                })
            notifications = connection.execute(
                """SELECT n.kind,n.post_id,n.created_at,n.read_at,
                          u.username AS actor_username,p.display_name AS actor_display_name
                   FROM notifications n JOIN users u ON u.id=n.actor_id
                   JOIN profiles p ON p.user_id=u.id
                   WHERE n.user_id=? ORDER BY n.id""",
                (user["id"],),
            ).fetchall()
        export = {
            "account": profile_data,
            "posts": [dict(row) for row in posts],
            "replies": [dict(row) for row in replies],
            "reactions": [dict(row) for row in reactions],
            "bookmarks": [dict(row) for row in bookmarks],
            "followers": [dict(row) for row in followers],
            "following": [dict(row) for row in following],
            "conversations": conversations,
            "notifications_received": [dict(row) for row in notifications],
        }
        return Response(
            content=json.dumps(export, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="zorlii-account-export.json"'},
        )

    @app.delete("/api/account")
    def delete_account(data: AccountDeleteInput, user: User, response: Response):
        with db.locked_connection() as connection:
            row = connection.execute(
                """SELECT u.password_hash,p.avatar_filename FROM users u
                   JOIN profiles p ON p.user_id=u.id WHERE u.id=?""",
                (user["id"],),
            ).fetchone()
        if row is None or not verify_password(data.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Password is incorrect.")
        with db.transaction() as connection:
            connection.execute("DELETE FROM users WHERE id=?", (user["id"],))
            connection.execute(
                """DELETE FROM conversations WHERE NOT EXISTS(
                       SELECT 1 FROM conversation_participants cp
                       WHERE cp.conversation_id=conversations.id
                   )"""
            )
        if row["avatar_filename"] and re.fullmatch(r"[a-f0-9]{32}\.jpg", row["avatar_filename"]):
            (avatar_dir / row["avatar_filename"]).unlink(missing_ok=True)
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
        return {"message": "Your account and account-owned content have been permanently deleted."}

    @app.patch("/api/profile")
    def update_profile(data: ProfileUpdate, user: User):
        changes = data.model_dump(exclude_unset=True)
        if changes:
            if "interests" in changes:
                changes["interests"] = json.dumps(changes["interests"])
            assignments = [f"{key} = ?" for key in changes]
            values = [int(value) if key.endswith("_consent") else value for key, value in changes.items()]
            assignments.append("updated_at = CURRENT_TIMESTAMP")
            values.append(user["id"])
            with db.transaction() as connection:
                connection.execute(f"UPDATE profiles SET {', '.join(assignments)} WHERE user_id = ?", values)
        return {"user": db.profile_for(user["id"])}

    @app.get("/api/users/{username}")
    def get_public_profile(username: str, user: User):
        with db.locked_connection() as connection:
            row = connection.execute(
                """SELECT u.id,u.username,u.created_at,p.display_name,p.bio,p.avatar_filename
                   FROM users u JOIN profiles p ON p.user_id=u.id WHERE u.username=?""",
                (username.lower().lstrip("@"),),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Profile not found.")
            result = public_user(row)
            result["following"] = bool(connection.execute(
                "SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (user["id"], row["id"])
            ).fetchone())
            result["follower_count"] = connection.execute(
                "SELECT COUNT(*) FROM follows WHERE followed_id=?", (row["id"],)
            ).fetchone()[0]
            result["following_count"] = connection.execute(
                "SELECT COUNT(*) FROM follows WHERE follower_id=?", (row["id"],)
            ).fetchone()[0]
        return {"user": result}

    @app.get("/api/users/{username}/posts")
    def profile_posts(username: str, user: User, limit: int = Query(default=30, ge=1, le=100)):
        with db.locked_connection() as connection:
            target = connection.execute("SELECT id FROM users WHERE username=?", (username.lower().lstrip("@"),)).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="Profile not found.")
            ids = connection.execute(
                """SELECT p.id FROM posts p WHERE p.user_id=? AND
                   (p.user_id=? OR p.visibility='public' OR
                    (p.visibility='followers' AND EXISTS(
                       SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=p.user_id)))
                   ORDER BY p.id DESC LIMIT ?""",
                (target["id"], user["id"], user["id"], limit),
            ).fetchall()
            posts = []
            for item in ids:
                row = visible_post(connection, item["id"], user["id"])
                if row is not None:
                    posts.append(post_payload(row))
        return {"posts": posts}

    def relationship_list(username, relationship, limit, offset):
        target_column = "followed_id" if relationship == "followers" else "follower_id"
        source_column = "follower_id" if relationship == "followers" else "followed_id"
        with db.locked_connection() as connection:
            target = connection.execute(
                "SELECT id FROM users WHERE username=?",
                (username.lower().lstrip("@"),),
            ).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="Profile not found.")
            total = connection.execute(
                f"SELECT COUNT(*) FROM follows WHERE {target_column}=?",
                (target["id"],),
            ).fetchone()[0]
            rows = connection.execute(
                f"""SELECT u.id,u.username,u.created_at,p.display_name,p.bio,p.avatar_filename
                    FROM follows f JOIN users u ON u.id=f.{source_column}
                    JOIN profiles p ON p.user_id=u.id
                    WHERE f.{target_column}=?
                    ORDER BY f.created_at DESC,u.id DESC LIMIT ? OFFSET ?""",
                (target["id"], limit, offset),
            ).fetchall()
        return {"users": [public_user(row) for row in rows], "count": total, "limit": limit, "offset": offset}

    @app.get("/api/users/{username}/followers")
    def list_followers(
        username: str,
        user: User,
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return relationship_list(username, "followers", limit, offset)

    @app.get("/api/users/{username}/following")
    def list_following(
        username: str,
        user: User,
        limit: int = Query(default=30, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return relationship_list(username, "following", limit, offset)

    @app.post("/api/users/{username}/follow")
    def toggle_follow(username: str, user: User):
        with db.transaction() as connection:
            target = connection.execute("SELECT id FROM users WHERE username=?", (username.lower().lstrip("@"),)).fetchone()
            if target is None:
                raise HTTPException(status_code=404, detail="Profile not found.")
            if target["id"] == user["id"]:
                raise HTTPException(status_code=400, detail="You cannot follow yourself.")
            existing = connection.execute(
                "SELECT 1 FROM follows WHERE follower_id=? AND followed_id=?", (user["id"], target["id"])
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM follows WHERE follower_id=? AND followed_id=?", (user["id"], target["id"]))
                following = False
            else:
                connection.execute(
                    "INSERT INTO follows(follower_id,followed_id) VALUES(?,?)", (user["id"], target["id"])
                )
                connection.execute(
                    "INSERT INTO notifications(user_id,actor_id,kind) VALUES(?,?,'follow')",
                    (target["id"], user["id"]),
                )
                following = True
        return {"following": following}

    @app.post("/api/posts", status_code=201)
    def create_post(data: PostInput, user: User):
        with db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO posts(user_id,body,visibility) VALUES(?,?,?)",
                (user["id"], data.body, data.visibility),
            )
            post_id = cursor.lastrowid
            row = visible_post(connection, post_id, user["id"])
        return {"post": post_payload(row)}

    @app.get("/api/feed")
    def feed(user: User, scope: str = "all", limit: int = Query(default=30, ge=1, le=100), offset: int = Query(default=0, ge=0)):
        if scope not in {"all", "following", "bookmarks"}:
            raise HTTPException(status_code=422, detail="Unknown feed scope.")
        with db.locked_connection() as connection:
            where = """(p.user_id=? OR p.visibility='public' OR
                        (p.visibility='followers' AND EXISTS(
                            SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=p.user_id)))"""
            params = [user["id"], user["id"]]
            if scope == "following":
                where += """ AND (p.user_id=? OR EXISTS(
                             SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=p.user_id))"""
                params.extend((user["id"], user["id"]))
            elif scope == "bookmarks":
                where += " AND EXISTS(SELECT 1 FROM bookmarks b WHERE b.user_id=? AND b.post_id=p.id)"
                params.append(user["id"])
            params.extend((limit, offset))
            ids = connection.execute(
                f"SELECT p.id FROM posts p WHERE {where} ORDER BY p.id DESC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
            results = []
            for item in ids:
                row = visible_post(connection, item["id"], user["id"])
                if row is None:
                    continue
                results.append(post_payload(row))
            return {"posts": results, "limit": limit, "offset": offset}

    @app.get("/api/posts/{post_id}")
    def get_post(post_id: int, user: User):
        with db.locked_connection() as connection:
            row = visible_post(connection, post_id, user["id"])
            if row is None:
                raise HTTPException(status_code=404, detail="Post not found.")
            replies = connection.execute(
                """SELECT r.id,r.body,r.created_at,u.id AS user_id,u.username,p.display_name,p.avatar_filename
                   FROM replies r JOIN users u ON u.id=r.user_id JOIN profiles p ON p.user_id=u.id
                   WHERE r.post_id=? ORDER BY r.id LIMIT 100""",
                (post_id,),
            ).fetchall()
        return {"post": post_payload(row), "replies": [
            {"id": r["id"], "body": r["body"], "created_at": r["created_at"],
             "author": {
                 "id": r["user_id"], "username": r["username"], "display_name": r["display_name"],
                 "avatar_url": f"/api/avatars/{r['user_id']}" if r["avatar_filename"] else None,
             }}
            for r in replies
        ]}

    @app.delete("/api/posts/{post_id}")
    def delete_post(post_id: int, user: User):
        with db.transaction() as connection:
            cursor = connection.execute("DELETE FROM posts WHERE id=? AND user_id=?", (post_id, user["id"]))
            if cursor.rowcount == 0:
                exists = connection.execute("SELECT 1 FROM posts WHERE id=?", (post_id,)).fetchone()
                raise HTTPException(status_code=404, detail="Post not found or unavailable.")
        return {"ok": True}

    @app.post("/api/posts/{post_id}/replies", status_code=201)
    def create_reply(post_id: int, data: MessageInput, user: User):
        with db.transaction() as connection:
            post = visible_post(connection, post_id, user["id"])
            if post is None:
                raise HTTPException(status_code=404, detail="Post not found.")
            cursor = connection.execute(
                "INSERT INTO replies(post_id,user_id,body) VALUES(?,?,?)", (post_id, user["id"], data.body)
            )
            if post["user_id"] != user["id"]:
                connection.execute(
                    "INSERT INTO notifications(user_id,actor_id,kind,post_id) VALUES(?,?,'reply',?)",
                    (post["user_id"], user["id"], post_id),
                )
            reply_id = cursor.lastrowid
        return {"id": reply_id, "body": data.body, "post_id": post_id}

    @app.delete("/api/replies/{reply_id}")
    def delete_reply(reply_id: int, user: User):
        with db.transaction() as connection:
            cursor = connection.execute(
                "DELETE FROM replies WHERE id=? AND user_id=?", (reply_id, user["id"])
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Reply not found or unavailable.")
        return {"ok": True}

    @app.post("/api/posts/{post_id}/reaction")
    def toggle_reaction(post_id: int, user: User):
        with db.transaction() as connection:
            post = visible_post(connection, post_id, user["id"])
            if post is None:
                raise HTTPException(status_code=404, detail="Post not found.")
            existing = connection.execute(
                "SELECT 1 FROM reactions WHERE user_id=? AND post_id=?", (user["id"], post_id)
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM reactions WHERE user_id=? AND post_id=?", (user["id"], post_id))
                reacted = False
            else:
                connection.execute("INSERT INTO reactions(user_id,post_id) VALUES(?,?)", (user["id"], post_id))
                if post["user_id"] != user["id"]:
                    connection.execute(
                        "INSERT INTO notifications(user_id,actor_id,kind,post_id) VALUES(?,?,'reaction',?)",
                        (post["user_id"], user["id"], post_id),
                    )
                reacted = True
        return {"reacted": reacted}

    @app.post("/api/posts/{post_id}/bookmark")
    def toggle_bookmark(post_id: int, user: User):
        with db.transaction() as connection:
            if visible_post(connection, post_id, user["id"]) is None:
                raise HTTPException(status_code=404, detail="Post not found.")
            existing = connection.execute(
                "SELECT 1 FROM bookmarks WHERE user_id=? AND post_id=?", (user["id"], post_id)
            ).fetchone()
            if existing:
                connection.execute("DELETE FROM bookmarks WHERE user_id=? AND post_id=?", (user["id"], post_id))
                saved = False
            else:
                connection.execute("INSERT INTO bookmarks(user_id,post_id) VALUES(?,?)", (user["id"], post_id))
                saved = True
        return {"bookmarked": saved}

    @app.get("/api/search")
    def search(user: User, q: str = Query(min_length=1, max_length=120)):
        term = f"%{q.strip()}%"
        with db.locked_connection() as connection:
            people = connection.execute(
                """SELECT u.id,u.username,u.created_at,p.display_name,p.bio,p.avatar_filename FROM users u
                   JOIN profiles p ON p.user_id=u.id WHERE u.username LIKE ? OR p.display_name LIKE ?
                   ORDER BY u.username LIMIT 30""",
                (term, term),
            ).fetchall()
            post_ids = connection.execute(
                """SELECT p.id FROM posts p WHERE p.body LIKE ? AND
                   (p.user_id=? OR p.visibility='public' OR
                    (p.visibility='followers' AND EXISTS(
                       SELECT 1 FROM follows f WHERE f.follower_id=? AND f.followed_id=p.user_id)))
                   ORDER BY p.id DESC LIMIT 100""",
                (term, user["id"], user["id"]),
            ).fetchall()
            posts = []
            for item in post_ids:
                row = visible_post(connection, item["id"], user["id"])
                if row is not None:
                    posts.append(post_payload(row))
        return {"people": [public_user(p) for p in people], "posts": posts[:30]}

    @app.get("/api/conversations")
    def conversations(user: User):
        with db.locked_connection() as connection:
            rows = connection.execute(
                """SELECT c.id,c.created_at,
                   (SELECT m.body FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message,
                   (SELECT m.created_at FROM messages m WHERE m.conversation_id=c.id ORDER BY m.id DESC LIMIT 1) AS last_message_at
                   FROM conversations c JOIN conversation_participants cp ON cp.conversation_id=c.id
                   WHERE cp.user_id=? ORDER BY COALESCE(last_message_at,c.created_at) DESC LIMIT 100""",
                (user["id"],),
            ).fetchall()
            result = []
            for row in rows:
                participants = connection.execute(
                    """SELECT u.id,u.username,p.display_name,p.avatar_filename FROM conversation_participants cp
                       JOIN users u ON u.id=cp.user_id JOIN profiles p ON p.user_id=u.id
                       WHERE cp.conversation_id=? AND cp.user_id<>?""",
                    (row["id"], user["id"]),
                ).fetchall()
                result.append({"id": row["id"], "last_message": row["last_message"],
                               "last_message_at": row["last_message_at"], "participants": [
                                   {
                                       "id": p["id"], "username": p["username"], "display_name": p["display_name"],
                                       "avatar_url": f"/api/avatars/{p['id']}?v={p['avatar_filename'][:8]}"
                                       if p["avatar_filename"] else None,
                                   }
                                   for p in participants
                               ]})
        return {"conversations": result}

    @app.post("/api/conversations", status_code=201)
    def create_conversation(data: ConversationInput, user: User):
        with db.transaction() as connection:
            recipient = connection.execute("SELECT id FROM users WHERE username=?", (data.username,)).fetchone()
            if recipient is None:
                raise HTTPException(status_code=404, detail="Account not found.")
            if recipient["id"] == user["id"]:
                raise HTTPException(status_code=400, detail="Choose another account.")
            existing = connection.execute(
                """SELECT c.id FROM conversations c
                   WHERE (SELECT COUNT(*) FROM conversation_participants cp WHERE cp.conversation_id=c.id)=2
                   AND EXISTS(SELECT 1 FROM conversation_participants cp WHERE cp.conversation_id=c.id AND cp.user_id=?)
                   AND EXISTS(SELECT 1 FROM conversation_participants cp WHERE cp.conversation_id=c.id AND cp.user_id=?)""",
                (user["id"], recipient["id"]),
            ).fetchone()
            if existing:
                return {"id": existing["id"]}
            cursor = connection.execute("INSERT INTO conversations DEFAULT VALUES")
            conversation_id = cursor.lastrowid
            connection.executemany(
                "INSERT INTO conversation_participants(conversation_id,user_id) VALUES(?,?)",
                ((conversation_id, user["id"]), (conversation_id, recipient["id"])),
            )
        return {"id": conversation_id}

    def require_conversation_participant(connection, conversation_id, user_id):
        if not connection.execute(
            "SELECT 1 FROM conversation_participants WHERE conversation_id=? AND user_id=?",
            (conversation_id, user_id),
        ).fetchone():
            raise HTTPException(status_code=404, detail="Conversation not found.")

    @app.get("/api/conversations/{conversation_id}/messages")
    def list_messages(conversation_id: int, user: User, limit: int = Query(default=100, ge=1, le=100)):
        with db.locked_connection() as connection:
            require_conversation_participant(connection, conversation_id, user["id"])
            rows = connection.execute(
                """SELECT m.id,m.body,m.created_at,m.sender_id,u.username,p.display_name,p.avatar_filename
                   FROM messages m JOIN users u ON u.id=m.sender_id JOIN profiles p ON p.user_id=u.id
                   WHERE m.conversation_id=? ORDER BY m.id DESC LIMIT ?""",
                (conversation_id, limit),
            ).fetchall()
        return {"messages": [
            {"id": r["id"], "body": r["body"], "created_at": r["created_at"], "sender_id": r["sender_id"],
             "author": {
                 "username": r["username"], "display_name": r["display_name"],
                 "avatar_url": f"/api/avatars/{r['sender_id']}?v={r['avatar_filename'][:8]}"
                 if r["avatar_filename"] else None,
             }}
            for r in reversed(rows)
        ]}

    @app.post("/api/conversations/{conversation_id}/messages", status_code=201)
    def send_message(conversation_id: int, data: MessageInput, user: User):
        with db.transaction() as connection:
            require_conversation_participant(connection, conversation_id, user["id"])
            cursor = connection.execute(
                "INSERT INTO messages(conversation_id,sender_id,body) VALUES(?,?,?)",
                (conversation_id, user["id"], data.body),
            )
        return {"id": cursor.lastrowid, "body": data.body, "sender_id": user["id"]}

    @app.patch("/api/conversations/{conversation_id}/messages/{message_id}")
    def edit_message(conversation_id: int, message_id: int, data: MessageInput, user: User):
        with db.transaction() as connection:
            require_conversation_participant(connection, conversation_id, user["id"])
            cursor = connection.execute(
                "UPDATE messages SET body=? WHERE id=? AND conversation_id=? AND sender_id=?",
                (data.body, message_id, conversation_id, user["id"]),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Message not found or unavailable.")
        return {"id": message_id, "body": data.body}

    @app.delete("/api/conversations/{conversation_id}/messages/{message_id}")
    def delete_message(conversation_id: int, message_id: int, user: User):
        with db.transaction() as connection:
            require_conversation_participant(connection, conversation_id, user["id"])
            cursor = connection.execute(
                "DELETE FROM messages WHERE id=? AND conversation_id=? AND sender_id=?",
                (message_id, conversation_id, user["id"]),
            )
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="Message not found or unavailable.")
        return {"ok": True}

    @app.get("/api/notifications")
    def notifications(user: User):
        with db.locked_connection() as connection:
            unread_count = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL",
                (user["id"],),
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT n.id,n.actor_id,n.kind,n.post_id,n.created_at,n.read_at,
                          u.username,p.display_name,p.avatar_filename
                   FROM notifications n JOIN users u ON u.id=n.actor_id JOIN profiles p ON p.user_id=u.id
                   WHERE n.user_id=? ORDER BY n.id DESC LIMIT 100""",
                (user["id"],),
            ).fetchall()
        return {"notifications": [
            {"id": r["id"], "kind": r["kind"], "post_id": r["post_id"], "created_at": r["created_at"],
             "read": bool(r["read_at"]), "actor": {
                 "username": r["username"], "display_name": r["display_name"],
                 "avatar_url": f"/api/avatars/{r['actor_id']}?v={r['avatar_filename'][:8]}"
                 if r["avatar_filename"] else None,
             }}
            for r in rows
        ], "unread_count": unread_count}

    @app.patch("/api/notifications/{notification_id}/read")
    def mark_notification_read(notification_id: int, user: User):
        with db.transaction() as connection:
            row = connection.execute(
                "SELECT read_at FROM notifications WHERE id=? AND user_id=?",
                (notification_id, user["id"]),
            ).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="Notification not found.")
            if row["read_at"] is None:
                connection.execute(
                    "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?",
                    (notification_id, user["id"]),
                )
        return {"id": notification_id, "read": True}

    @app.post("/api/notifications/read")
    def mark_all_notifications_read(user: User):
        with db.transaction() as connection:
            cursor = connection.execute(
                "UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE user_id=? AND read_at IS NULL",
                (user["id"],),
            )
        return {"updated": cursor.rowcount}

    @app.get("/api/recommendations")
    def recommendations(user: User):
        profile_data = db.profile_for(user["id"])
        if not profile_data["recommendations_consent"]:
            raise HTTPException(status_code=403, detail="Recommendations are off until you opt in.")
        with db.locked_connection() as connection:
            followed = connection.execute("SELECT followed_id FROM follows WHERE follower_id=?", (user["id"],)).fetchall()
            following_ids = [row["followed_id"] for row in followed]
            placeholders = ",".join("?" for _ in following_ids) or "-1"
            params = [user["id"], *following_ids]
            rows = connection.execute(
                f"""SELECT u.id,u.username,u.created_at,p.display_name,p.bio,p.avatar_filename,
                           GROUP_CONCAT(posts.body, ' ') AS text
                    FROM users u JOIN profiles p ON p.user_id=u.id
                    JOIN posts ON posts.user_id=u.id AND posts.visibility='public'
                    WHERE u.id<>? AND u.id NOT IN ({placeholders})
                    GROUP BY u.id ORDER BY u.id DESC LIMIT 50""",
                params,
            ).fetchall()
        profile_text = " ".join(profile_data["interests"] + [profile_data["bio"]])
        return {
            "method": "local TF-IDF over opted-in profile and real public posts",
            "recommendations": recommend([
                {**public_user(row), "text": row["text"]} for row in rows
            ], profile_text),
        }

    @app.post("/api/context")
    def context_assistance(data: ContextInput, user: User):
        profile_data = db.profile_for(user["id"])
        if not data.consent_for_this_request:
            raise HTTPException(status_code=403, detail="Confirm local use for this request.")
        if not profile_data["context_assistance_consent"]:
            raise HTTPException(status_code=403, detail="Local context assistance is off until you opt in.")
        return {
            "method": "local extractive selection",
            "notice": "Original sentences selected from the supplied text; no generated answer.",
            "sentences": extractive_context(data.text, data.question),
            "stored": False,
        }

    return app


app = new_app()

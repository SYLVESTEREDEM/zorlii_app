import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class Database:
    def __init__(self, path=None):
        configured_path = path or os.environ.get("ZORLII_DB_PATH")
        self.path = Path(configured_path) if configured_path else Path(__file__).with_name("data") / "zorlii.sqlite3"
        self._lock = threading.RLock()
        self._connection = None

    def connect(self):
        with self._lock:
            if self._connection is None:
                if str(self.path) != ":memory:":
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(
                    str(self.path), check_same_thread=False, timeout=10
                )
                self._connection.row_factory = sqlite3.Row
                self._connection.execute("PRAGMA foreign_keys = ON")
                self._connection.execute("PRAGMA busy_timeout = 10000")
                self.initialize()
            return self._connection

    def initialize(self):
        with self._lock:
            connection = self._connection
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,
                    bio TEXT NOT NULL DEFAULT '',
                    avatar_filename TEXT,
                    interests TEXT NOT NULL DEFAULT '[]',
                    recommendations_consent INTEGER NOT NULL DEFAULT 0,
                    context_assistance_consent INTEGER NOT NULL DEFAULT 0,
                    onboarding_completed INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS password_resets (
                    token_hash TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS password_resets_user_id ON password_resets(user_id);
                CREATE TABLE IF NOT EXISTS reset_rate_limits (
                    subject_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reset_rate_limits_created ON reset_rate_limits(created_at);
                CREATE TABLE IF NOT EXISTS otp_challenges (
                    id INTEGER PRIMARY KEY,
                    purpose TEXT NOT NULL CHECK (purpose IN ('register', 'password_reset')),
                    email TEXT NOT NULL,
                    username TEXT,
                    display_name TEXT,
                    password_hash TEXT,
                    code_hash TEXT NOT NULL,
                    expires_at INTEGER NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_sent_at INTEGER NOT NULL,
                    created_at INTEGER NOT NULL,
                    UNIQUE (purpose, email)
                );
                CREATE INDEX IF NOT EXISTS otp_challenges_expiry ON otp_challenges(expires_at);
                CREATE TABLE IF NOT EXISTS otp_rate_limits (
                    subject_kind TEXT NOT NULL,
                    subject_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS otp_rate_limits_created ON otp_rate_limits(created_at);
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    visibility TEXT NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','followers','private')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS posts_created ON posts(id DESC);
                CREATE INDEX IF NOT EXISTS posts_user ON posts(user_id, id DESC);
                CREATE TABLE IF NOT EXISTS replies (
                    id INTEGER PRIMARY KEY,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS replies_post ON replies(post_id, id);
                CREATE TABLE IF NOT EXISTS reactions (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, post_id)
                );
                CREATE TABLE IF NOT EXISTS bookmarks (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, post_id)
                );
                CREATE TABLE IF NOT EXISTS follows (
                    follower_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    followed_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (follower_id, followed_id),
                    CHECK (follower_id <> followed_id)
                );
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS conversation_participants (
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    PRIMARY KEY (conversation_id, user_id)
                );
                CREATE INDEX IF NOT EXISTS conversation_participant_user ON conversation_participants(user_id);
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY,
                    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS messages_conversation ON messages(conversation_id, id);
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK (kind IN ('follow','reply','reaction')),
                    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, id DESC);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
            if "username" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN username TEXT")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users(username) WHERE username IS NOT NULL")
            profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(profiles)")}
            if "avatar_filename" not in profile_columns:
                connection.execute("ALTER TABLE profiles ADD COLUMN avatar_filename TEXT")
            connection.execute(
                "UPDATE users SET username = 'member' || id WHERE username IS NULL"
            )
            connection.commit()

    @contextmanager
    def locked_connection(self):
        with self._lock:
            yield self.connect()

    @contextmanager
    def transaction(self):
        with self._lock:
            connection = self.connect()
            with connection:
                yield connection

    def profile_for(self, user_id):
        with self.locked_connection() as connection:
            row = connection.execute(
                """SELECT u.id, u.email, u.username, u.created_at, p.display_name, p.bio, p.avatar_filename, p.interests,
                          p.recommendations_consent, p.context_assistance_consent,
                          p.onboarding_completed
                   FROM users u JOIN profiles p ON p.user_id = u.id WHERE u.id = ?""",
                (user_id,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["interests"] = json.loads(result["interests"])
        result["avatar_url"] = (
            f"/api/avatars/{result['id']}?v={result['avatar_filename'][:8]}"
            if result["avatar_filename"] else None
        )
        result.pop("avatar_filename", None)
        result["recommendations_consent"] = bool(result["recommendations_consent"])
        result["context_assistance_consent"] = bool(result["context_assistance_consent"])
        result["onboarding_completed"] = bool(result["onboarding_completed"])
        return result

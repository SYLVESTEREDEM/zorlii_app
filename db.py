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
                    terms_accepted_at TEXT,
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
                    quoted_post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL,
                    quoted_reply_id INTEGER REFERENCES replies(id) ON DELETE SET NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS posts_created ON posts(id DESC);
                CREATE INDEX IF NOT EXISTS posts_user ON posts(user_id, id DESC);
                CREATE TABLE IF NOT EXISTS post_media (
                    id INTEGER PRIMARY KEY,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS post_media_post ON post_media(post_id, position, id);
                CREATE TABLE IF NOT EXISTS replies (
                    id INTEGER PRIMARY KEY,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS replies_post ON replies(post_id, id);
                CREATE TABLE IF NOT EXISTS reply_media (
                    id INTEGER PRIMARY KEY,
                    reply_id INTEGER NOT NULL REFERENCES replies(id) ON DELETE CASCADE,
                    filename TEXT NOT NULL UNIQUE,
                    media_type TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS reply_media_reply ON reply_media(reply_id, position, id);
                CREATE TABLE IF NOT EXISTS reply_reactions (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    reply_id INTEGER NOT NULL REFERENCES replies(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, reply_id)
                );
                CREATE TABLE IF NOT EXISTS reply_reposts (
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    reply_id INTEGER NOT NULL REFERENCES replies(id) ON DELETE CASCADE,
                    share_post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, reply_id)
                );
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
                CREATE TABLE IF NOT EXISTS post_reposts (
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
                CREATE TABLE IF NOT EXISTS blocked_users (
                    blocker_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    blocked_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (blocker_id, blocked_id),
                    CHECK (blocker_id <> blocked_id)
                );
                CREATE INDEX IF NOT EXISTS blocked_users_blocked ON blocked_users(blocked_id, blocker_id);
                CREATE TABLE IF NOT EXISTS content_reports (
                    id INTEGER PRIMARY KEY,
                    reporter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    target_type TEXT NOT NULL CHECK (target_type IN ('post','user')),
                    post_id INTEGER,
                    target_user_id INTEGER,
                    reason TEXT NOT NULL CHECK (reason IN ('harassment','hate','sexual','spam','self_harm','other')),
                    details TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','actioned','dismissed')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reviewed_at TEXT,
                    CHECK (
                        (target_type='post' AND post_id IS NOT NULL AND target_user_id IS NULL) OR
                        (target_type='user' AND post_id IS NULL AND target_user_id IS NOT NULL)
                    )
                );
                CREATE INDEX IF NOT EXISTS content_reports_open ON content_reports(status, id DESC);
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
                    reply_id INTEGER,
                    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
                    activity_kind TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    read_at TEXT
                );
                CREATE INDEX IF NOT EXISTS notifications_user ON notifications(user_id, id DESC);
                CREATE TABLE IF NOT EXISTS push_tokens (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    platform TEXT NOT NULL CHECK (platform IN ('ios','android')),
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS push_tokens_user ON push_tokens(user_id);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(users)")}
            if "username" not in columns:
                connection.execute("ALTER TABLE users ADD COLUMN username TEXT")
            connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_username ON users(username) WHERE username IS NOT NULL")
            profile_columns = {row["name"] for row in connection.execute("PRAGMA table_info(profiles)")}
            if "avatar_filename" not in profile_columns:
                connection.execute("ALTER TABLE profiles ADD COLUMN avatar_filename TEXT")
            if "terms_accepted_at" not in profile_columns:
                connection.execute("ALTER TABLE profiles ADD COLUMN terms_accepted_at TEXT")
            post_columns = {row["name"] for row in connection.execute("PRAGMA table_info(posts)")}
            if "quoted_post_id" not in post_columns:
                connection.execute(
                    "ALTER TABLE posts ADD COLUMN quoted_post_id INTEGER REFERENCES posts(id) ON DELETE SET NULL"
                )
            if "quoted_reply_id" not in post_columns:
                connection.execute(
                    "ALTER TABLE posts ADD COLUMN quoted_reply_id INTEGER REFERENCES replies(id) ON DELETE SET NULL"
                )
            notification_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(notifications)")
            }
            if "reply_id" not in notification_columns:
                connection.execute("ALTER TABLE notifications ADD COLUMN reply_id INTEGER")
            if "conversation_id" not in notification_columns:
                connection.execute(
                    "ALTER TABLE notifications ADD COLUMN conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE"
                )
            if "activity_kind" not in notification_columns:
                connection.execute(
                    "ALTER TABLE notifications ADD COLUMN activity_kind TEXT NOT NULL DEFAULT ''"
                )
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
                          p.onboarding_completed, p.terms_accepted_at
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
        result["terms_accepted"] = bool(result.pop("terms_accepted_at"))
        moderators = {
            email.strip().lower()
            for email in os.environ.get("ZORLII_MODERATOR_EMAILS", "").split(",")
            if email.strip()
        }
        result["is_moderator"] = result["email"].lower() in moderators
        return result

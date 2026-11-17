import base64
import concurrent.futures
from contextlib import closing
import io
import json
import os
import shutil
import smtplib
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest import mock
from pathlib import Path

from PIL import Image

os.environ["ZORLII_DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient

from zorlii_app.db import Database
from zorlii_app import games
from zorlii_app.main import OTP_EMAIL_LIMIT, new_app, otp_digest
from zorlii_app.security import hash_password, token_digest


class CapturingMailer:
    def __init__(self):
        self.deliveries = []

    def send_otp(self, recipient, code, purpose):
        self.deliveries.append({"recipient": recipient, "code": code, "purpose": purpose})


class FailingMailer:
    def send_otp(self, recipient, code, purpose):
        raise RuntimeError("private delivery failure")


class SMTPAuthFailingMailer:
    def send_otp(self, recipient, code, purpose):
        raise smtplib.SMTPAuthenticationError(535, b"private authentication response")


class AccountApiTests(unittest.TestCase):
    def setUp(self):
        self.avatar_dir = Path(__file__).with_name(f".avatar-test-storage-{id(self)}")
        self.media_dir = Path(__file__).with_name(f".media-test-storage-{id(self)}")
        self.secret_patch = mock.patch.dict(os.environ, {
            "ZORLII_OTP_SECRET": "test-secret-" + "x" * 40,
            "ZORLII_SMTP_HOST": "smtp.example.test",
            "ZORLII_SMTP_FROM": "Zorlii <no-reply@example.test>",
        })
        self.secret_patch.start()
        self.db = Database(":memory:")
        self.mailer = CapturingMailer()
        self.client = TestClient(new_app(self.db, self.mailer, self.avatar_dir, self.media_dir))

    def tearDown(self):
        self.secret_patch.stop()
        shutil.rmtree(self.avatar_dir, ignore_errors=True)
        shutil.rmtree(self.media_dir, ignore_errors=True)

    @staticmethod
    def image_bytes(image_format="PNG"):
        output = io.BytesIO()
        Image.new("RGB", (32, 24), color=(96, 84, 180)).save(output, format=image_format)
        return output.getvalue()

    def register(self, email="jamie@example.test", username="jamie", display_name="Jamie"):
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": email,
                "username": username,
                "password": "Correct horse battery staple 4!",
                "display_name": display_name,
                "accept_terms": True,
            },
        )
        self.assertEqual(response.status_code, 202, response.text)
        code = self.mailer.deliveries[-1]["code"]
        verified = self.client.post("/api/auth/register/verify", json={"email": email, "code": code})
        self.assertEqual(verified.status_code, 201, verified.text)
        return verified.json()

    @staticmethod
    def auth(token):
        return {"Authorization": f"Bearer {token}"}

    def test_registration_login_and_hashed_bearer_session(self):
        response = self.client.post("/api/auth/register", json={
            "email": "jamie@example.test", "username": "jamie",
            "password": "Correct horse battery staple 4!", "display_name": "Jamie", "accept_terms": True,
        })
        self.assertEqual(response.status_code, 202)
        self.assertNotIn("token", response.text.lower())
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            pending = connection.execute("SELECT * FROM otp_challenges").fetchone()
        self.assertIsNotNone(pending)
        self.assertNotIn("Correct horse battery staple 4!", pending["password_hash"])
        self.assertRegex(self.mailer.deliveries[-1]["code"], r"^\d{6}$")
        code = self.mailer.deliveries[-1]["code"]
        self.assertNotIn(code, response.text)
        self.assertNotEqual(pending["code_hash"], code)
        result_response = self.client.post("/api/auth/register/verify", json={
            "email": "jamie@example.test", "code": code,
        })
        self.assertEqual(result_response.status_code, 201, result_response.text)
        result = result_response.json()
        self.assertEqual(result["user"]["username"], "jamie")
        self.assertNotIn("password", result)
        self.assertIn("httponly", result_response.headers["set-cookie"].lower())
        with self.db.locked_connection() as connection:
            row = connection.execute("SELECT token_hash FROM sessions").fetchone()
        self.assertEqual(row["token_hash"], token_digest(result["token"]))
        self.assertNotEqual(row["token_hash"], result["token"])
        self.assertEqual(self.client.get("/api/me", headers=self.auth(result["token"])).status_code, 200)
        duplicate_email = self.client.post("/api/auth/register", json={
            "email": "JAMIE@example.test", "username": "other", "password": "Correct horse battery staple 4!", "display_name": "Other", "accept_terms": True,
        })
        self.assertEqual(duplicate_email.status_code, 409)
        duplicate_username = self.client.post("/api/auth/register", json={
            "email": "other@example.test", "username": "jamie", "password": "Correct horse battery staple 4!", "display_name": "Other", "accept_terms": True,
        })
        self.assertEqual(duplicate_username.status_code, 409)
        self.client.post("/api/auth/logout", headers=self.auth(result["token"]))
        self.assertEqual(self.client.get("/api/me", headers=self.auth(result["token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "email": "JAMIE@example.test", "password": "Correct horse battery staple 4!",
        }).status_code, 200)

    def test_registration_requires_terms_acceptance(self):
        response = self.client.post("/api/auth/register", json={
            "email": "no-consent@example.test",
            "username": "noconsent",
            "password": "Correct horse battery staple 4!",
            "display_name": "No Consent",
            "accept_terms": False,
        })
        self.assertEqual(response.status_code, 422)
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM otp_challenges").fetchone()[0], 0)

    def test_theme_is_account_scoped_and_validated(self):
        first = self.register()
        second = self.register("other@example.test", "other", "Other")
        first_auth = self.auth(first["token"])
        self.assertEqual(self.client.get("/api/me", headers=first_auth).json()["user"]["theme_color"], "#a47dff")
        response = self.client.patch("/api/settings/theme", headers=first_auth, json={"theme_color": "#AB12EF"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["theme_color"], "#ab12ef")
        self.assertEqual(self.client.get("/api/me", headers=first_auth).json()["user"]["theme_color"], "#ab12ef")
        self.assertEqual(self.client.get("/api/me", headers=self.auth(second["token"])).json()["user"]["theme_color"], "#a47dff")
        self.assertEqual(self.client.patch("/api/settings/theme", headers=first_auth, json={"theme_color": "red"}).status_code, 422)
        self.client.cookies.clear()
        self.assertEqual(self.client.patch("/api/settings/theme", json={"theme_color": "#123456"}).status_code, 401)

    def test_language_preference_is_account_scoped_and_validated(self):
        first = self.register()
        second = self.register("other@example.test", "other", "Other")
        first_auth = self.auth(first["token"])
        self.assertEqual(self.client.get("/api/me", headers=first_auth).json()["user"]["language"], "en-US")
        for language in ("fr-FR", "es-ES", "ar", "hi-IN", "ur"):
            result = self.client.patch("/api/settings/language", headers=first_auth, json={"language": language})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["user"]["language"], language)
            self.assertEqual(self.client.get("/api/me", headers=first_auth).json()["user"]["language"], language)
        self.assertEqual(self.client.get("/api/me", headers=self.auth(second["token"])).json()["user"]["language"], "en-US")
        self.assertEqual(self.client.patch("/api/settings/language", headers=first_auth,
                                          json={"language": "not-a-language"}).status_code, 422)
        self.assertEqual(self.client.get("/api/me", headers=first_auth).json()["user"]["language"], "ur")
        login = self.client.post("/api/auth/login", json={
            "email": "jamie@example.test", "password": "Correct horse battery staple 4!",
        })
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual(login.json()["user"]["language"], "ur")
        self.assertEqual(self.client.get("/api/account/export", headers=first_auth).json()["account"]["language"], "ur")
        self.assertEqual(self.client.patch("/api/settings/language", headers=first_auth,
                                          json={"language": "en-US"}).json()["user"]["language"], "en-US")
        self.client.cookies.clear()
        self.assertEqual(self.client.patch("/api/settings/language", json={"language": "fr-FR"}).status_code, 401)

    def test_game_scores_are_server_calculated_ranked_and_account_owned(self):
        first = self.register()
        second = self.register("other@example.test", "other", "Other")
        first_auth, second_auth = self.auth(first["token"]), self.auth(second["token"])
        self.assertEqual(len(self.client.get("/api/games", headers=first_auth).json()["games"]), 7)
        self.assertEqual(self.client.post("/api/games/no-such-game/start", headers=first_auth).status_code, 404)
        with mock.patch("zorlii_app.games._holds", return_value=[0, 1, 2]):
            run = self.client.post("/api/games/summit-steps/start", headers=first_auth).json()
            payload = {"run_id": run["run_id"], "revision": 0, "action": "center"}
            self.assertEqual(self.client.post("/api/games/summit-steps/move", headers=second_auth, json=payload).status_code, 409)
            self.assertEqual(self.client.post("/api/games/summit-steps/move", headers=first_auth, json={**payload, "score": 999999}).status_code, 422)
            result = self.client.post("/api/games/summit-steps/move", headers=first_auth, json=payload)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["state"]["score"], 10)
            resumed = self.client.get("/api/games/summit-steps/run", headers=first_auth).json()["run"]
            self.assertEqual(resumed["run_id"], run["run_id"])
            self.assertEqual(resumed["revision"], 1)
            self.assertEqual(resumed["state"]["score"], 10)
            self.assertEqual(self.client.post("/api/games/summit-steps/move", headers=first_auth, json=payload).status_code, 409)
            other = self.client.post("/api/games/summit-steps/start", headers=second_auth).json()
            for revision in range(2):
                result = self.client.post("/api/games/summit-steps/move", headers=second_auth,
                    json={"run_id": other["run_id"], "revision": revision, "action": "center"})
                self.assertEqual(result.status_code, 200, result.text)
            fresh = self.client.post("/api/games/summit-steps/start", headers=second_auth).json()
            self.client.post("/api/games/summit-steps/move", headers=second_auth,
                json={"run_id": fresh["run_id"], "revision": 0, "action": "center"})
        page = self.client.get("/api/games/summit-steps/leaderboard?limit=1", headers=first_auth).json()
        self.assertEqual([(entry["username"], entry["score"]) for entry in page["scores"]], [("other", 20)])
        self.assertTrue(page["has_more"])
        page = self.client.get("/api/games/summit-steps/leaderboard?limit=1&offset=1", headers=first_auth).json()
        self.assertEqual(page["scores"][0]["score"], 10)
        self.assertFalse(page["has_more"])
        self.assertEqual(self.client.get("/api/games/tile-quest/leaderboard", headers=first_auth).json()["scores"], [])
        exported = self.client.get("/api/account/export", headers=first_auth).json()
        self.assertEqual(exported["game_scores"][0]["score"], 10)
        self.assertEqual(exported["game_progress"][0]["state"]["score"], 10)
        self.assertEqual(self.client.post("/api/users/other/block", headers=first_auth).status_code, 200)
        self.assertEqual(len(self.client.get("/api/games/summit-steps/leaderboard", headers=first_auth).json()["scores"]), 1)
        self.assertEqual(self.client.request("DELETE", "/api/account", headers=second_auth,
            json={"password": "Correct horse battery staple 4!"}).status_code, 200)
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM game_scores").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM game_runs").fetchone()[0], 1)

    def test_game_rules_merge_once_and_end_an_invalid_climb(self):
        state = {"board": [[2, 2, 2, 2], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], "score": 0, "over": False}
        with mock.patch("zorlii_app.games._add_tile"):
            result = games.move("tile-quest", state, "left")
        self.assertEqual(result["board"][0], [4, 4, 0, 0])
        self.assertEqual(result["score"], 8)
        climb = {"lane": 0, "holds": [2], "score": 30, "over": False, "deadline": time.time() + 12}
        result = games.move("summit-steps", climb, "right")
        self.assertTrue(result["over"])
        self.assertEqual(result["score"], 30)
        with self.assertRaises(ValueError):
            games.move("summit-steps", result, "left")
        with mock.patch("zorlii_app.games.time.time", return_value=100):
            expired = games.move("summit-steps", {"lane": 1, "holds": [1], "score": 20,
                                                  "over": False, "deadline": 99}, "center")
        self.assertTrue(expired["over"])
        self.assertEqual(expired["score"], 20)
        for lane in range(3):
            for _ in range(30):
                self.assertTrue(any(abs(hold - lane) <= 1 for hold in games._holds(lane)))

    def test_optional_username_rename_relationships_and_reservations(self):
        registration = {"email": "new@example.test", "password": "Correct horse battery staple 4!", "accept_terms": True}
        self.assertEqual(self.client.post("/api/auth/register", json=registration).status_code, 202)
        code = self.mailer.deliveries[-1]["code"]
        result = self.client.post("/api/auth/register/verify", json={"email": registration["email"], "code": code}).json()
        original = result["user"]["username"]
        self.assertRegex(original, r"^member_[0-9a-f]{12}$")
        self.assertEqual(result["user"]["display_name"], original)
        auth = self.auth(result["token"])
        other = self.register("other@example.test", "other", "Other")
        other_auth = self.auth(other["token"])
        self.assertTrue(self.client.post(f"/api/users/{original}/follow", headers=other_auth).json()["following"])
        self.assertEqual(self.client.patch("/api/profile", headers=auth, json={"username": "OTHER"}).status_code, 409)
        for invalid in ("a!", "ab", "bad-name", None):
            self.assertEqual(self.client.patch("/api/profile", headers=auth, json={"username": invalid}).status_code, 422)
        renamed = self.client.patch("/api/profile", headers=auth, json={"username": "New_Name"})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual(renamed.json()["user"]["username"], "new_name")
        self.assertEqual(self.client.get("/api/me", headers=auth).json()["user"]["username"], "new_name")
        self.assertEqual(self.client.get(f"/api/users/{original}", headers=other_auth).status_code, 404)
        self.assertTrue(self.client.get("/api/users/NEW_NAME", headers=other_auth).json()["user"]["following"])
        self.assertEqual(self.client.post("/api/posts", headers=other_auth, json={"body": "Hello @NEW_NAME"}).status_code, 201)
        with self.db.locked_connection() as connection:
            self.assertTrue(connection.execute("SELECT 1 FROM notifications WHERE user_id=? AND actor_id=?",
                                               (result["user"]["id"], other["user"]["id"])).fetchone())
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE users SET username='NEW_NAME' WHERE id=?", (other["user"]["id"],))
            connection.rollback()
        pending = {**registration, "email": "pending@example.test", "username": "reserved"}
        self.assertEqual(self.client.post("/api/auth/register", json=pending).status_code, 202)
        self.assertEqual(self.client.patch("/api/profile", headers=auth, json={"username": "reserved"}).status_code, 409)
        self.assertEqual(self.client.patch("/api/profile", headers=auth, json={"username": "free_name", "bio": "updated"}).status_code, 200)

    def test_quiz_games_server_scoring_resume_and_invalid_moves(self):
        account = self.register()
        auth = self.auth(account["token"])
        for game in sorted(games.QUIZ_GAMES):
            with self.subTest(game=game):
                run = self.client.post(f"/api/games/{game}/start", headers=auth).json()
                self.assertEqual(run["state"]["round"], 1)
                self.assertEqual(len(run["state"]["choices"]), 4)
                self.assertNotIn("_answer", run["state"])
                invalid = {"run_id": run["run_id"], "revision": 0, "action": "4"}
                self.assertEqual(self.client.post(f"/api/games/{game}/move", headers=auth, json=invalid).status_code, 400)
                for revision in range(10):
                    with self.db.locked_connection() as connection:
                        stored = json.loads(connection.execute("SELECT state FROM game_runs WHERE user_id=? AND game=?",
                                                               (account["user"]["id"], game)).fetchone()["state"])
                    answer = stored["_answer"] if revision != 1 else str((int(stored["_answer"]) + 1) % 4)
                    payload = {"run_id": run["run_id"], "revision": revision, "action": answer}
                    response = self.client.post(f"/api/games/{game}/move", headers=auth, json=payload)
                    self.assertEqual(response.status_code, 200, response.text)
                    run = response.json()
                    self.assertEqual(run["state"]["score"], (revision + 1 - int(revision >= 1)) * 10)
                    self.assertNotIn("_answer", run["state"])
                    if revision == 0:
                        self.assertEqual(self.client.post(f"/api/games/{game}/move", headers=auth, json=payload).status_code, 409)
                        resumed = self.client.get(f"/api/games/{game}/run", headers=auth).json()["run"]
                        self.assertEqual(resumed["state"], run["state"])
                        export = self.client.get("/api/account/export", headers=auth).json()
                        self.assertNotIn("_answer", json.dumps(export))
                self.assertTrue(run["state"]["over"])
                self.assertEqual(run["state"]["score"], 90)
                self.assertEqual(self.client.post(f"/api/games/{game}/move", headers=auth, json={
                    "run_id": run["run_id"], "revision": 10, "action": "0"}).status_code, 400)
                scores = self.client.get(f"/api/games/{game}/leaderboard", headers=auth).json()["scores"]
                self.assertEqual(scores[0]["score"], 90)

    def test_generated_username_retries_existing_and_reserved_names(self):
        self.register("first@example.test", "member_000000000001", "First")
        base = {"password": "Correct horse battery staple 4!", "accept_terms": True}
        self.assertEqual(self.client.post("/api/auth/register", json={
            **base, "email": "reserved@example.test", "username": "member_000000000002"}).status_code, 202)
        self.assertEqual(self.client.post("/api/auth/register", json={
            **base, "email": "generated@example.test"}).status_code, 202)
        code = self.mailer.deliveries[-1]["code"]
        with mock.patch("zorlii_app.main.secrets.token_hex", side_effect=["000000000001", "000000000002", "000000000003"]):
            result = self.client.post("/api/auth/register/verify", json={"email": "generated@example.test", "code": code})
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(result.json()["user"]["username"], "member_000000000003")

    def test_simultaneous_renames_are_case_insensitively_unique(self):
        path = Path(__file__).with_name(f".rename-race-{id(self)}.sqlite3")
        databases = [Database(path), Database(path)]
        try:
            clients = [TestClient(new_app(db, self.mailer, self.avatar_dir, self.media_dir)) for db in databases]
            tokens = []
            for index in range(2):
                email = f"race{index}@example.test"
                response = clients[0].post("/api/auth/register", json={
                    "email": email, "username": f"race{index}", "password": "Correct horse battery staple 4!",
                    "display_name": f"Race {index}", "accept_terms": True})
                self.assertEqual(response.status_code, 202, response.text)
                response = clients[0].post("/api/auth/register/verify", json={"email": email, "code": self.mailer.deliveries[-1]["code"]})
                self.assertEqual(response.status_code, 201, response.text)
                tokens.append(response.json()["token"])
            clients[1].get("/api/me", headers=self.auth(tokens[1]))
            barrier = threading.Barrier(2)
            def rename(index):
                barrier.wait(timeout=10)
                return clients[index].patch("/api/profile", headers=self.auth(tokens[index]),
                                            json={"username": ("SHARED" if index == 0 else "shared")}).status_code
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(rename, range(2)))
            self.assertEqual(sorted(results), [200, 409])
        finally:
            for db in databases:
                if db._connection is not None:
                    db._connection.close()
            path.unlink(missing_ok=True)

    def test_legacy_case_collisions_and_missing_username_are_preserved(self):
        path = Path(__file__).with_name(f".username-migration-{id(self)}.sqlite3")
        db = None
        try:
            with closing(sqlite3.connect(path)) as connection:
                connection.executescript("""
                    CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                                        username TEXT, password_hash TEXT NOT NULL,
                                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    INSERT INTO users(id,email,username,password_hash) VALUES
                        (1,'one@example.test','Alice','hash'),
                        (2,'two@example.test','alice','hash'),
                        (3,'three@example.test',NULL,'hash'),
                        (4,'four@example.test','MEMBER3','hash');
                """)
            db = Database(path)
            with db.locked_connection() as connection:
                names = [row["username"] for row in connection.execute("SELECT username FROM users ORDER BY id")]
                self.assertEqual(names, ["Alice", "alice", "member3_1", "MEMBER3"])
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE users SET username='ALICE' WHERE id=4")
                connection.rollback()
        finally:
            if db is not None and db._connection is not None:
                db._connection.close()
            path.unlink(missing_ok=True)

    def test_quiz_questions_have_consistent_answers(self):
        for game in games.QUIZ_GAMES:
            for _ in range(20):
                state = games.start(game)
                labels = [choice["label"] for choice in state["choices"]]
                self.assertEqual(len(set(labels)), 4)
                answer = labels[int(state["_answer"])]
                if game == "quick-math":
                    a, b = map(int, state["prompt"].removeprefix("What is ").removesuffix("?").split(" + "))
                    self.assertEqual(int(answer), a + b)
                elif game == "word-scramble":
                    self.assertEqual(sorted(answer), sorted(state["prompt"].split(": ")[1]))
                elif game == "number-pattern":
                    numbers = list(map(int, state["prompt"].split(": ")[1].removesuffix("?").split(", ")))
                    self.assertEqual(int(answer), numbers[-1] + numbers[1] - numbers[0])
                elif game == "color-match":
                    colors = {"red": "#FF0000", "green": "#00FF00", "blue": "#0000FF",
                              "yellow": "#FFFF00", "magenta": "#FF00FF", "cyan": "#00FFFF"}
                    self.assertEqual(answer, colors[state["prompt"].split()[-1].removesuffix("?")])
                else:
                    self.assertIn(answer, {"carrot", "dolphin", "trumpet", "cube"})

    def test_public_policy_and_account_deletion_pages_are_available(self):
        for path, phrase in (
            ("/privacy", "Privacy Policy"),
            ("/terms", "Terms of Use"),
            ("/account-deletion", "Request account deletion"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(phrase, response.text)
            self.assertIn("benefit19990@gmail.com", response.text)

    def test_social_refresh_migrations_preserve_existing_account_and_activity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.sqlite3"
            connection = sqlite3.connect(path)
            connection.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE users(
                    id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO users(id,email,password_hash) VALUES(1,'old@example.test','hashed');
                CREATE TABLE profiles(
                    user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                    display_name TEXT NOT NULL,bio TEXT NOT NULL DEFAULT '',
                    interests TEXT NOT NULL DEFAULT '[]',recommendations_consent INTEGER NOT NULL DEFAULT 0,
                    context_assistance_consent INTEGER NOT NULL DEFAULT 0,
                    onboarding_completed INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO profiles(user_id,display_name) VALUES(1,'Existing member');
                CREATE TABLE posts(
                    id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,visibility TEXT NOT NULL DEFAULT 'public',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                INSERT INTO posts(id,user_id,body) VALUES(1,1,'Keep this post');
                CREATE TABLE replies(
                    id INTEGER PRIMARY KEY,post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    body TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE notifications(
                    id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    actor_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    kind TEXT NOT NULL CHECK(kind IN ('follow','reply','reaction')),
                    post_id INTEGER REFERENCES posts(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,read_at TEXT
                );
                INSERT INTO notifications(id,user_id,actor_id,kind,post_id) VALUES(1,1,1,'reaction',1);
                """
            )
            connection.close()
            migrated = Database(path)
            try:
                user = migrated.profile_for(1)
                self.assertEqual(user["display_name"], "Existing member")
                self.assertEqual(user["username"], "member1")
                self.assertEqual(user["theme_color"], "#a47dff")
                self.assertEqual(user["language"], "en-US")
                with migrated.locked_connection() as upgraded:
                    self.assertEqual(upgraded.execute(
                        "SELECT body FROM posts WHERE id=1",
                    ).fetchone()["body"], "Keep this post")
                    self.assertEqual(upgraded.execute(
                        "SELECT kind FROM notifications WHERE id=1",
                    ).fetchone()["kind"], "reaction")
                    self.assertIn(
                        "activity_kind",
                        {row["name"] for row in upgraded.execute("PRAGMA table_info(notifications)")},
                    )
                    self.assertEqual(
                        upgraded.execute("SELECT COUNT(*) FROM push_tokens").fetchone()[0],
                        0,
                    )
            finally:
                if migrated._connection is not None:
                    migrated._connection.close()

    def test_password_policy_applies_to_signup_and_reset_at_boundaries(self):
        registration = {
            "email": "policy@example.test",
            "username": "policy",
            "display_name": "Policy",
            "accept_terms": True,
        }
        invalid_passwords = (
            "aB1",
            "ab1!",
            "AB1!",
            "Abc!",
            "Abc1",
            "A" * 126 + "a1!",
        )
        for password in invalid_passwords:
            response = self.client.post("/api/auth/register", json={**registration, "password": password})
            self.assertEqual(response.status_code, 422, password)

        signup = self.client.post("/api/auth/register", json={**registration, "password": "aB1!"})
        self.assertEqual(signup.status_code, 202, signup.text)
        code = self.mailer.deliveries[-1]["code"]
        verified = self.client.post("/api/auth/register/verify", json={
            "email": registration["email"], "code": code,
        })
        self.assertEqual(verified.status_code, 201, verified.text)
        reset_request = self.client.post("/api/auth/forgot-password", json={"email": registration["email"]})
        self.assertEqual(reset_request.status_code, 202)
        reset_code = self.mailer.deliveries[-1]["code"]
        self.assertEqual(self.client.post("/api/auth/reset-password", json={
            "email": registration["email"], "code": reset_code, "password": "Abc1",
        }).status_code, 422)
        maximum_password = "A" * 125 + "a1!"
        self.assertEqual(len(maximum_password), 128)
        reset = self.client.post("/api/auth/reset-password", json={
            "email": registration["email"], "code": reset_code, "password": maximum_password,
        })
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "email": registration["email"], "password": maximum_password,
        }).status_code, 200)

    def test_existing_passwords_are_not_rejected_by_new_password_policy(self):
        with self.db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO users(email,username,password_hash) VALUES(?,?,?)",
                ("legacy@example.test", "legacy", hash_password("oldpass")),
            )
            connection.execute(
                "INSERT INTO profiles(user_id,display_name) VALUES(?,?)",
                (cursor.lastrowid, "Legacy member"),
            )
        response = self.client.post("/api/auth/login", json={
            "email": "legacy@example.test", "password": "oldpass",
        })
        self.assertEqual(response.status_code, 200, response.text)

    def test_reset_is_opaque_expiring_single_use_and_revokes_sessions(self):
        result = self.register()
        reset_response = self.client.post("/api/auth/forgot-password", json={"email": "jamie@example.test"})
        self.assertEqual(reset_response.status_code, 202)
        code = self.mailer.deliveries[-1]["code"]
        self.assertNotIn(code, reset_response.text)
        self.assertEqual(self.mailer.deliveries[-1]["purpose"], "password_reset")
        with self.db.locked_connection() as connection:
            saved = connection.execute("SELECT code_hash FROM otp_challenges WHERE purpose='password_reset'").fetchone()["code_hash"]
        self.assertEqual(saved, otp_digest(os.environ["ZORLII_OTP_SECRET"].encode(), "password_reset", "jamie@example.test", code))
        reset = self.client.post("/api/auth/reset-password", json={
            "email": "jamie@example.test", "code": code, "password": "Even stronger password 2468!",
        })
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertEqual(self.client.get("/api/me", headers=self.auth(result["token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/reset-password", json={
            "email": "jamie@example.test", "code": code, "password": "Another new password 2468!",
        }).status_code, 400)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "email": "jamie@example.test", "password": "Even stronger password 2468!",
        }).status_code, 200)
        with mock.patch("zorlii_app.main.secrets.randbelow", return_value=999999):
            self.client.post("/api/auth/forgot-password", json={"email": "jamie@example.test"})
        expired_code = self.mailer.deliveries[-1]["code"]
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE otp_challenges SET expires_at=? WHERE purpose='password_reset' AND email=?",
                (int(time.time()) - 1, "jamie@example.test"),
            )
        self.assertEqual(self.client.post("/api/auth/reset-password", json={
            "email": "jamie@example.test", "code": expired_code, "password": "Expired link password 2468!",
        }).status_code, 400)

    def test_forgot_response_does_not_disclose_unknown_account(self):
        known = self.client.post("/api/auth/forgot-password", json={"email": "known@example.test"})
        unknown = self.client.post("/api/auth/forgot-password", json={"email": "nobody@example.test"})
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.json(), unknown.json())
        self.assertEqual([x["recipient"] for x in self.mailer.deliveries], ["known@example.test", "nobody@example.test"])
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM otp_challenges").fetchone()[0], 0)

    def test_password_reset_wrong_codes_are_limited_and_requests_are_rate_limited(self):
        self.register()
        with mock.patch("zorlii_app.main.secrets.randbelow", return_value=999999):
            self.client.post("/api/auth/forgot-password", json={"email": "jamie@example.test"})
        for attempt in range(5):
            response = self.client.post("/api/auth/reset-password", json={
                "email": "jamie@example.test", "code": f"{attempt:06d}",
                "password": "A different password 24680!",
            })
        self.assertEqual(response.status_code, 429)
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute(
                "SELECT COUNT(*) FROM otp_challenges WHERE purpose='password_reset'"
            ).fetchone()[0], 0)

        # Failed deliveries still count toward the per-email hourly limit.
        limited_db = Database(":memory:")
        client = TestClient(new_app(limited_db, FailingMailer()))
        with mock.patch("zorlii_app.main.secrets.randbelow", return_value=123456):
            for attempt in range(OTP_EMAIL_LIMIT):
                with mock.patch("zorlii_app.main.time.time", return_value=int(time.time()) + attempt * 61):
                    response = client.post("/api/auth/forgot-password", json={"email": "ratelimit@example.test"})
                    self.assertEqual(response.status_code, 503)
            with mock.patch("zorlii_app.main.time.time", return_value=int(time.time()) + OTP_EMAIL_LIMIT * 61):
                response = client.post("/api/auth/forgot-password", json={"email": "ratelimit@example.test"})
        self.assertEqual(response.status_code, 429)

    def test_schema_migration_preserves_existing_account_and_session_data(self):
        db = Database(":memory:")
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE profiles (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                display_name TEXT NOT NULL, bio TEXT NOT NULL DEFAULT '',
                interests TEXT NOT NULL DEFAULT '[]', recommendations_consent INTEGER NOT NULL DEFAULT 0,
                context_assistance_consent INTEGER NOT NULL DEFAULT 0, onboarding_completed INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),expires_at INTEGER NOT NULL);
            INSERT INTO users(id,email,password_hash) VALUES(7,'legacy@example.test','kept-hash');
            INSERT INTO profiles(user_id,display_name,bio) VALUES(7,'Legacy member','Still here');
            INSERT INTO sessions(token_hash,user_id,expires_at) VALUES('kept-session-digest',7,9999999999);
        """)
        db._connection = connection
        db.initialize()
        profile = db.profile_for(7)
        self.assertEqual((profile["email"], profile["display_name"], profile["bio"]), (
            "legacy@example.test", "Legacy member", "Still here"
        ))
        self.assertEqual(profile["username"], "member7")
        self.assertEqual(connection.execute("SELECT password_hash FROM users WHERE id=7").fetchone()[0], "kept-hash")
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions WHERE token_hash='kept-session-digest'").fetchone()[0], 1)

    def test_email_configuration_failure_is_explicit_and_never_returns_token(self):
        app = new_app(Database(":memory:"), mailer=None)
        client = TestClient(app)
        with mock.patch.dict(os.environ, {
            "ZORLII_SMTP_HOST": "", "ZORLII_SMTP_FROM": "",
        }, clear=False):
            response = client.post("/api/auth/forgot-password", json={"email": "nobody@example.test"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("token", response.text.lower())

    def test_delivery_failure_does_not_disclose_account_existence_or_leave_token(self):
        db = Database(":memory:")
        client = TestClient(new_app(db, FailingMailer()))
        registration = client.post("/api/auth/register", json={
            "email": "valid@example.test", "username": "valid", "password": "Correct horse battery staple 4!",
            "display_name": "Member", "accept_terms": True,
        })
        self.assertEqual(registration.status_code, 503)
        known = client.post("/api/auth/forgot-password", json={"email": "valid@example.test"})
        unknown = client.post("/api/auth/forgot-password", json={"email": "unknown@example.test"})
        self.assertEqual((known.status_code, unknown.status_code), (503, 503))
        self.assertEqual(known.json(), unknown.json())
        with db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM otp_challenges").fetchone()[0], 0)

    def test_delivery_logs_safe_smtp_failure_details(self):
        client = TestClient(new_app(Database(":memory:"), SMTPAuthFailingMailer()))
        with self.assertLogs("zorlii.recovery", level="ERROR") as captured:
            response = client.post("/api/auth/forgot-password", json={"email": "valid@example.test"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("SMTPAuthenticationError", captured.output[0])
        self.assertIn("provider_code=535", captured.output[0])
        self.assertNotIn("private authentication response", captured.output[0])
        self.assertNotIn("valid@example.test", captured.output[0])

    def test_registration_wrong_code_attempt_limit_and_resend_invalidation(self):
        body = {
            "email": "jamie@example.test", "username": "jamie",
            "password": "Correct horse battery staple 4!", "display_name": "Jamie", "accept_terms": True,
        }
        with mock.patch("zorlii_app.main.secrets.randbelow", side_effect=[100001, 100002, 200002]):
            response = self.client.post("/api/auth/register", json=body)
            self.assertEqual(response.status_code, 202)
            first_code = self.mailer.deliveries[-1]["code"]
            self.assertEqual(first_code, "100001")
            self.assertEqual(self.client.post("/api/auth/register", json=body).status_code, 429)
            # Move past the resend cooldown, then issue a different code.
            with mock.patch("zorlii_app.main.time.time", return_value=int(time.time()) + 61):
                resent = self.client.post("/api/auth/register/resend", json={"email": body["email"]})
        self.assertEqual(resent.status_code, 202)
        second_code = self.mailer.deliveries[-1]["code"]
        self.assertEqual(second_code, "200002")
        self.assertEqual(self.client.post("/api/auth/register/verify", json={
            "email": body["email"], "code": first_code,
        }).status_code, 400)
        for attempt in range(4):
            failed = self.client.post("/api/auth/register/verify", json={
                "email": body["email"], "code": f"{(int(second_code) + attempt + 1) % 1_000_000:06d}",
            })
        self.assertEqual(failed.status_code, 429)
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM otp_challenges").fetchone()[0], 0)
        self.assertEqual(self.client.post("/api/auth/register/verify", json={
            "email": body["email"], "code": second_code,
        }).status_code, 400)

    def test_registration_otp_expiry_rejects_account_creation(self):
        body = {
            "email": "expired@example.test", "username": "expired",
            "password": "Correct horse battery staple 4!", "display_name": "Expired", "accept_terms": True,
        }
        self.client.post("/api/auth/register", json=body)
        code = self.mailer.deliveries[-1]["code"]
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE otp_challenges SET expires_at=? WHERE email=?",
                (int(time.time()) - 1, body["email"]),
            )
        self.assertEqual(self.client.post("/api/auth/register/verify", json={
            "email": body["email"], "code": code,
        }).status_code, 400)
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_otp_secret_is_required_and_codes_are_not_returned(self):
        with mock.patch.dict(os.environ, {"ZORLII_OTP_SECRET": ""}):
            response = self.client.post("/api/auth/register", json={
                "email": "member@example.test", "username": "member",
                "password": "Correct horse battery staple 4!", "display_name": "Member", "accept_terms": True,
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.mailer.deliveries, [])
        self.assertNotIn("code", response.text.lower())

    def test_edit_posts_and_replies_requires_author_and_preserves_media(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        post = self.client.post("/api/posts", headers=ha, json={"body": "Original @bob"}).json()["post"]
        post_url = f"/api/posts/{post['id']}"
        self.client.cookies.clear()
        self.assertEqual(self.client.patch(post_url, json={"body": "Anonymous"}).status_code, 401)
        self.assertEqual(self.client.patch(post_url, headers=hb, json={"body": "Not mine"}).status_code, 404)
        self.assertEqual(self.client.patch(post_url, headers=ha, json={"body": "  "}).status_code, 422)
        self.assertEqual(self.client.patch(post_url, headers=ha, json={}).status_code, 422)
        edited = self.client.patch(post_url, headers=ha, json={"body": "  Updated @bob  "})
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertEqual(edited.json()["post"]["body"], "Updated @bob")
        self.assertEqual(self.client.get(post_url, headers=hb).json()["post"]["body"], "Updated @bob")
        notifications = self.client.get("/api/notifications", headers=hb).json()["notifications"]
        self.assertEqual(len([item for item in notifications if item["kind"] == "mention"]), 1)

        media_post = self.client.post(
            "/api/posts/media", headers=ha, data={"body": "Caption", "visibility": "public"},
            files={"media": ("test.png", self.image_bytes(), "image/png")},
        ).json()["post"]
        edited_media = self.client.patch(
            f"/api/posts/{media_post['id']}", headers=ha, json={"body": ""},
        )
        self.assertEqual(edited_media.status_code, 200, edited_media.text)
        self.assertEqual(edited_media.json()["post"]["media"], media_post["media"])
        quote = self.client.post(
            "/api/posts", headers=ha, json={"body": "Caption", "quoted_post_id": post["id"]},
        ).json()["post"]
        edited_quote = self.client.patch(f"/api/posts/{quote['id']}", headers=ha, json={"body": ""})
        self.assertEqual(edited_quote.status_code, 200, edited_quote.text)
        self.assertEqual(edited_quote.json()["post"]["quoted_post"]["id"], post["id"])

        reply = self.client.post(
            f"/api/posts/{post['id']}/replies/media", headers=hb, data={"body": "Reply"},
            files={"media": ("test.png", self.image_bytes(), "image/png")},
        ).json()
        reply_url = f"/api/replies/{reply['id']}"
        self.assertEqual(self.client.patch(reply_url, headers=ha, json={"body": "Not mine"}).status_code, 404)
        self.assertEqual(self.client.patch(reply_url, headers=hb, json={"body": "x" * 4001}).status_code, 422)
        reply_quote = self.client.post(
            "/api/posts", headers=ha, json={"body": "Quoted reply", "quoted_reply_id": reply["id"]},
        ).json()["post"]
        renamed_reply = self.client.patch(reply_url, headers=hb, json={"body": "Updated reply"})
        self.assertEqual(renamed_reply.status_code, 200, renamed_reply.text)
        self.assertEqual(
            self.client.get(f"/api/posts/{reply_quote['id']}", headers=ha).json()["post"]["quoted_reply"]["body"],
            "Updated reply",
        )
        updated_reply = self.client.patch(reply_url, headers=hb, json={"body": ""})
        self.assertEqual(updated_reply.status_code, 200, updated_reply.text)
        self.assertEqual(updated_reply.json()["media"], reply["media"])
        plain = self.client.post(
            f"/api/posts/{post['id']}/replies", headers=hb, json={"body": "Plain"},
        ).json()
        self.assertEqual(self.client.patch(
            f"/api/replies/{plain['id']}", headers=hb, json={"body": " "},
        ).status_code, 422)

    def test_edit_notifies_only_new_visible_mentions(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        charlie = self.register("charlie@example.test", "charlie", "Charlie")
        ha, hb, hc = (self.auth(account["token"]) for account in (alice, bob, charlie))
        post = self.client.post("/api/posts", headers=ha, json={"body": "Hello @bob"}).json()["post"]
        result = self.client.patch(
            f"/api/posts/{post['id']}", headers=ha, json={"body": "@bob and @charlie"},
        )
        self.assertEqual(result.status_code, 200, result.text)
        for headers in (hb, hc):
            notifications = self.client.get("/api/notifications", headers=headers).json()["notifications"]
            self.assertEqual(len([item for item in notifications if item["kind"] == "mention"]), 1)
        private = self.client.post(
            "/api/posts", headers=ha, json={"body": "Private", "visibility": "private"},
        ).json()["post"]
        self.client.patch(f"/api/posts/{private['id']}", headers=ha, json={"body": "Private @charlie"})
        notifications = self.client.get("/api/notifications", headers=hc).json()["notifications"]
        self.assertEqual(len([item for item in notifications if item["kind"] == "mention"]), 1)
        reply = self.client.post(
            f"/api/posts/{post['id']}/replies", headers=ha, json={"body": "Reply @bob"},
        ).json()
        self.assertEqual(self.client.patch(
            f"/api/replies/{reply['id']}", headers=ha, json={"body": "Reply @bob and @charlie"},
        ).status_code, 200)
        for headers in (hb, hc):
            notifications = self.client.get("/api/notifications", headers=headers).json()["notifications"]
            reply_mentions = [
                item for item in notifications
                if item["kind"] == "mention" and item["reply_id"] == reply["id"]
            ]
            self.assertEqual(len(reply_mentions), 1)

    def test_feed_orders_posts_by_creation_not_repost_time(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        self.client.post("/api/users/bob/follow", headers=ha)
        old = self.client.post("/api/posts", headers=ha, json={"body": "Older"}).json()["post"]
        new = self.client.post("/api/posts", headers=hb, json={"body": "Newer"}).json()["post"]
        with self.db.transaction() as connection:
            connection.execute("UPDATE posts SET created_at=? WHERE id=?", ("2020-01-01 00:00:00", old["id"]))
            connection.execute("UPDATE posts SET created_at=? WHERE id=?", ("2021-01-01 00:00:00", new["id"]))
        self.client.post(f"/api/posts/{old['id']}/repost", headers=hb)
        posts = self.client.get("/api/feed", headers=ha).json()["posts"]
        self.assertEqual([post["id"] for post in posts], [new["id"], old["id"]])
        first = self.client.get("/api/feed?limit=1&offset=0", headers=ha).json()["posts"]
        second = self.client.get("/api/feed?limit=1&offset=1", headers=ha).json()["posts"]
        self.assertEqual([first[0]["id"], second[0]["id"]], [new["id"], old["id"]])

    def test_deleting_reply_removes_other_users_reposts_and_attached_media(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        post = self.client.post("/api/posts", headers=ha, json={"body": "Original"}).json()["post"]
        reply = self.client.post(
            f"/api/posts/{post['id']}/replies", headers=hb, json={"body": "Reply"},
        ).json()
        quote = self.client.post(
            "/api/posts", headers=ha, json={"body": "My thought", "quoted_reply_id": reply["id"]},
        ).json()["post"]
        self.assertEqual(self.client.post(f"/api/replies/{reply['id']}/repost", headers=ha).status_code, 200)
        with self.db.locked_connection() as connection:
            share_id = connection.execute(
                "SELECT share_post_id FROM reply_reposts WHERE reply_id=?", (reply["id"],),
            ).fetchone()["share_post_id"]
        attachment = self.client.post(
            f"/api/posts/{share_id}/replies/media", headers=ha, data={"body": "Attachment"},
            files={"media": ("test.png", self.image_bytes(), "image/png")},
        )
        self.assertEqual(attachment.status_code, 201, attachment.text)
        files_before = list(self.media_dir.iterdir())
        self.assertTrue(files_before)
        self.assertEqual(self.client.delete(f"/api/replies/{reply['id']}", headers=hb).status_code, 200)
        self.assertEqual(self.client.get(f"/api/posts/{share_id}", headers=ha).status_code, 404)
        remaining_quote = self.client.get(f"/api/posts/{quote['id']}", headers=ha).json()["post"]
        self.assertEqual(remaining_quote["body"], "My thought")
        self.assertIsNone(remaining_quote["quoted_reply"])
        self.assertTrue(all(not path.exists() for path in files_before))

    def test_social_content_persists_and_private_content_is_authorized(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        headers_alice, headers_bob = self.auth(alice["token"]), self.auth(bob["token"])
        public = self.client.post("/api/posts", headers=headers_alice, json={"body": "Real public garden notes"})
        private = self.client.post("/api/posts", headers=headers_alice, json={"body": "Personal note", "visibility": "private"})
        self.assertEqual(public.status_code, 201)
        self.assertEqual(private.status_code, 201)
        self.assertEqual([p["body"] for p in self.client.get("/api/feed", headers=headers_bob).json()["posts"]], ["Real public garden notes"])
        self.assertEqual(self.client.get(f"/api/posts/{private.json()['post']['id']}", headers=headers_bob).status_code, 404)
        self.assertEqual(self.client.get(f"/api/posts/{private.json()['post']['id']}", headers=headers_alice).status_code, 200)
        reply = self.client.post(f"/api/posts/{public.json()['post']['id']}/replies", headers=headers_bob, json={"body": "A real reply"})
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(self.client.delete(f"/api/replies/{reply.json()['id']}", headers=headers_alice).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/replies/{reply.json()['id']}", headers=headers_bob).status_code, 200)
        self.assertEqual(self.client.post(f"/api/posts/{public.json()['post']['id']}/reaction", headers=headers_bob).json(), {"reacted": True})
        self.assertEqual(self.client.post(f"/api/posts/{public.json()['post']['id']}/bookmark", headers=headers_bob).json(), {"bookmarked": True})
        notification_data = self.client.get("/api/notifications", headers=headers_alice).json()
        self.assertEqual(len(notification_data["notifications"]), 2)
        self.assertEqual(notification_data["unread_count"], 2)
        notification_id = notification_data["notifications"][0]["id"]
        self.assertEqual(self.client.patch(
            f"/api/notifications/{notification_id}/read", headers=headers_alice,
        ).json(), {"id": notification_id, "read": True})
        self.assertEqual(self.client.patch(
            f"/api/notifications/{notification_id}/read", headers=headers_bob,
        ).status_code, 404)
        self.assertEqual(self.client.get("/api/notifications", headers=headers_alice).json()["unread_count"], 1)
        self.assertEqual(self.client.post("/api/notifications/read", headers=headers_alice).json()["updated"], 1)
        self.assertEqual(self.client.get("/api/notifications", headers=headers_alice).json()["unread_count"], 0)
        self.assertEqual(self.client.delete(f"/api/posts/{public.json()['post']['id']}", headers=headers_bob).status_code, 404)
        self.assertEqual(self.client.delete(f"/api/posts/{public.json()['post']['id']}", headers=headers_alice).status_code, 200)

    def test_hashtags_match_whole_tags_and_respect_visibility(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        def post(body, visibility="public"):
            return self.client.post("/api/posts", headers=ha, json={
                "body": body, "visibility": visibility,
            }).json()["post"]["id"]

        first = post("Hello #Music!")
        post("#musical and inside#music and ##music")
        private = post("#music private", "private")
        followers = post("#MUSIC followers", "followers")
        last = post("#music public")
        page = self.client.get("/api/hashtags/music?limit=1", headers=hb).json()
        self.assertEqual([p["id"] for p in page["posts"]], [last])
        self.assertTrue(page["has_more"])
        page = self.client.get(f"/api/hashtags/MUSIC?limit=1&before_id={last}", headers=hb).json()
        self.assertEqual([p["id"] for p in page["posts"]], [first])
        self.assertFalse(page["has_more"])
        self.client.post("/api/users/jamie/follow", headers=hb)
        visible = self.client.get("/api/hashtags/music", headers=hb).json()["posts"]
        self.assertEqual([p["id"] for p in visible], [last, followers, first])
        self.assertNotIn(private, [p["id"] for p in visible])
        self.client.post("/api/users/jamie/block", headers=hb)
        self.assertEqual(self.client.get("/api/hashtags/music", headers=hb).json()["posts"], [])
        self.assertEqual(self.client.get("/api/hashtags/music!", headers=ha).status_code, 422)
        international = post("A #Café moment")
        self.assertEqual(
            self.client.get("/api/hashtags/café", headers=ha).json()["posts"][0]["id"],
            international,
        )

    def test_follower_visibility_and_private_messaging_participant_access(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        outsider = self.register("eve@example.test", "eve", "Eve")
        ha, hb, he = self.auth(alice["token"]), self.auth(bob["token"]), self.auth(outsider["token"])
        post = self.client.post("/api/posts", headers=ha, json={"body": "Followers only", "visibility": "followers"}).json()["post"]
        self.assertEqual(self.client.get("/api/posts/" + str(post["id"]), headers=hb).status_code, 404)
        self.client.post("/api/users/jamie/follow", headers=hb)
        followers = self.client.get("/api/users/jamie/followers", headers=ha).json()
        following = self.client.get("/api/users/bob/following", headers=hb).json()
        self.assertEqual([person["username"] for person in followers["users"]], ["bob"])
        self.assertEqual([person["username"] for person in following["users"]], ["jamie"])
        self.assertEqual(followers["count"], 1)
        self.assertNotIn("email", followers["users"][0])
        self.assertEqual(self.client.get(
            "/api/users/jamie/followers?offset=1", headers=ha,
        ).json()["users"], [])
        self.assertEqual(self.client.get(
            "/api/users/unknown/followers", headers=ha,
        ).status_code, 404)
        self.client.post("/api/users/bob/block", headers=he)
        self.assertEqual(self.client.get("/api/users/jamie", headers=he).json()["user"]["follower_count"], 0)
        self.assertEqual(self.client.get("/api/users/jamie/followers", headers=he).json()["count"], 0)
        self.assertEqual(self.client.get("/api/posts/" + str(post["id"]), headers=hb).status_code, 200)
        conv = self.client.post("/api/conversations", headers=ha, json={"username": "bob"}).json()["id"]
        message = self.client.post(f"/api/conversations/{conv}/messages", headers=ha, json={"body": "Hello"})
        self.assertEqual(message.status_code, 201)
        message_id = message.json()["id"]
        self.assertEqual(len(self.client.get(f"/api/conversations/{conv}/messages", headers=hb).json()["messages"]), 1)
        self.assertEqual(self.client.get(f"/api/conversations/{conv}/messages", headers=he).status_code, 404)
        self.assertEqual(self.client.post(f"/api/conversations/{conv}/messages", headers=he, json={"body": "intrusion"}).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/conversations/{conv}/messages/{message_id}", headers=hb, json={"body": "changed"}).status_code, 404)
        self.assertEqual(self.client.patch(f"/api/conversations/{conv}/messages/{message_id}", headers=ha, json={"body": "Updated hello"}).status_code, 200)

    def test_profile_activity_counts_and_post_pagination(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        self.assertEqual(self.client.get("/api/me", headers=ha).json()["user"]["activity_counts"],
                         {"posts": 0, "media": 0, "replies": 0, "likes": 0, "echoes": 0,
                          "saved": 0, "messages": 0})
        root = self.client.post("/api/posts", headers=hb, json={"body": "Bob's post"}).json()["post"]
        photo = self.client.post(
            "/api/posts/media", headers=ha, data={"body": "My photo"},
            files=[("media", ("post.png", self.image_bytes(), "image/png"))],
        ).json()["post"]
        self.client.post("/api/posts", headers=ha, json={"body": "Private", "visibility": "private"})
        reply = self.client.post(
            f"/api/posts/{root['id']}/replies/media", headers=ha, data={"body": "My reply"},
            files=[("media", ("reply.png", self.image_bytes(), "image/png"))],
        ).json()
        self.client.post(f"/api/posts/{root['id']}/reaction", headers=ha)
        self.client.post(f"/api/replies/{reply['id']}/reaction", headers=ha)
        self.client.post(f"/api/posts/{root['id']}/bookmark", headers=ha)
        self.client.post(f"/api/posts/{root['id']}/repost", headers=ha)
        self.client.post(f"/api/replies/{reply['id']}/repost", headers=ha)
        conversation_id = self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).json()["id"]
        self.client.post(
            f"/api/conversations/{conversation_id}/messages", headers=ha, json={"body": "Hello"},
        )
        counts = self.client.get("/api/me", headers=ha).json()["user"]["activity_counts"]
        self.assertEqual(counts, {"posts": 3, "media": 2, "replies": 1, "likes": 2, "echoes": 2,
                                  "saved": 1, "messages": 1})
        url = "/api/users/jamie/posts"
        latest = self.client.get(url, headers=hb, params={"limit": 1}).json()
        self.assertTrue(latest["has_more"])
        older = self.client.get(
            url, headers=hb, params={"limit": 1, "before_id": latest["posts"][0]["id"]},
        ).json()
        self.assertFalse(older["has_more"])
        self.assertEqual([post["id"] for post in older["posts"]], [photo["id"]])
        self.assertEqual(self.client.get(url, headers=hb, params={"before_id": 0}).status_code, 422)

    def test_mentions_notify_once_only_when_recipient_can_see_content(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        eve = self.register("eve@example.test", "eve", "Eve")
        ha, hb, he = self.auth(alice["token"]), self.auth(bob["token"]), self.auth(eve["token"])
        post = self.client.post(
            "/api/posts", headers=ha,
            json={"body": "Hello @Bob and @bob, contact someone@eve.example or @unknown"},
        ).json()["post"]
        mentions = [item for item in self.client.get("/api/notifications", headers=hb).json()["notifications"]
                    if item["kind"] == "mention"]
        self.assertEqual(len(mentions), 1)
        self.assertEqual(mentions[0]["post_id"], post["id"])
        self.assertEqual(self.client.get("/api/notifications", headers=he).json()["notifications"], [])
        self.client.post("/api/posts", headers=ha, json={"body": "@bob", "visibility": "private"})
        self.client.post("/api/posts", headers=ha, json={"body": "@bob", "visibility": "followers"})
        self.assertEqual(len([item for item in self.client.get("/api/notifications", headers=hb).json()["notifications"]
                              if item["kind"] == "mention"]), 1)
        self.client.post("/api/users/jamie/follow", headers=hb)
        self.client.post("/api/posts", headers=ha, json={"body": "@bob", "visibility": "followers"})
        self.assertEqual(len([item for item in self.client.get("/api/notifications", headers=hb).json()["notifications"]
                              if item["kind"] == "mention"]), 2)
        self.client.post("/api/users/jamie/block", headers=he)
        self.client.post("/api/posts", headers=ha, json={"body": "@eve"})
        self.assertEqual(self.client.get("/api/notifications", headers=he).json()["notifications"], [])

    def test_mentions_in_media_posts_and_replies(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        post_response = self.client.post(
            "/api/posts/media", headers=ha, data={"body": "@bob"},
            files=[("media", ("photo.png", self.image_bytes(), "image/png"))],
        )
        self.assertEqual(post_response.status_code, 201, post_response.text)
        post_id = post_response.json()["post"]["id"]
        reply_response = self.client.post(
            f"/api/posts/{post_id}/replies/media", headers=ha, data={"body": "@bob"},
            files=[("media", ("photo.png", self.image_bytes(), "image/png"))],
        )
        self.assertEqual(reply_response.status_code, 201, reply_response.text)
        text_reply = self.client.post(
            f"/api/posts/{post_id}/replies", headers=ha, json={"body": "@bob"},
        )
        self.assertEqual(text_reply.status_code, 201, text_reply.text)
        mentions = [item for item in self.client.get("/api/notifications", headers=hb).json()["notifications"]
                    if item["kind"] == "mention"]
        self.assertEqual({item["reply_id"] for item in mentions},
                         {None, reply_response.json()["id"], text_reply.json()["id"]})
        self.assertTrue(all(item["post_id"] == post_id for item in mentions))

    def test_mention_push_is_only_sent_for_visible_content(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        token = "ExpoPushToken[0123456789abcdef01234567]"
        self.assertEqual(self.client.post(
            "/api/push-token", headers=hb, json={"token": token, "platform": "android"},
        ).status_code, 204)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data":[{"status":"ok"}]}'
        with mock.patch("zorlii_app.main.urlopen", return_value=response) as push_request:
            self.client.post("/api/posts", headers=ha, json={"body": "@bob", "visibility": "private"})
            push_request.assert_not_called()
            post = self.client.post("/api/posts", headers=ha, json={"body": "@bob"}).json()["post"]
        payload = json.loads(push_request.call_args.args[0].data)
        self.assertEqual(payload[0]["to"], token)
        self.assertEqual(payload[0]["data"]["post_id"], post["id"])
        self.assertEqual(payload[0]["title"], "New mention")

    def test_message_history_pagination_and_conversation_date(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        outsider = self.register("eve@example.test", "eve", "Eve")
        ha, hb, he = self.auth(alice["token"]), self.auth(bob["token"]), self.auth(outsider["token"])
        conversation_id = self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).json()["id"]
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE conversations SET created_at=? WHERE id=?",
                ("2024-01-02 10:00:00", conversation_id),
            )
        url = f"/api/conversations/{conversation_id}/messages"
        empty = self.client.get(url, headers=hb).json()
        self.assertEqual(empty["conversation_created_at"], "2024-01-02 10:00:00")
        self.assertEqual(empty["messages"], [])
        self.assertFalse(empty["has_more"])
        for number in range(5):
            self.client.post(
                f"/api/conversations/{conversation_id}/messages",
                headers=ha, json={"body": f"Message {number}"},
            )
        self.assertEqual(
            self.client.get("/api/conversations", headers=hb).json()["conversations"][0]["created_at"],
            "2024-01-02 10:00:00",
        )
        latest = self.client.get(url, headers=hb, params={"limit": 2}).json()
        self.assertEqual(latest["conversation_created_at"], "2024-01-02 10:00:00")
        self.assertTrue(latest["has_more"])
        self.assertEqual([message["body"] for message in latest["messages"]], ["Message 3", "Message 4"])
        older = self.client.get(
            url, headers=hb, params={"limit": 2, "before_id": latest["messages"][0]["id"]},
        ).json()
        self.assertTrue(older["has_more"])
        self.assertEqual([message["body"] for message in older["messages"]], ["Message 1", "Message 2"])
        oldest = self.client.get(
            url, headers=hb, params={"limit": 2, "before_id": older["messages"][0]["id"]},
        ).json()
        self.assertFalse(oldest["has_more"])
        self.assertEqual([message["body"] for message in oldest["messages"]], ["Message 0"])
        self.assertEqual(self.client.get(url, headers=he, params={"before_id": 1}).status_code, 404)
        self.assertEqual(self.client.get(url, headers=hb, params={"before_id": 0}).status_code, 422)

    def test_legacy_member_must_accept_terms_before_contributing(self):
        with self.db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO users(email,username,password_hash) VALUES(?,?,?)",
                ("legacy@example.test", "legacy", hash_password("oldpass")),
            )
            connection.execute(
                "INSERT INTO profiles(user_id,display_name) VALUES(?,?)",
                (cursor.lastrowid, "Legacy member"),
            )
        login = self.client.post("/api/auth/login", json={
            "email": "legacy@example.test", "password": "oldpass",
        }).json()
        headers = self.auth(login["token"])
        self.assertFalse(self.client.get("/api/me", headers=headers).json()["user"]["terms_accepted"])
        self.assertEqual(self.client.post(
            "/api/posts", headers=headers, json={"body": "Not accepted yet"},
        ).status_code, 403)
        language = self.client.patch(
            "/api/settings/language", headers=headers, json={"language": "fr-FR"},
        )
        self.assertEqual(language.status_code, 200, language.text)
        self.assertEqual(language.json()["user"]["language"], "fr-FR")
        self.assertFalse(language.json()["user"]["terms_accepted"])
        self.assertEqual(self.client.post(
            "/api/posts", headers=headers, json={"body": "Still not accepted"},
        ).status_code, 403)
        accepted = self.client.post("/api/terms/accept", headers=headers, json={"accepted": True})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertTrue(accepted.json()["user"]["terms_accepted"])
        self.assertEqual(accepted.json()["user"]["language"], "fr-FR")
        self.assertEqual(self.client.post(
            "/api/posts", headers=headers, json={"body": "Accepted"},
        ).status_code, 201)

    def test_reports_are_deduplicated_and_only_moderators_can_review(self):
        reporter = self.register()
        author = self.register("bob@example.test", "bob", "Bob")
        author_headers = self.auth(author["token"])
        post = self.client.post(
            "/api/posts", headers=author_headers, json={"body": "A reported post"},
        ).json()["post"]
        report_payload = {
            "target_type": "post", "target_id": post["id"],
            "reason": "spam", "details": "This looks suspicious.",
        }
        reporter_headers = self.auth(reporter["token"])
        report = self.client.post("/api/reports", headers=reporter_headers, json=report_payload)
        self.assertEqual(report.status_code, 201, report.text)
        self.assertEqual(self.client.post(
            "/api/reports", headers=reporter_headers, json=report_payload,
        ).status_code, 409)
        self.assertEqual(self.client.get(
            "/api/moderation/reports", headers=reporter_headers,
        ).status_code, 403)
        with mock.patch.dict(os.environ, {"ZORLII_MODERATOR_EMAILS": "jamie@example.test"}):
            reports = self.client.get("/api/moderation/reports", headers=reporter_headers)
            self.assertEqual(reports.status_code, 200, reports.text)
            self.assertEqual(reports.json()["reports"][0]["id"], report.json()["id"])
            reviewed = self.client.patch(
                f"/api/moderation/reports/{report.json()['id']}",
                headers=reporter_headers,
                json={"status": "reviewed"},
            )
            self.assertEqual(reviewed.status_code, 200, reviewed.text)
            self.assertEqual(self.client.get(
                "/api/moderation/reports", headers=reporter_headers,
            ).json()["reports"], [])

    def test_only_configured_moderator_can_remove_unreported_posts(self):
        creator = self.register()
        author = self.register("bob@example.test", "bob", "Bob")
        creator_headers = self.auth(creator["token"])
        author_headers = self.auth(author["token"])
        post = self.client.post(
            "/api/posts", headers=author_headers, json={"body": "An unreported post"},
        ).json()["post"]
        with mock.patch.dict(os.environ, {"ZORLII_MODERATOR_EMAILS": "  JAMIE@example.test  "}):
            self.assertTrue(self.client.get("/api/me", headers=creator_headers).json()["user"]["is_moderator"])
            self.assertFalse(self.client.get("/api/me", headers=author_headers).json()["user"]["is_moderator"])
            path = f"/api/moderation/posts/{post['id']}"
            self.assertEqual(self.client.delete(path, headers=author_headers).status_code, 403)
            self.assertEqual(self.client.delete(path, headers=creator_headers).status_code, 200)
            self.assertEqual(self.client.delete(path, headers=creator_headers).status_code, 404)
        with mock.patch.dict(os.environ, {"ZORLII_MODERATOR_EMAILS": ""}):
            self.assertFalse(self.client.get("/api/me", headers=creator_headers).json()["user"]["is_moderator"])
            self.assertEqual(self.client.get("/api/moderation/reports", headers=creator_headers).status_code, 403)

    def test_block_hides_profiles_and_posts_and_prevents_private_messages(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        post = self.client.post(
            "/api/posts", headers=hb, json={"body": "Bob's post"},
        ).json()["post"]
        conversation = self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).json()["id"]
        self.assertIn(post["id"], [
            item["id"] for item in self.client.get("/api/feed", headers=ha).json()["posts"]
        ])
        self.assertEqual(self.client.post("/api/users/bob/block", headers=ha).json()["blocked"], True)
        self.assertNotIn(post["id"], [
            item["id"] for item in self.client.get("/api/feed", headers=ha).json()["posts"]
        ])
        self.assertEqual(self.client.get("/api/users/bob", headers=ha).status_code, 404)
        self.assertEqual(self.client.get(
            f"/api/conversations/{conversation}/messages", headers=ha,
        ).status_code, 404)
        self.assertEqual(self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).status_code, 404)
        self.assertEqual(self.client.get("/api/blocks", headers=ha).json()["users"][0]["username"], "bob")
        self.assertEqual(self.client.post("/api/users/bob/block", headers=ha).json()["blocked"], False)
        self.assertIn(post["id"], [
            item["id"] for item in self.client.get("/api/feed", headers=ha).json()["posts"]
        ])

    def test_profile_and_recommendations_have_real_data_only(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        self.assertEqual(self.client.get("/api/recommendations", headers=ha).status_code, 403)
        self.client.patch("/api/profile", headers=ha, json={
            "bio": "I enjoy thoughtful gardening and books.", "interests": ["gardening", "books"],
            "recommendations_consent": True,
        })
        self.client.post("/api/posts", headers=hb, json={"body": "Gardening basil on a sunny balcony"})
        result = self.client.get("/api/recommendations", headers=ha)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["recommendations"][0]["username"], "bob")
        self.assertNotIn("sample", result.text.lower())
        self.assertEqual(self.client.post("/api/posts", headers=ha, json={"body": "   "}).status_code, 422)

    def test_posts_support_quotes_reposts_and_activity_attribution(self):
        author = self.register()
        reposter = self.register("bob@example.test", "bob", "Bob")
        follower = self.register("eve@example.test", "eve", "Eve")
        ha, hb, he = map(self.auth, (author["token"], reposter["token"], follower["token"]))
        post = self.client.post(
            "/api/posts", headers=ha, json={"body": "The original post"},
        ).json()["post"]
        self.assertEqual(self.client.post(
            "/api/users/bob/follow", headers=he,
        ).status_code, 200)
        repost = self.client.post(f"/api/posts/{post['id']}/repost", headers=hb)
        self.assertEqual(repost.status_code, 200, repost.text)
        self.assertTrue(repost.json()["reposted"])
        reposted_post = next(
            item for item in self.client.get("/api/feed?scope=following", headers=he).json()["posts"]
            if item["id"] == post["id"]
        )
        self.assertEqual(reposted_post["repost_count"], 1)
        self.assertEqual(reposted_post["reposted_by"]["username"], "bob")
        quote = self.client.post("/api/posts", headers=hb, json={
            "body": "Adding my thoughts", "quoted_post_id": post["id"],
        })
        self.assertEqual(quote.status_code, 201, quote.text)
        self.assertEqual(quote.json()["post"]["quoted_post"]["body"], "The original post")
        activities = self.client.get("/api/notifications", headers=ha).json()["notifications"]
        self.assertEqual({item["kind"] for item in activities}, {"repost", "quote"})
        self.assertEqual(
            self.client.post(f"/api/posts/{post['id']}/repost", headers=hb).json(),
            {"reposted": False},
        )

    def test_quote_cannot_expand_non_public_post_visibility(self):
        author = self.register()
        viewer = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(author["token"]), self.auth(viewer["token"])
        post = self.client.post(
            "/api/posts", headers=ha,
            json={"body": "Followers only", "visibility": "followers"},
        ).json()["post"]
        self.assertEqual(self.client.post("/api/posts", headers=hb, json={
            "quoted_post_id": post["id"], "body": "Can't see this yet",
        }).status_code, 404)
        self.client.post("/api/users/jamie/follow", headers=hb)
        public_quote = self.client.post("/api/posts", headers=hb, json={
            "quoted_post_id": post["id"], "body": "Cannot broaden the audience",
        })
        self.assertEqual(public_quote.status_code, 403)
        private_quote = self.client.post("/api/posts", headers=hb, json={
            "quoted_post_id": post["id"], "visibility": "private",
        })
        self.assertEqual(private_quote.status_code, 201, private_quote.text)

    def test_thread_pages_all_visible_replies(self):
        author = self.register()
        blocked = self.register("blocked@example.test", "blocked", "Blocked")
        headers = self.auth(author["token"])
        post = self.client.post("/api/posts", headers=headers, json={"body": "Thread root"}).json()["post"]
        with self.db.transaction() as connection:
            connection.execute(
                "INSERT INTO blocked_users(blocker_id,blocked_id) VALUES(?,?)",
                (author["user"]["id"], blocked["user"]["id"]),
            )
            for index in range(105):
                connection.execute(
                    "INSERT INTO replies(post_id,user_id,body) VALUES(?,?,?)",
                    (post["id"], author["user"]["id"], f"Reply {index}"),
                )
            connection.execute(
                "INSERT INTO replies(post_id,user_id,body) VALUES(?,?,?)",
                (post["id"], blocked["user"]["id"], "Hidden"),
            )
        url = f"/api/posts/{post['id']}"
        default_page = self.client.get(url, headers=headers).json()
        self.assertEqual(len(default_page["replies"]), 100)
        self.assertTrue(default_page["has_more"])
        cursor = None
        bodies = []
        while True:
            params = {"limit": 40}
            if cursor is not None:
                params["after_id"] = cursor
            response = self.client.get(url, headers=headers, params=params)
            self.assertEqual(response.status_code, 200)
            page = response.json()
            bodies.extend(reply["body"] for reply in page["replies"])
            if not page["has_more"]:
                self.assertIsNone(page["next_after_id"])
                break
            self.assertGreater(page["next_after_id"], cursor or 0)
            cursor = page["next_after_id"]
        self.assertEqual(bodies, [f"Reply {index}" for index in range(105)])
        self.assertEqual(self.client.get(url, headers=headers, params={"after_id": 0}).status_code, 422)
        self.assertEqual(self.client.get(url, headers=headers, params={"limit": 101}).status_code, 422)

    def test_replies_support_media_reactions_reposts_and_quotes(self):
        author = self.register()
        replier = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(author["token"]), self.auth(replier["token"])
        post = self.client.post("/api/posts", headers=ha, json={"body": "Thread root"}).json()["post"]
        reply_response = self.client.post(
            f"/api/posts/{post['id']}/replies/media",
            headers=hb,
            data={"body": "A reply with a photo"},
            files=[("media", ("reply.png", self.image_bytes(), "image/png"))],
        )
        self.assertEqual(reply_response.status_code, 201, reply_response.text)
        reply = reply_response.json()
        self.assertEqual(len(reply["media"]), 1)
        media_response = self.client.get(reply["media"][0]["url"], headers=ha)
        self.assertEqual(media_response.status_code, 200)
        self.assertEqual(self.client.post(
            f"/api/replies/{reply['id']}/reaction", headers=ha,
        ).json(), {"reacted": True})
        self.assertEqual(self.client.post(
            f"/api/replies/{reply['id']}/repost", headers=ha,
        ).json(), {"reposted": True})
        details = self.client.get(f"/api/posts/{post['id']}", headers=ha).json()
        self.assertEqual(details["replies"][0]["reaction_count"], 1)
        self.assertEqual(details["replies"][0]["repost_count"], 1)
        quote = self.client.post("/api/posts", headers=ha, json={
            "body": "Quoting this reply", "quoted_reply_id": reply["id"],
        })
        self.assertEqual(quote.status_code, 201, quote.text)
        self.assertEqual(quote.json()["post"]["quoted_reply"]["id"], reply["id"])
        feed = self.client.get("/api/feed", headers=ha).json()["posts"]
        self.assertTrue(any(item["reposted_reply"] for item in feed))
        activities = self.client.get("/api/notifications", headers=hb).json()["notifications"]
        self.assertEqual(
            {item["kind"] for item in activities},
            {"reply_reaction", "reply_repost", "quote"},
        )
        media_path = next(self.media_dir.glob("*.png"))
        self.assertEqual(self.client.delete(
            f"/api/replies/{reply['id']}", headers=hb,
        ).status_code, 200)
        self.assertFalse(media_path.exists())

    def test_search_supports_display_names_and_at_usernames(self):
        self.register("bob@example.test", "bob_smith", "Bob Smith")
        self.register("other@example.test", "bobxsmith", "Other")
        viewer = self.register("eve@example.test", "eve", "Eve")
        headers = self.auth(viewer["token"])
        for query in ("Bob Smith", "@bob_", "@bob_smith", "bob_smith"):
            result = self.client.get("/api/search", headers=headers, params={"q": query})
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual([person["username"] for person in result.json()["people"]], ["bob_smith"])
        self.assertEqual(
            self.client.get("/api/search", headers=headers, params={"q": "@"}).status_code,
            422,
        )
        self.assertEqual(self.client.post("/api/users/bob_smith/block", headers=headers).status_code, 200)
        blocked = self.client.get("/api/search", headers=headers, params={"q": "@bob_"})
        self.assertEqual(blocked.json()["people"], [])

    def test_push_token_registration_and_activity_delivery(self):
        author = self.register()
        liker = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(author["token"]), self.auth(liker["token"])
        push_token = "ExpoPushToken[0123456789abcdef01234567]"
        registered = self.client.post("/api/push-token", headers=ha, json={
            "token": push_token, "platform": "android",
        })
        self.assertEqual(registered.status_code, 204, registered.text)
        post = self.client.post("/api/posts", headers=ha, json={"body": "Like me"}).json()["post"]
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data":[{"status":"ok"}]}'
        with mock.patch("zorlii_app.main.urlopen", return_value=response) as push_request:
            liked = self.client.post(f"/api/posts/{post['id']}/reaction", headers=hb)
        self.assertEqual(liked.status_code, 200, liked.text)
        self.assertTrue(push_request.called)
        payload = json.loads(push_request.call_args.args[0].data)
        self.assertEqual(payload[0]["to"], push_token)
        self.assertEqual(payload[0]["title"], "New like")
        self.assertEqual(self.client.get("/api/notifications", headers=ha).json()[
            "notifications"
        ][0]["kind"], "reaction")
        removed = self.client.request(
            "DELETE", "/api/push-token", headers=ha,
            json={"token": push_token, "platform": "android"},
        )
        self.assertEqual(removed.status_code, 204)

    def test_push_errors_are_diagnosable_without_logging_tokens(self):
        author = self.register()
        liker = self.register("bob@example.test", "bob", "Bob")
        author_headers, liker_headers = self.auth(author["token"]), self.auth(liker["token"])
        token = "ExpoPushToken[0123456789abcdef01234567]"
        self.assertEqual(self.client.post("/api/push-token", headers=author_headers, json={
            "token": token, "platform": "android",
        }).status_code, 204)
        for result, expected in (
            (b'{"errors":[{"message":"provider error"}]}', "did not contain a ticket list"),
            (b'{"data":[{"status":"error","details":{"error":"InvalidCredentials"}}]}', "InvalidCredentials"),
            (b'{"data":[{"status":"error","details":"invalid"}]}', "Other"),
        ):
            post = self.client.post("/api/posts", headers=author_headers, json={"body": "Hello"}).json()["post"]
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = result
            with mock.patch("zorlii_app.main.urlopen", return_value=response), self.assertLogs("zorlii.push") as logs:
                self.assertEqual(self.client.post(
                    f"/api/posts/{post['id']}/reaction", headers=liker_headers,
                ).status_code, 200)
            self.assertIn(expected, " ".join(logs.output))
            self.assertNotIn(token, " ".join(logs.output))

    def test_push_device_not_registered_removes_only_that_token(self):
        author = self.register()
        liker = self.register("bob@example.test", "bob", "Bob")
        author_headers, liker_headers = self.auth(author["token"]), self.auth(liker["token"])
        tokens = ["ExpoPushToken[0123456789abcdef01234567]", "ExpoPushToken[abcdef0123456789abcdef01]"]
        for token in tokens:
            self.assertEqual(self.client.post("/api/push-token", headers=author_headers, json={
                "token": token, "platform": "android",
            }).status_code, 204)
        post = self.client.post("/api/posts", headers=author_headers, json={"body": "Hello"}).json()["post"]
        def provider_reply(request, timeout):
            payload = json.loads(request.data)
            tickets = [
                {"status": "error", "details": {"error": "DeviceNotRegistered"}}
                if item["to"] == tokens[0] else {"status": "ok"}
                for item in payload
            ]
            response = mock.MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps({"data": tickets}).encode()
            return response

        with mock.patch("zorlii_app.main.urlopen", side_effect=provider_reply):
            self.assertEqual(self.client.post(
                f"/api/posts/{post['id']}/reaction", headers=liker_headers,
            ).status_code, 200)
        with self.db.locked_connection() as connection:
            remaining = [row["token"] for row in connection.execute(
                "SELECT token FROM push_tokens WHERE user_id=?", (author["user"]["id"],)
            )]
        self.assertEqual(remaining, [tokens[1]])

    def test_local_context_requires_saved_opt_in_and_per_request_confirmation(self):
        member = self.register()
        headers = self.auth(member["token"])
        request = {
            "text": "Basil needs steady water. Tomatoes prefer full sun.",
            "question": "How should I water basil?",
            "consent_for_this_request": True,
        }
        self.assertEqual(self.client.post("/api/context", headers=headers, json=request).status_code, 403)
        consent = self.client.patch("/api/profile", headers=headers, json={
            "context_assistance_consent": True,
        })
        self.assertTrue(consent.json()["user"]["context_assistance_consent"])
        self.assertEqual(self.client.post(
            "/api/context", headers=headers,
            json={**request, "consent_for_this_request": False},
        ).status_code, 403)
        result = self.client.post("/api/context", headers=headers, json=request)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["method"], "local extractive selection")
        self.assertFalse(result.json()["stored"])
        self.assertEqual(result.json()["sentences"], ["Basil needs steady water."])

    def test_profile_photo_upload_validation_ownership_display_replacement_and_removal(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        alice_headers = self.auth(alice["token"])
        bob_headers = self.auth(bob["token"])
        png = self.image_bytes()

        self.client.cookies.clear()
        self.assertEqual(self.client.put(
            "/api/profile/avatar", content=png, headers={"Content-Type": "image/png"},
        ).status_code, 401)
        invalid_gif = self.client.put(
            "/api/profile/avatar", headers={**alice_headers, "Content-Type": "image/gif"}, content=b"gif",
        )
        self.assertEqual(invalid_gif.status_code, 400)
        spoofed = self.client.put(
            "/api/profile/avatar", headers={**alice_headers, "Content-Type": "image/jpeg"}, content=png,
        )
        self.assertEqual(spoofed.status_code, 400)
        corrupt = self.client.put(
            "/api/profile/avatar", headers={**alice_headers, "Content-Type": "image/png"}, content=b"not an image",
        )
        self.assertEqual(corrupt.status_code, 400)
        with mock.patch("zorlii_app.main.AVATAR_MAX_BYTES", 8):
            oversized = self.client.put(
                "/api/profile/avatar", headers={**alice_headers, "Content-Type": "image/png"},
                content=b"x" * 9,
            )
        self.assertEqual(oversized.status_code, 413)

        uploaded = self.client.put(
            "/api/profile/avatar",
            headers=alice_headers,
            files={"file": ("profile.gif", self.image_bytes("GIF"), "image/gif")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        avatar_url = uploaded.json()["avatar_url"]
        self.assertRegex(avatar_url, rf"/api/avatars/{alice['user']['id']}\?v=[a-f0-9]{{8}}")
        stored = list(self.avatar_dir.glob("*.jpg"))
        self.assertEqual(len(stored), 1)
        self.assertRegex(stored[0].name, r"^[a-f0-9]{32}\.jpg$")
        fetched = self.client.get(avatar_url)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.headers["content-type"], "image/jpeg")
        with Image.open(io.BytesIO(fetched.content)) as decoded:
            self.assertEqual(decoded.size, (32, 24))

        profile = self.client.get("/api/me", headers=alice_headers).json()["user"]
        public_profile = self.client.get("/api/users/jamie", headers=bob_headers).json()["user"]
        self.assertEqual(profile["avatar_url"], avatar_url)
        self.assertEqual(public_profile["avatar_url"], avatar_url)
        self.client.post("/api/posts", headers=alice_headers, json={"body": "A real post"})
        post = self.client.get("/api/feed", headers=bob_headers).json()["posts"][0]
        self.assertEqual(post["author"]["avatar_url"], avatar_url)
        self.assertEqual(self.client.get(f"/api/avatars/{bob['user']['id']}").status_code, 404)

        replacement = self.client.put(
            "/api/profile/avatar", headers={**alice_headers, "Content-Type": "image/jpeg"},
            content=self.image_bytes("JPEG"),
        )
        self.assertEqual(replacement.status_code, 200, replacement.text)
        self.assertEqual(len(list(self.avatar_dir.glob("*.jpg"))), 1)
        self.assertNotEqual(replacement.json()["avatar_url"], avatar_url)
        self.assertEqual(self.client.delete("/api/profile/avatar", headers=bob_headers).status_code, 200)
        self.assertIsNone(self.client.get("/api/me", headers=bob_headers).json()["user"]["avatar_url"])
        self.assertEqual(
            self.client.get("/api/me", headers=alice_headers).json()["user"]["avatar_url"],
            replacement.json()["avatar_url"],
        )
        removed = self.client.delete("/api/profile/avatar", headers=alice_headers)
        self.assertEqual(removed.status_code, 200)
        self.assertIsNone(self.client.get("/api/me", headers=alice_headers).json()["user"]["avatar_url"])
        self.assertEqual(self.client.get(f"/api/avatars/{alice['user']['id']}").status_code, 404)
        self.assertEqual(list(self.avatar_dir.glob("*.jpg")), [])

    def test_profile_photo_accepts_images_above_old_limit_without_client_error(self):
        alice = self.register()
        headers = self.auth(alice["token"])
        pixels = os.urandom(1024 * 1024 * 3)
        output = io.BytesIO()
        Image.frombytes("RGB", (1024, 1024), pixels).save(output, format="PNG")
        image = output.getvalue()
        self.assertGreater(len(image), 2 * 1024 * 1024)
        uploaded = self.client.put(
            "/api/profile/avatar", headers={**headers, "Content-Type": "image/png"}, content=image,
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)

    def test_post_media_upload_supports_gif_video_visibility_and_cleanup(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        alice_headers = self.auth(alice["token"])
        bob_headers = self.auth(bob["token"])
        gif = self.image_bytes("GIF")
        private_post = self.client.post(
            "/api/posts/media",
            headers=alice_headers,
            data={"body": "", "visibility": "private"},
            files=[("media", ("loop.gif", gif, "image/gif"))],
        )
        self.assertEqual(private_post.status_code, 201, private_post.text)
        post = private_post.json()["post"]
        self.assertEqual(post["body"], "")
        self.assertEqual(post["media"][0]["media_type"], "image/gif")
        gif_response = self.client.get(post["media"][0]["url"], headers=alice_headers)
        self.assertEqual(gif_response.status_code, 200)
        self.assertEqual(gif_response.headers["content-type"], "image/gif")
        with Image.open(io.BytesIO(gif_response.content)) as decoded:
            self.assertEqual(decoded.format, "GIF")
        self.assertEqual(
            self.client.get(post["media"][0]["url"], headers=bob_headers).status_code, 404,
        )

        mp4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"
        video_post = self.client.post(
            "/api/posts/media",
            headers=alice_headers,
            data={"body": "A short clip", "visibility": "public"},
            files=[("media", ("clip.mp4", mp4, "video/mp4"))],
        )
        self.assertEqual(video_post.status_code, 201, video_post.text)
        video = video_post.json()["post"]["media"][0]
        self.assertEqual(video["media_type"], "video/mp4")
        fetched_video = self.client.get(video["url"], headers=bob_headers)
        self.assertEqual(fetched_video.status_code, 200)
        self.assertEqual(fetched_video.content, mp4)
        self.assertEqual(fetched_video.headers["x-content-type-options"], "nosniff")

        stored = list(self.media_dir.iterdir())
        self.assertEqual(len(stored), 2)
        self.assertEqual(self.client.delete(
            f"/api/posts/{video_post.json()['post']['id']}", headers=bob_headers,
        ).status_code, 404)
        self.assertTrue(all(path.exists() for path in stored))
        self.assertEqual(self.client.delete(
            f"/api/posts/{video_post.json()['post']['id']}", headers=alice_headers,
        ).status_code, 200)
        self.assertEqual(len(list(self.media_dir.iterdir())), 1)

    def test_post_media_rejects_bad_content_and_requires_text_or_media(self):
        alice = self.register()
        headers = self.auth(alice["token"])
        invalid = self.client.post(
            "/api/posts/media",
            headers=headers,
            data={"body": "Invalid upload"},
            files=[("media", ("fake.gif", b"not a GIF", "image/gif"))],
        )
        self.assertEqual(invalid.status_code, 415)
        empty = self.client.post("/api/posts/media", headers=headers, data={"body": ""})
        self.assertEqual(empty.status_code, 422)
        self.assertEqual(list(self.media_dir.iterdir()), [])

    def test_post_media_detects_images_with_unknown_mime_type(self):
        alice = self.register()
        headers = self.auth(alice["token"])
        for image_format, expected in (("PNG", "image/png"), ("WEBP", "image/webp")):
            response = self.client.post(
                "/api/posts/media", headers=headers, data={"body": ""},
                files=[("media", ("image", self.image_bytes(image_format), "application/octet-stream"))],
            )
            self.assertEqual(response.status_code, 201, response.text)
            self.assertEqual(response.json()["post"]["media"][0]["media_type"], expected)

    def test_account_deletion_removes_profile_photo(self):
        alice = self.register()
        headers = self.auth(alice["token"])
        image = self.image_bytes()
        uploaded = self.client.put(
            "/api/profile/avatar", headers=headers,
            json={"content_type": "image/png", "image_base64": base64.b64encode(image).decode("ascii")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        path = next(self.avatar_dir.glob("*.jpg"))
        post = self.client.post(
            "/api/posts/media",
            headers=headers,
            data={"body": ""},
            files=[("media", ("loop.gif", self.image_bytes("GIF"), "image/gif"))],
        )
        self.assertEqual(post.status_code, 201, post.text)
        media_path = next(self.media_dir.iterdir())
        response = self.client.request(
            "DELETE", "/api/account", headers=headers,
            json={"password": "Correct horse battery staple 4!"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(path.exists())
        self.assertFalse(media_path.exists())

    def test_account_export_contains_user_data_but_never_credentials(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        own_post = self.client.post("/api/posts", headers=ha, json={"body": "My journal"}).json()["post"]
        other_post = self.client.post("/api/posts", headers=hb, json={"body": "A public thought"}).json()["post"]
        self.client.post(f"/api/posts/{other_post['id']}/replies", headers=ha, json={"body": "My reply"})
        self.client.post("/api/users/bob/follow", headers=ha)
        conversation_id = self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).json()["id"]
        self.client.post(
            f"/api/conversations/{conversation_id}/messages", headers=ha, json={"body": "My message"},
        )
        response = self.client.get("/api/account/export", headers=ha)
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["content-disposition"])
        exported = response.json()
        self.assertEqual(exported["account"]["email"], "jamie@example.test")
        self.assertEqual([post["body"] for post in exported["posts"]], ["My journal"])
        self.assertEqual(exported["replies"][0]["body"], "My reply")
        self.assertEqual(exported["following"][0]["username"], "bob")
        self.assertEqual(exported["conversations"][0]["messages"][0]["body"], "My message")
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn("token_hash", response.text)
        self.assertEqual(self.client.get(
            "/api/account/export", headers={"Authorization": "Bearer invalid"},
        ).status_code, 401)

    def test_account_deletion_requires_password_and_removes_only_the_account_data(self):
        alice = self.register()
        bob = self.register("bob@example.test", "bob", "Bob")
        ha, hb = self.auth(alice["token"]), self.auth(bob["token"])
        own_post = self.client.post("/api/posts", headers=ha, json={"body": "Remove me"}).json()["post"]
        bob_post = self.client.post("/api/posts", headers=hb, json={"body": "Keep me"}).json()["post"]
        self.client.post(f"/api/posts/{bob_post['id']}/replies", headers=ha, json={"body": "Remove my reply"})
        conversation_id = self.client.post(
            "/api/conversations", headers=ha, json={"username": "bob"},
        ).json()["id"]
        self.client.post(
            f"/api/conversations/{conversation_id}/messages", headers=ha, json={"body": "Remove my message"},
        )
        self.client.post(
            f"/api/conversations/{conversation_id}/messages", headers=hb, json={"body": "Keep Bob's message"},
        )
        invalid = self.client.request("DELETE", "/api/account", headers=ha, json={"password": "wrong"})
        self.assertEqual(invalid.status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=ha).status_code, 200)
        deleted = self.client.request(
            "DELETE",
            "/api/account", headers=ha, json={"password": "Correct horse battery staple 4!"},
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertEqual(self.client.get("/api/me", headers=ha).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=hb).status_code, 200)
        self.assertEqual(self.client.get(f"/api/posts/{own_post['id']}", headers=hb).status_code, 404)
        self.assertEqual(self.client.get(f"/api/posts/{bob_post['id']}", headers=hb).status_code, 200)
        remaining_messages = self.client.get(
            f"/api/conversations/{conversation_id}/messages", headers=hb,
        ).json()["messages"]
        self.assertEqual([message["body"] for message in remaining_messages], ["Keep Bob's message"])
        with self.db.locked_connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

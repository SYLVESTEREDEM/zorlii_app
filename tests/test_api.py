import os
import smtplib
import sqlite3
import time
import unittest
from unittest import mock

os.environ["ZORLII_DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient

from zorlii_app.db import Database
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
        self.secret_patch = mock.patch.dict(os.environ, {
            "ZORLII_OTP_SECRET": "test-secret-" + "x" * 40,
            "ZORLII_SMTP_HOST": "smtp.example.test",
            "ZORLII_SMTP_FROM": "Zorlii <no-reply@example.test>",
        })
        self.secret_patch.start()
        self.db = Database(":memory:")
        self.mailer = CapturingMailer()
        self.client = TestClient(new_app(self.db, self.mailer))

    def tearDown(self):
        self.secret_patch.stop()

    def register(self, email="jamie@example.test", username="jamie", display_name="Jamie"):
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": email,
                "username": username,
                "password": "Correct horse battery staple 4!",
                "display_name": display_name,
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
            "password": "Correct horse battery staple 4!", "display_name": "Jamie",
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
            "email": "JAMIE@example.test", "username": "other", "password": "Correct horse battery staple 4!", "display_name": "Other",
        })
        self.assertEqual(duplicate_email.status_code, 409)
        duplicate_username = self.client.post("/api/auth/register", json={
            "email": "other@example.test", "username": "jamie", "password": "Correct horse battery staple 4!", "display_name": "Other",
        })
        self.assertEqual(duplicate_username.status_code, 409)
        self.client.post("/api/auth/logout", headers=self.auth(result["token"]))
        self.assertEqual(self.client.get("/api/me", headers=self.auth(result["token"])).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/login", json={
            "email": "JAMIE@example.test", "password": "Correct horse battery staple 4!",
        }).status_code, 200)

    def test_password_policy_applies_to_signup_and_reset_at_boundaries(self):
        registration = {
            "email": "policy@example.test",
            "username": "policy",
            "display_name": "Policy",
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
            "display_name": "Member",
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
        self.assertIn("535", captured.output[0])
        self.assertNotIn("private authentication response", captured.output[0])
        self.assertNotIn("valid@example.test", captured.output[0])

    def test_registration_wrong_code_attempt_limit_and_resend_invalidation(self):
        body = {
            "email": "jamie@example.test", "username": "jamie",
            "password": "Correct horse battery staple 4!", "display_name": "Jamie",
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
            "password": "Correct horse battery staple 4!", "display_name": "Expired",
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
                "password": "Correct horse battery staple 4!", "display_name": "Member",
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.mailer.deliveries, [])
        self.assertNotIn("code", response.text.lower())

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

import re
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from zorlii_app.db import Database
from zorlii_app.main import new_app


ROOT = Path(__file__).resolve().parents[1]


class WebUiRegressionTests(unittest.TestCase):
    def test_registration_inputs_share_full_width_mobile_rule(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        registration = html.split("function authScreen", 1)[1].split("function", 1)[0]
        for field in ("display_name", "username", "email", "password"):
            self.assertRegex(registration, rf'<input type="(?:text|email|password)" name="{field}"')
        self.assertIn(
            ".form input:not([type=checkbox]):not([type=hidden]){width:100%",
            html,
        )

    def test_logo_is_local_and_served_by_the_app_without_external_fonts(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('src="assets/zorlii-logo.png"', html)
        self.assertTrue((ROOT / "assets" / "zorlii-logo.png").is_file())
        self.assertNotRegex(html, r"https?://")

        response = TestClient(new_app(Database(":memory:"))).get("/assets/zorlii-logo.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_registration_and_recovery_use_otp_not_reset_links(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        self.assertIn('id="verify-register"', html)
        self.assertIn('id="verify-reset"', html)
        self.assertIn('data-action="resend-signup"', html)
        self.assertIn('data-action="resend-recovery"', html)
        self.assertIn("/api/auth/register/verify", html)
        self.assertIn("/api/auth/reset-password", html)
        self.assertIn('name="code"', html)
        self.assertNotIn("URLSearchParams(location.search).get('token')", html)
        self.assertNotIn("reset link", html.lower())

    def test_password_policy_and_social_activity_ui_are_exposed(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("4–128 characters", html)
        self.assertIn("passwordPolicyPattern", html)
        self.assertIn('button.dataset.go = "notifications"', html)
        self.assertIn("/api/notifications/read", html)
        self.assertIn("/followers?limit=100", html)
        self.assertIn("/following?limit=100", html)
        self.assertIn("4–128 characters", mobile)
        self.assertIn('"/api/notifications"', mobile)
        self.assertIn('"/api/notifications/read"', mobile)
        self.assertIn("/followers", mobile)
        self.assertIn("/following", mobile)

    def test_account_data_controls_are_available_in_web_and_mobile(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('data-action="export-account"', html)
        self.assertIn('data-go="delete-account"', html)
        self.assertIn("/api/account/export", html)
        self.assertIn('id="delete-account"', html)
        self.assertIn("without @", html)
        self.assertIn('"/api/account/export"', mobile)
        self.assertIn('"/api/account"', mobile)
        self.assertIn("Share.share", mobile)
        self.assertIn("Delete account", mobile)

    def test_profile_photo_controls_and_privacy_copy_exist_on_both_clients(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn('id="avatar-file"', html)
        self.assertIn("PUT", html)
        self.assertIn("DELETE", html)
        self.assertIn("avatarMarkup", html)
        self.assertIn("No generative AI service is used", html)
        self.assertIn("local extractive context help", html)
        self.assertIn("expo-image-picker", mobile)
        self.assertIn("pickAvatar", mobile)
        self.assertIn("Remove profile photo", mobile)
        self.assertIn("avatar_url", mobile)
        self.assertIn("No generative AI service.", mobile)

    def test_empty_states_and_opt_in_local_assistance_remain_explicit(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("New conversations will appear here when members share them.", html)
        self.assertIn("Your inbox is quiet.", html)
        self.assertIn("recommendations_consent", html)
        self.assertIn("context_assistance_consent", html)
        self.assertIn("no generated answers are produced.", html.lower())
        self.assertIn("Conversations shared by real Zorlii members will appear here.", mobile)
        self.assertIn("Suggestions use real public member posts; none may be available yet.", mobile)
        self.assertIn("Confirm use of this text for this request first.", mobile)
        self.assertIn('accessibilityRole="checkbox" accessibilityState={{ checked: form.context_confirm === "true" }}', mobile)

    def test_mobile_navigation_and_empty_state_have_compact_brand_signature(self):
        html = (ROOT / "index.html").read_text(encoding="utf-8")
        mobile = (ROOT / "mobile" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("grid-template-columns:repeat(5,minmax(0,1fr))", html)
        self.assertIn('window.matchMedia("(max-width: 670px)").matches ? "Alerts" : "Notifications"', html)
        self.assertIn('button.setAttribute("aria-label", `Notifications${unreadLabel}`)', html)
        self.assertIn('.empty:before{content:"Z"', html)
        self.assertIn('#auth.form:before{content:"Z"', html)
        self.assertIn("animation:haloPulse 3.8s ease-in-out infinite", html)
        self.assertIn("function BrandHalo(", mobile)
        self.assertIn("<BrandHalo size={42} showLogo />", mobile)
        self.assertIn("<BrandHalo size={58} />", mobile)
        self.assertIn("styles.avatarHalo", mobile)
        self.assertIn("styles.avatarPulse", mobile)


if __name__ == "__main__":
    unittest.main()

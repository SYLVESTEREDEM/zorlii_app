import io
import json
import os
import unittest
from unittest import mock
from urllib.error import HTTPError

from zorlii_app.email_delivery import ResendAPIError, ResendMailer, SMTPMailer, mailer_from_env


class SMTPMailerTests(unittest.TestCase):
    def test_gmail_app_password_whitespace_is_normalized(self):
        with mock.patch.dict(os.environ, {
            "ZORLII_SMTP_HOST": "smtp.gmail.com",
            "ZORLII_SMTP_PORT": "587",
            "ZORLII_SMTP_USER": "mailer@example.test",
            "ZORLII_SMTP_PASSWORD": "ab cd ef gh ij kl mn op",
            "ZORLII_SMTP_FROM": "mailer@example.test",
        }, clear=True):
            mailer = SMTPMailer.from_env()
        self.assertEqual(mailer.password, "abcdefghijklmnop")

    def test_sends_plain_one_time_code_without_reset_link(self):
        smtp = mock.MagicMock()
        smtp.__enter__.return_value = smtp
        with mock.patch("zorlii_app.email_delivery.smtplib.SMTP", return_value=smtp):
            SMTPMailer("smtp.example.test", 587, "user", "private", "Zorlii <no-reply@example.test>").send_otp(
                "member@example.test", "031947", "password_reset"
            )
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "member@example.test")
        self.assertIn("password reset code", message["Subject"].lower())
        self.assertIn("031947", message.get_content())
        self.assertIn("expires in 10 minutes", message.get_content())
        self.assertNotIn("http", message.get_content().lower())

    def test_signup_email_has_verification_copy(self):
        smtp = mock.MagicMock()
        smtp.__enter__.return_value = smtp
        with mock.patch("zorlii_app.email_delivery.smtplib.SMTP", return_value=smtp):
            SMTPMailer("smtp.example.test", 587, "", "", "no-reply@example.test").send_otp(
                "new@example.test", "867530", "register"
            )
        message = smtp.send_message.call_args.args[0]
        self.assertIn("Verify your Zorlii email", message["Subject"])
        self.assertIn("finish creating your account", message.get_content())


class ResendMailerTests(unittest.TestCase):
    def test_selects_resend_from_environment_without_smtp_configuration(self):
        with mock.patch.dict(os.environ, {
            "ZORLII_EMAIL_PROVIDER": "resend",
            "ZORLII_RESEND_API_KEY": "re_test_key",
            "ZORLII_EMAIL_FROM": "Zorlii <no-reply@auth.example.test>",
        }, clear=True):
            mailer = mailer_from_env()
        self.assertIsInstance(mailer, ResendMailer)

    def test_sends_plain_otp_through_resend_https_api(self):
        with mock.patch("zorlii_app.email_delivery.urlopen") as urlopen:
            ResendMailer("re_test_key", "Zorlii <no-reply@auth.example.test>").send_otp(
                "member@example.test", "031947", "password_reset"
            )
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.resend.com/emails")
        self.assertEqual(request.get_header("Authorization"), "Bearer re_test_key")
        payload = json.loads(request.data)
        self.assertEqual(payload["to"], ["member@example.test"])
        self.assertIn("password reset code", payload["subject"].lower())
        self.assertIn("031947", payload["text"])
        self.assertNotIn("http", payload["text"].lower())
        urlopen.assert_called_once_with(request, timeout=15)

    def test_reports_only_a_safe_resend_error_category(self):
        body = json.dumps({
            "name": "validation_error",
            "message": "The auth.example.test domain is not verified.",
        }).encode("utf-8")
        error = HTTPError("https://api.resend.com/emails", 403, "Forbidden", {}, io.BytesIO(body))
        with mock.patch("zorlii_app.email_delivery.urlopen", side_effect=error):
            with self.assertRaises(ResendAPIError) as raised:
                ResendMailer("re_test_key", "Zorlii <no-reply@auth.example.test>").send_otp(
                    "member@example.test", "031947", "register"
                )
        self.assertEqual(raised.exception.code, 403)
        self.assertEqual(raised.exception.provider_reason, "sender_domain_unverified")
        self.assertNotIn("auth.example.test", str(raised.exception))

    def test_preserves_only_a_sanitized_resend_error_name(self):
        body = json.dumps({
            "name": "sender_policy_403",
            "message": "Do not log this provider message.",
        }).encode("utf-8")
        error = HTTPError("https://api.resend.com/emails", 403, "Forbidden", {}, io.BytesIO(body))
        with mock.patch("zorlii_app.email_delivery.urlopen", side_effect=error):
            with self.assertRaises(ResendAPIError) as raised:
                ResendMailer("re_test_key", "Zorlii <no-reply@auth.example.test>").send_otp(
                    "member@example.test", "031947", "register"
                )
        self.assertEqual(raised.exception.provider_reason, "sender_policy_403")
        self.assertNotIn("Do not log", str(raised.exception))


if __name__ == "__main__":
    unittest.main()

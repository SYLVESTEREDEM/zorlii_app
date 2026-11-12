import unittest
from unittest import mock

from zorlii_app.email_delivery import SMTPMailer


class SMTPMailerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

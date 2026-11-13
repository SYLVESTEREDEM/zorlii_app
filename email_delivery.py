import json
import os
import smtplib
from email.message import EmailMessage
from urllib.request import Request, urlopen


class EmailConfigurationError(RuntimeError):
    pass


class SMTPConfigurationError(EmailConfigurationError):
    pass


def otp_email_content(code, purpose):
    if purpose == "register":
        subject = "Verify your Zorlii email"
        action = "verify your email address and finish creating your account"
    else:
        subject = "Your Zorlii password reset code"
        action = "confirm your email address and reset your password"
    text = (
        f"Use this one-time code to {action}:\n\n"
        f"{code}\n\n"
        "The code expires in 10 minutes. If you did not request it, you can ignore this message."
    )
    return subject, text


class SMTPMailer:
    def __init__(self, host, port, username, password, sender, use_tls=True):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls

    @classmethod
    def from_env(cls):
        host = os.environ.get("ZORLII_SMTP_HOST", "").strip()
        sender = os.environ.get("ZORLII_SMTP_FROM", "").strip()
        username = os.environ.get("ZORLII_SMTP_USER", "").strip()
        password = os.environ.get("ZORLII_SMTP_PASSWORD", "")
        if host.lower() == "smtp.gmail.com":
            password = "".join(password.split())
        if not host or not sender:
            raise SMTPConfigurationError("SMTP is not configured.")
        if bool(username) != bool(password):
            raise SMTPConfigurationError("SMTP username and password must both be configured.")
        return cls(
            host=host,
            port=int(os.environ.get("ZORLII_SMTP_PORT", "587")),
            username=username,
            password=password,
            sender=sender,
            use_tls=os.environ.get("ZORLII_SMTP_STARTTLS", "1").lower() not in {"0", "false", "no"},
        )

    def send_otp(self, recipient, code, purpose):
        subject, text = otp_email_content(code, purpose)
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = recipient
        message.set_content(text)
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)


class ResendMailer:
    API_URL = "https://api.resend.com/emails"

    def __init__(self, api_key, sender):
        self.api_key = api_key
        self.sender = sender

    @classmethod
    def from_env(cls):
        api_key = os.environ.get("ZORLII_RESEND_API_KEY", "").strip()
        sender = os.environ.get("ZORLII_EMAIL_FROM", "").strip()
        if not api_key or not sender:
            raise EmailConfigurationError("Resend email is not configured.")
        return cls(api_key, sender)

    def send_otp(self, recipient, code, purpose):
        subject, text = otp_email_content(code, purpose)
        payload = json.dumps({
            "from": self.sender,
            "to": [recipient],
            "subject": subject,
            "text": text,
        }).encode("utf-8")
        request = Request(
            self.API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(request, timeout=15):
            pass


def mailer_from_env():
    provider = os.environ.get("ZORLII_EMAIL_PROVIDER", "smtp").strip().lower()
    if provider == "resend":
        return ResendMailer.from_env()
    if provider == "smtp":
        return SMTPMailer.from_env()
    raise EmailConfigurationError("Unsupported email provider.")

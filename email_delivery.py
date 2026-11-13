import json
import os
import smtplib
from email.message import EmailMessage
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class EmailConfigurationError(RuntimeError):
    pass


class SMTPConfigurationError(EmailConfigurationError):
    pass


class ResendAPIError(RuntimeError):
    def __init__(self, status_code, reason, content_type):
        super().__init__("Resend rejected the email request.")
        self.code = status_code
        self.provider_reason = reason
        self.provider_content_type = content_type


def _resend_error_reason(error):
    raw_body = error.read()
    try:
        body = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        body_text = raw_body.decode("utf-8", errors="ignore").lower()
        if any(marker in body_text for marker in ("cloudflare", "cf-ray", "attention required")):
            return "edge_firewall"
        if "access denied" in body_text:
            return "access_denied"
        if "forbidden" in body_text:
            return "forbidden_response"
        return "non_json_response"
    if not isinstance(body, dict):
        return "unstructured_json_response"

    name = body.get("name")
    message = body.get("message")
    message = message.lower() if isinstance(message, str) else ""
    if "only send testing emails" in message or "testing emails to your own email" in message:
        return "recipient_restricted"
    if "domain" in message and "not verified" in message:
        return "sender_domain_unverified"
    if "api key" in message and ("invalid" in message or "missing" in message):
        return "api_key_rejected"
    if "permission" in message or name == "invalid_permission":
        return "api_key_permission"
    if name == "restricted_api_key":
        return "api_key_restricted"
    if name == "suspended_api_key":
        return "api_key_suspended"
    if "inboxes included" in message or "quota" in message:
        return "quota_exceeded"
    if name == "validation_error":
        return "validation_error"
    if isinstance(name, str) and 1 <= len(name) <= 64 and all(
        character.isascii() and (character.isalnum() or character == "_")
        for character in name
    ):
        return name.lower()
    return "unavailable"


def _resend_content_type(error):
    header = error.headers.get("Content-Type", "") if error.headers else ""
    media_type = header.split(";", 1)[0].strip().lower()
    if media_type in {"application/json", "application/problem+json"} or media_type.endswith("+json"):
        return "json"
    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"
    if media_type.startswith("text/"):
        return "text"
    return "other" if media_type else "unavailable"


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
                "Accept": "application/json",
                "User-Agent": "Zorlii/1.0",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=15):
                pass
        except HTTPError as error:
            raise ResendAPIError(
                error.code,
                _resend_error_reason(error),
                _resend_content_type(error),
            ) from None


def mailer_from_env():
    provider = os.environ.get("ZORLII_EMAIL_PROVIDER", "smtp").strip().lower()
    if provider == "resend":
        return ResendMailer.from_env()
    if provider == "smtp":
        return SMTPMailer.from_env()
    raise EmailConfigurationError("Unsupported email provider.")

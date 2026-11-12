import os
import smtplib
from email.message import EmailMessage


class SMTPConfigurationError(RuntimeError):
    pass


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
        if purpose == "register":
            subject = "Verify your Zorlii email"
            action = "verify your email address and finish creating your account"
        else:
            subject = "Your Zorlii password reset code"
            action = "confirm your email address and reset your password"
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = self.sender
        message["To"] = recipient
        message.set_content(
            f"Use this one-time code to {action}:\n\n"
            f"{code}\n\n"
            "The code expires in 10 minutes. If you did not request it, you can ignore this message."
        )
        with smtplib.SMTP(self.host, self.port, timeout=15) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message)

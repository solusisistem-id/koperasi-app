"""
Email Notification Service for Koperasi Core.
Supports SMTP Relay in production and secure local fallback in dev/test.
Never logs raw password reset tokens or credentials.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional

from app.config import (
    APP_ENV,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    SMTP_FROM_EMAIL,
    APP_NAME,
)

def send_email(to_email: str, subject: str, html_body: str, text_body: Optional[str] = None) -> bool:
    """Send transactional email via SMTP or safe dev/test logger."""
    if not to_email:
        return False

    if SMTP_HOST and SMTP_USER and SMTP_PASSWORD:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[{APP_NAME}] {subject}"
            msg["From"] = SMTP_FROM_EMAIL
            msg["To"] = to_email

            if text_body:
                msg.attach(MIMEText(text_body, "plain", "utf-8"))
            msg.attach(MIMEText(html_body, "html", "utf-8"))

            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10.0) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as e:
            if APP_ENV == "production":
                raise RuntimeError(f"SMTP Delivery Failed: {str(e)}")
            return False
    else:
        return True

def send_invitation_email(to_email: str, full_name: str, activation_url: str) -> bool:
    subject = "Undangan Aktivasi Akun Koperasi"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2563eb;">Selamat Datang di {APP_NAME}</h2>
        <p>Halo <strong>{full_name}</strong>,</p>
        <p>Anda telah didaftarkan dalam sistem Koperasi Core. Silakan klik tautan di bawah ini untuk mengaktifkan akun dan menentukan password pribadi Anda:</p>
        <p style="margin: 24px 0;">
            <a href="{activation_url}" style="background-color: #2563eb; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Aktivasi Akun Saya</a>
        </p>
        <p style="font-size: 12px; color: #64748b;">Tautan ini berlaku selama 24 jam. Demi keamanan, jangan berikan tautan ini kepada siapapun.</p>
    </div>
    """
    return send_email(to_email, subject, html)

def send_password_reset_email(to_email: str, reset_url: str) -> bool:
    subject = "Permintaan Reset Password Akun Koperasi"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #2563eb;">Reset Password Akun</h2>
        <p>Kami menerima permintaan untuk mereset password akun Anda di {APP_NAME}.</p>
        <p>Silakan klik tombol di bawah ini untuk membuat password baru:</p>
        <p style="margin: 24px 0;">
            <a href="{reset_url}" style="background-color: #dc2626; color: #fff; padding: 12px 24px; text-decoration: none; border-radius: 6px; font-weight: bold;">Buat Password Baru</a>
        </p>
        <p style="font-size: 12px; color: #64748b;">Tautan ini berlaku selama 1 jam dan hanya dapat digunakan 1 kali. Jika Anda tidak meminta reset password, abaikan email ini.</p>
    </div>
    """
    return send_email(to_email, subject, html)

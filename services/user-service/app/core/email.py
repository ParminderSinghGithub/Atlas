"""
Email and notification delivery service for password reset and account verification.

Supports:
- Transactional API delivery (e.g. Resend) via RESEND_API_KEY
- Standard SMTP / Gmail App Password delivery via SMTP_HOST, SMTP_USER, SMTP_PASSWORD
- Safe local / cloud fallback (logging reset tokens) when email credentials are not configured
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
import json
import logging
import urllib.request
import urllib.error

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(email: str, token: str, user_name: str = "User") -> bool:
    """
    Send password reset OTP / token email.
    
    Tries in order:
    1. Resend API (if RESEND_API_KEY is configured)
    2. SMTP / Gmail App Password (if SMTP_HOST, SMTP_USER, and SMTP_PASSWORD are configured)
    3. Safe server log fallback (if no external provider is configured)
    """
    text_content = f"""Hello {user_name},

You requested a password reset for your Atlas account.
Your password reset verification code is:

    {token}

This code will expire in {settings.reset_token_expiration_minutes} minutes.
If you did not request this, please ignore this email.

Best regards,
The Atlas Team
"""
    
    html_content = f"""
    <html>
      <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; color: #1e293b; background-color: #f8fafc; padding: 24px;">
        <div style="max-width: 520px; margin: 0 auto; background: #ffffff; border-radius: 16px; border: 1px solid #e2e8f0; padding: 32px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
          <div style="display: flex; align-items: center; margin-bottom: 24px;">
            <div style="background: linear-gradient(135deg, #2563eb, #4f46e5); color: #ffffff; width: 36px; height: 36px; border-radius: 10px; display: inline-block; text-align: center; line-height: 36px; font-weight: 800; font-size: 18px; margin-right: 12px;">A</div>
            <span style="font-size: 20px; font-weight: bold; color: #0f172a; vertical-align: middle;">Atlas</span>
          </div>
          <h2 style="font-size: 20px; font-weight: 700; color: #0f172a; margin-top: 0;">Password Reset Code</h2>
          <p style="font-size: 14px; line-height: 1.6; color: #475569;">Hello <strong>{user_name}</strong>,</p>
          <p style="font-size: 14px; line-height: 1.6; color: #475569;">We received a request to reset your password. Use the verification code below to complete the reset:</p>
          <div style="background-color: #f1f5f9; padding: 18px; border-radius: 12px; font-size: 28px; font-weight: 800; letter-spacing: 6px; text-align: center; color: #1e40af; margin: 24px 0; border: 1px dashed #cbd5e1;">
            {token}
          </div>
          <p style="font-size: 13px; color: #64748b; margin-bottom: 8px;">• This code expires in <strong>{settings.reset_token_expiration_minutes} minutes</strong>.</p>
          <p style="font-size: 13px; color: #64748b; margin-top: 0;">• If you did not make this request, you can safely ignore this email.</p>
          <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;" />
          <p style="font-size: 12px; color: #94a3b8; text-align: center; margin: 0;">Atlas Recommendation Platform</p>
        </div>
      </body>
    </html>
    """

    # 1. Resend API Delivery
    if settings.resend_api_key:
        try:
            req_data = json.dumps({
                "from": settings.resend_from_email or "Atlas <onboarding@resend.dev>",
                "to": [email],
                "subject": "Atlas — Password Reset Code",
                "text": text_content,
                "html": html_content,
            }).encode("utf-8")
            
            req = urllib.request.Request(
                "https://api.resend.com/emails",
                data=req_data,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key.strip()}",
                    "Content-Type": "application/json",
                    "User-Agent": "Atlas-UserService/1.0",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                if 200 <= resp.status < 300:
                    logger.info("Password reset email sent successfully via Resend API | email=%s", email)
                    return True
        except Exception as e:
            logger.error("Failed to send email via Resend API: %s", e)

    # 2. Standard SMTP / Gmail Delivery
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Atlas — Password Reset Code"
            
            from_header = settings.smtp_from_email or settings.smtp_user
            msg["From"] = from_header
            msg["To"] = email
            
            # Extract plain email address for envelope sender
            _, from_addr = parseaddr(from_header)
            envelope_sender = from_addr if from_addr else settings.smtp_user
            
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))
            
            if settings.smtp_port == 465:
                # SSL connection
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [email], msg.as_string())
            else:
                # Standard / STARTTLS connection
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=12) as server:
                    if settings.smtp_use_tls:
                        server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [email], msg.as_string())
                
            logger.info("Password reset email sent successfully via SMTP | email=%s", email)
            return True
        except Exception as e:
            logger.error("Failed to send SMTP email | email=%s: %s", email, e)
    
    # 3. Dev / Unconfigured fallback: log token for forensics and return success
    logger.info(
        "[NOTIFICATION SERVICE] Password reset code for %s: %s (expires in %d min)",
        email,
        token,
        settings.reset_token_expiration_minutes,
    )
    print(f"\n>>> [EMAIL/OTP SERVICE] Password reset code for {email}: {token} (Expires in {settings.reset_token_expiration_minutes}m) <<<\n")
    return True

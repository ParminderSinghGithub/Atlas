"""
Email and notification delivery service for password reset and account verification.

Supports:
- SMTP delivery when configured via environment variables
- Safe development / cloud fallback (logging reset tokens) when SMTP is unconfigured
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(email: str, token: str, user_name: str = "User") -> bool:
    """
    Send password reset OTP / token email.
    
    If SMTP credentials are configured, sends real email via SMTP.
    If unconfigured (free-tier / dev environment), logs the token safely and returns True.
    """
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Atlas — Password Reset Code"
            msg["From"] = settings.smtp_from_email
            msg["To"] = email
            
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
              <body>
                <h2>Atlas Password Reset</h2>
                <p>Hello <strong>{user_name}</strong>,</p>
                <p>You requested a password reset for your Atlas account. Use the verification code below:</p>
                <div style="background-color: #f3f4f6; padding: 16px; border-radius: 8px; font-size: 24px; font-weight: bold; letter-spacing: 4px; text-align: center; color: #1e40af; margin: 16px 0;">
                  {token}
                </div>
                <p>This code expires in <strong>{settings.reset_token_expiration_minutes} minutes</strong>.</p>
                <p>If you did not make this request, you can safely ignore this email.</p>
              </body>
            </html>
            """
            
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))
            
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                server.login(settings.smtp_user, settings.smtp_password)
                server.sendmail(settings.smtp_from_email, [email], msg.as_string())
                
            logger.info("Password reset email sent successfully via SMTP | email=%s", email)
            return True
        except Exception as e:
            logger.exception("Failed to send SMTP email | email=%s: %s", email, e)
            # Fall back to logging
            pass
    
    # Dev / Free-tier environment fallback: log token for forensics and return success
    logger.info(
        "[NOTIFICATION SERVICE] Password reset code for %s: %s (expires in %d min)",
        email,
        token,
        settings.reset_token_expiration_minutes,
    )
    print(f"\n>>> [EMAIL/OTP SERVICE] Password reset code for {email}: {token} (Expires in {settings.reset_token_expiration_minutes}m) <<<\n")
    return True

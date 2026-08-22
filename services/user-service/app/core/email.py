"""
Email notification delivery service for password reset and account verification.

Delivery Mechanism:
- Dedicated Atlas Gmail Account via Gmail SMTP (smtp.gmail.com:587 with STARTTLS).
- Google 16-character App Password configured via environment variables:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_EMAIL, SMTP_USE_TLS.
- Safe development logging fallback when SMTP credentials are not configured.
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parseaddr
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_password_reset_email(email: str, token: str, user_name: str = "User") -> bool:
    """
    Send password reset OTP / verification code to the requested user email address via Gmail SMTP.
    
    Delivery Flow:
    1. If SMTP credentials (SMTP_USER & SMTP_PASSWORD) are configured:
       Dispatches email via Gmail SMTP using STARTTLS (port 587) or SSL (port 465).
    2. If SMTP credentials are not configured (local dev/test environment):
       Logs token securely to server logs for verification.
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

    # 1. Gmail SMTP Delivery
    if settings.smtp_host and settings.smtp_user and settings.smtp_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = "Atlas — Password Reset Code"
            
            from_header = settings.smtp_from_email or f"Atlas <{settings.smtp_user}>"
            msg["From"] = from_header
            msg["To"] = email
            
            # Extract plain email address for envelope sender
            _, from_addr = parseaddr(from_header)
            envelope_sender = from_addr if from_addr else settings.smtp_user
            
            msg.attach(MIMEText(text_content, "plain"))
            msg.attach(MIMEText(html_content, "html"))
            
            if settings.smtp_port == 465:
                # Direct SSL connection
                with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [email], msg.as_string())
            else:
                # Standard / STARTTLS connection (e.g. Gmail port 587)
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                    if settings.smtp_use_tls:
                        server.starttls()
                    server.login(settings.smtp_user, settings.smtp_password)
                    server.sendmail(envelope_sender, [email], msg.as_string())
                
            logger.info("Password reset email sent successfully via Gmail SMTP | recipient=%s", email)
            return True
        except Exception as e:
            logger.error("Failed to send password reset email via SMTP | recipient=%s: %s", email, e)
            return False
    
    # 2. Local development fallback: Log token for local verification
    logger.warning(
        "SMTP credentials not configured (SMTP_USER/SMTP_PASSWORD missing). "
        "Generated password reset code for %s: %s (expires in %d min)",
        email,
        token,
        settings.reset_token_expiration_minutes,
    )
    print(f"\n>>> [EMAIL/OTP SERVICE (DEV)] Password reset code for {email}: {token} (Expires in {settings.reset_token_expiration_minutes}m) <<<\n")
    return True

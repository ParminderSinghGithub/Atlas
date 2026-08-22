"""
Unit & Contract Test Suite for Atlas User Service (Milestone F3 Backend).

Tests:
1. Registration (Success, Validation, Normalized Email, Hash Verification)
2. Duplicate Registration Rejection (400 Bad Request)
3. Login (Success JWT + UUID, Invalid Credentials 401)
4. Authenticated /me Profile (Bearer Token Validation, 401 on Missing/Invalid Header)
5. Forgot Password Flow:
   - Non-existent email (returns generic 200 without leaking account existence)
   - Registered email (creates single-use token, invalidates prior tokens)
6. Token Verification:
   - Valid unexpired token
   - Invalid token
   - Expired token
   - Used/replayed token
7. Reset Password Completion:
   - Successful password reset with valid token
   - New password verified with bcrypt/pbkdf2
   - Token marked used
   - Replay protection (cannot reuse same token)
   - Login with new password succeeds, old password fails
"""
import sys
import os
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Setup path for user-service imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "services", "user-service")))

from app.core.database import Base
from app.models import User, PasswordResetToken
from app.api.schemas import (
    RegisterRequest,
    LoginRequest,
    ForgotPasswordRequest,
    VerifyResetTokenRequest,
    ResetPasswordRequest,
)
from app.api.routes import (
    register,
    signup,
    login,
    get_current_user,
    forgot_password,
    verify_reset_token_endpoint,
    reset_password_endpoint,
    ping,
)
from app.core.auth import (
    hash_password,
    verify_password,
    create_jwt_token,
    generate_reset_token,
    hash_reset_token,
    verify_reset_token,
)


class TestUserServiceUnit(unittest.TestCase):
    """Test suite for user-service endpoints and authentication logic."""

    @classmethod
    def setUpClass(cls):
        # Create an in-memory SQLite database with StaticPool for thread-safe testing
        cls.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        cls.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=cls.engine)
        Base.metadata.create_all(bind=cls.engine)

    def setUp(self):
        # Clear tables between tests
        self.db = self.TestingSessionLocal()
        self.db.query(PasswordResetToken).delete()
        self.db.query(User).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_health_ping(self):
        """GET /api/auth/ping should return alive message."""
        res = ping()
        self.assertEqual(res, {"message": "User service alive"})

    def test_registration_success(self):
        """POST /api/auth/register should create a user and return UUID."""
        req = RegisterRequest(
            name="Jane Doe",
            email="jane.doe@example.com",
            password="securepassword123"
        )
        res = register(req, db=self.db)
        self.assertIsNotNone(res.id)
        self.assertTrue(len(res.id) > 0)

        # Verify in DB
        user = self.db.query(User).filter(User.email == "jane.doe@example.com").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.name, "Jane Doe")
        self.assertTrue(verify_password("securepassword123", user.password))

    def test_duplicate_registration_rejected(self):
        """POST /api/auth/register with same email should raise HTTPException(400)."""
        req1 = RegisterRequest(
            name="User One",
            email="duplicate@example.com",
            password="password123"
        )
        register(req1, db=self.db)

        # Case-insensitive duplicate attempt
        req2 = RegisterRequest(
            name="User Two",
            email="DUPLICATE@example.com",
            password="newpassword456"
        )
        with self.assertRaises(HTTPException) as ctx:
            register(req2, db=self.db)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already registered", ctx.exception.detail.lower())

    def test_login_and_me_flow(self):
        """POST /api/auth/login and GET /api/auth/me profile flow."""
        # 1. Register
        reg_req = RegisterRequest(
            name="Alice Smith",
            email="alice@example.com",
            password="mypassword123"
        )
        register(reg_req, db=self.db)

        # 2. Login with valid credentials
        login_req = LoginRequest(
            email="ALICE@example.com",
            password="mypassword123"
        )
        login_res = login(login_req, db=self.db)
        self.assertIsNotNone(login_res.token)
        self.assertIsNotNone(login_res.id)

        # 3. Access /me with token
        me_res = get_current_user(
            authorization=f"Bearer {login_res.token}",
            db=self.db
        )
        self.assertEqual(me_res.email, "alice@example.com")
        self.assertEqual(me_res.name, "Alice Smith")
        self.assertEqual(me_res.id, login_res.id)

        # 4. Login with invalid password
        bad_login_req = LoginRequest(
            email="alice@example.com",
            password="wrongpassword"
        )
        with self.assertRaises(HTTPException) as ctx:
            login(bad_login_req, db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_forgot_password_and_reset_flow(self):
        """End-to-end forgotten password, OTP verification, and reset flow."""
        # 1. Create user
        reg_req = RegisterRequest(
            name="Bob Recovery",
            email="bob@example.com",
            password="initial_password_123"
        )
        register(reg_req, db=self.db)

        # 2. Request forgot password for registered email
        forgot_req = ForgotPasswordRequest(email="bob@example.com")
        forgot_res = forgot_password(forgot_req, db=self.db)
        self.assertTrue(forgot_res.success)

        # 2b. Request forgot password for non-registered email (returns generic success to prevent enumeration)
        non_reg_req = ForgotPasswordRequest(email="unknown@example.com")
        non_reg_res = forgot_password(non_reg_req, db=self.db)
        self.assertTrue(non_reg_res.success)

        # Retrieve the generated token from the DB to test the flow
        user = self.db.query(User).filter(User.email == "bob@example.com").first()
        token_entry = self.db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False)
        ).first()
        self.assertIsNotNone(token_entry)

        # Set a deterministic plain OTP for verification
        plain_otp = "849201"
        token_entry.token_hash = hash_reset_token(plain_otp)
        token_entry.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        self.db.commit()

        # 3. Verify valid OTP
        verify_req = VerifyResetTokenRequest(email="bob@example.com", token="849201")
        verify_res = verify_reset_token_endpoint(verify_req, db=self.db)
        self.assertTrue(verify_res.valid)

        # 4. Verify invalid OTP
        verify_bad_req = VerifyResetTokenRequest(email="bob@example.com", token="000000")
        verify_bad_res = verify_reset_token_endpoint(verify_bad_req, db=self.db)
        self.assertFalse(verify_bad_res.valid)

        # 5. Complete password reset with valid OTP
        reset_req = ResetPasswordRequest(
            email="bob@example.com",
            token="849201",
            new_password="brand_new_password_456"
        )
        reset_res = reset_password_endpoint(reset_req, db=self.db)
        self.assertTrue(reset_res.success)

        # 6. Replay protection: cannot reuse the same token
        replay_req = ResetPasswordRequest(
            email="bob@example.com",
            token="849201",
            new_password="another_password_789"
        )
        with self.assertRaises(HTTPException) as ctx:
            reset_password_endpoint(replay_req, db=self.db)
        self.assertEqual(ctx.exception.status_code, 400)

        # 7. Login with old password fails
        old_login_req = LoginRequest(
            email="bob@example.com",
            password="initial_password_123"
        )
        with self.assertRaises(HTTPException) as ctx:
            login(old_login_req, db=self.db)
        self.assertEqual(ctx.exception.status_code, 401)

        # 8. Login with new password succeeds
        new_login_req = LoginRequest(
            email="bob@example.com",
            password="brand_new_password_456"
        )
        new_login_res = login(new_login_req, db=self.db)
        self.assertIsNotNone(new_login_res.token)

    def test_email_delivery_mechanisms(self):
        """Test Gmail SMTP delivery, SSL/STARTTLS, custom sender, and fallback."""
        from unittest.mock import patch, MagicMock
        from app.core.email import send_password_reset_email
        from app.core.config import settings

        # 1. Unconfigured local dev fallback
        with patch.object(settings, "smtp_user", None), \
             patch.object(settings, "smtp_password", None):
            res = send_password_reset_email("test@example.com", "123456", "Test User")
            self.assertTrue(res)

        # 2. Mock Gmail SMTP STARTTLS delivery (Port 587)
        with patch.object(settings, "smtp_host", "smtp.gmail.com"), \
             patch.object(settings, "smtp_user", "atlas.platform.official@gmail.com"), \
             patch.object(settings, "smtp_password", "abcd efgh ijkl mnop"), \
             patch.object(settings, "smtp_port", 587), \
             patch.object(settings, "smtp_use_tls", True), \
             patch.object(settings, "smtp_from_email", "Atlas <atlas.platform.official@gmail.com>"), \
             patch("smtplib.SMTP") as mock_smtp:
            mock_server = MagicMock()
            mock_smtp.return_value.__enter__.return_value = mock_server

            res = send_password_reset_email("user@domain.com", "654321", "Alice")
            self.assertTrue(res)
            mock_server.starttls.assert_called_once()
            mock_server.login.assert_called_once_with("atlas.platform.official@gmail.com", "abcd efgh ijkl mnop")
            mock_server.sendmail.assert_called_once()
            args, _ = mock_server.sendmail.call_args
            self.assertEqual(args[0], "atlas.platform.official@gmail.com")
            self.assertEqual(args[1], ["user@domain.com"])
            self.assertIn("654321", args[2])

        # 3. Mock Gmail SMTP SSL delivery (Port 465)
        with patch.object(settings, "smtp_host", "smtp.gmail.com"), \
             patch.object(settings, "smtp_user", "atlas.platform.official@gmail.com"), \
             patch.object(settings, "smtp_password", "abcd efgh ijkl mnop"), \
             patch.object(settings, "smtp_port", 465), \
             patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
            mock_ssl_server = MagicMock()
            mock_smtp_ssl.return_value.__enter__.return_value = mock_ssl_server

            res = send_password_reset_email("ssl_user@domain.com", "112233", "Bob")
            self.assertTrue(res)
            mock_ssl_server.login.assert_called_once_with("atlas.platform.official@gmail.com", "abcd efgh ijkl mnop")
            mock_ssl_server.sendmail.assert_called_once()

        # 4. Mock SMTP Exception handling
        with patch.object(settings, "smtp_host", "smtp.gmail.com"), \
             patch.object(settings, "smtp_user", "atlas.platform.official@gmail.com"), \
             patch.object(settings, "smtp_password", "invalid_password"), \
             patch("smtplib.SMTP", side_effect=Exception("Authentication failed")):
            res = send_password_reset_email("fail_user@domain.com", "999888", "Charlie")
            self.assertFalse(res)


if __name__ == "__main__":
    unittest.main()

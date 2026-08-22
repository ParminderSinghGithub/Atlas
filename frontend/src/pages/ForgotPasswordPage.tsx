import React, { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import axios from 'axios';
import { authService } from '../services/authService';

export const ForgotPasswordPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const initialEmail = searchParams.get('email') || '';
  const initialToken = searchParams.get('token') || '';

  const [step, setStep] = useState<'request' | 'reset'>(initialToken ? 'reset' : 'request');
  const [email, setEmail] = useState(initialEmail);
  const [token, setToken] = useState(initialToken);
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [infoMessage, setInfoMessage] = useState('');
  const [successMessage, setSuccessMessage] = useState('');

  const navigate = useNavigate();

  const handleRequestReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setInfoMessage('');
    setLoading(true);

    try {
      const res = await authService.forgotPassword(email);
      setInfoMessage(res.message || 'If registered, password reset instructions have been sent.');
      setStep('reset');
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || 'Failed to request password reset. Please try again.');
      } else {
        setError('Failed to request password reset. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const handleCompleteReset = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }

    if (newPassword.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }

    if (!token.trim()) {
      setError('Please enter the 6-digit verification code');
      return;
    }

    setLoading(true);

    try {
      const res = await authService.resetPassword(email, token.trim(), newPassword);
      setSuccessMessage(res.message || 'Password reset successfully!');
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || 'Invalid or expired verification code.');
      } else {
        setError('Failed to reset password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[75vh] flex items-center justify-center px-4 py-12">
      <div className="bg-white p-8 sm:p-10 rounded-3xl shadow-xl border border-slate-200/80 w-full max-w-md">
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center font-extrabold text-white text-xl shadow-lg shadow-blue-500/20 mx-auto mb-3">
            A
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            {successMessage ? 'Password Updated' : step === 'request' ? 'Password Recovery' : 'Set New Password'}
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            {successMessage
              ? 'Your password has been securely reset.'
              : step === 'request'
              ? 'Enter your registered email to receive an OTP verification code.'
              : 'Enter your 6-digit code and choose a new password.'}
          </p>
        </div>

        <div className="bg-amber-50/90 border border-amber-200/80 text-amber-900 p-4 rounded-2xl text-xs space-y-1 mb-6">
          <div className="flex items-start gap-2.5">
            <svg className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="leading-relaxed">
              <p className="font-semibold text-amber-950">Free-Tier Deployment Advisory</p>
              <p className="mt-1 text-amber-800">
                Password recovery is currently unavailable on the free-tier deployment because email delivery is temporarily limited. If you need access and do not remember your password, please{' '}
                <Link to="/register" className="font-bold underline text-amber-950 hover:text-amber-700">
                  create a new account
                </Link>.
              </p>
            </div>
          </div>
        </div>

        {error && (
          <div className="bg-rose-50 border border-rose-200/80 text-rose-700 px-4 py-3 rounded-xl text-xs font-medium mb-6">
            {error}
          </div>
        )}

        {infoMessage && !successMessage && (
          <div className="bg-blue-50 border border-blue-200/80 text-blue-800 px-4 py-3 rounded-xl text-xs font-medium mb-6">
            {infoMessage}
          </div>
        )}

        {successMessage ? (
          <div className="space-y-6">
            <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-2xl text-xs flex items-start gap-3">
              <svg className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
              </svg>
              <div>
                <p className="font-semibold text-emerald-900">{successMessage}</p>
                <p className="mt-1 text-emerald-700">You can now sign in with your updated password.</p>
              </div>
            </div>

            <button
              onClick={() => navigate('/login')}
              className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs sm:text-sm font-semibold transition-all duration-200 shadow-md shadow-blue-600/20"
            >
              Proceed to Sign In
            </button>
          </div>
        ) : step === 'request' ? (
          <form onSubmit={handleRequestReset} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">Account Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                required
                disabled={loading}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs sm:text-sm font-semibold transition-all duration-200 shadow-md shadow-blue-600/20 disabled:bg-slate-400 mt-2"
            >
              {loading ? 'Sending Code...' : 'Send Recovery Code'}
            </button>

            <div className="text-center pt-2">
              <span className="text-xs text-slate-500">Already have a code? </span>
              <button
                type="button"
                onClick={() => setStep('reset')}
                className="text-xs text-blue-600 hover:underline font-semibold"
              >
                Enter code directly
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={handleCompleteReset} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">Account Email</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="name@example.com"
                className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                required
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">Verification Code / OTP</label>
              <input
                type="text"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                placeholder="e.g. 563079"
                maxLength={64}
                className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-xs sm:text-sm tracking-widest font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                required
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">New Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="Minimum 6 characters"
                minLength={6}
                className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                required
                disabled={loading}
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">Confirm New Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="Re-enter new password"
                minLength={6}
                className="w-full px-4 py-2.5 rounded-xl border border-slate-200 bg-slate-50/50 text-xs sm:text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all"
                required
                disabled={loading}
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs sm:text-sm font-semibold transition-all duration-200 shadow-md shadow-emerald-600/20 disabled:bg-slate-400 mt-2"
            >
              {loading ? 'Updating Password...' : 'Save New Password'}
            </button>

            <div className="text-center pt-2">
              <button
                type="button"
                onClick={() => setStep('request')}
                className="text-xs text-slate-500 hover:text-slate-800 hover:underline"
              >
                Request a new code
              </button>
            </div>
          </form>
        )}

        <div className="mt-8 pt-6 border-t border-slate-100 text-center">
          <Link to="/login" className="text-xs text-blue-600 hover:underline font-semibold inline-flex items-center gap-1">
            &larr; Back to Sign In
          </Link>
        </div>
      </div>
    </div>
  );
};

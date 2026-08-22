import React, { useState } from 'react';
import { useNavigate, Link, useLocation } from 'react-router-dom';
import axios from 'axios';
import { useAuth } from '../contexts/AuthContext';

export const LoginPage: React.FC = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [recoveryNotice, setRecoveryNotice] = useState(false);
  const [loading, setLoading] = useState(false);

  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const from = (location.state as { from?: { pathname?: string } })?.from?.pathname || '/';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      await login(email, password);
      navigate(from, { replace: true });
    } catch (err: unknown) {
      if (axios.isAxiosError(err)) {
        setError(err.response?.data?.detail || 'Login failed. Please verify your credentials.');
      } else {
        setError('Login failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-[75vh] flex items-center justify-center px-4 py-12">
      <div className="bg-white p-8 sm:p-10 rounded-3xl shadow-xl border border-slate-200/80 w-full max-w-md">
        {/* Brand Icon */}
        <div className="text-center mb-8">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center font-extrabold text-white text-xl shadow-lg shadow-blue-500/20 mx-auto mb-3">
            A
          </div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Sign in to Atlas
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Access your personalized recommendations and saved cart
          </p>
        </div>

        {error && (
          <div className="bg-rose-50 border border-rose-200/80 text-rose-700 px-4 py-3 rounded-xl text-xs font-medium mb-6">
            {error}
          </div>
        )}

        {recoveryNotice && (
          <div className="bg-amber-50/90 border border-amber-200/80 text-amber-900 p-4 rounded-2xl text-xs space-y-2 mb-6">
            <div className="flex items-start gap-2.5">
              <svg className="w-4 h-4 text-amber-600 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div className="flex-1 leading-relaxed">
                <p className="font-semibold text-amber-950">Password Recovery Notice</p>
                <p className="mt-1 text-amber-800">
                  Password recovery is currently unavailable on the free-tier deployment because email delivery is temporarily limited. If you need access and do not remember your password, please{' '}
                  <Link to="/register" className="font-bold underline text-amber-950 hover:text-amber-700">
                    create a new account
                  </Link>.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setRecoveryNotice(false)}
                className="text-amber-500 hover:text-amber-800 p-0.5 -mt-0.5 -mr-0.5 rounded-lg focus:outline-none"
                aria-label="Dismiss notice"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-semibold text-slate-700 mb-1.5">Email Address</label>
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
            <div className="flex justify-between items-center mb-1.5">
              <label className="block text-xs font-semibold text-slate-700">Password</label>
              <button
                type="button"
                onClick={() => setRecoveryNotice(true)}
                className="text-xs text-blue-600 hover:underline font-medium focus:outline-none"
              >
                Forgot password?
              </button>
            </div>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
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
            {loading ? 'Authenticating...' : 'Sign In'}
          </button>
        </form>

        <p className="mt-8 text-center text-xs text-slate-500">
          Don't have an account?{' '}
          <Link to="/register" className="text-blue-600 hover:underline font-semibold">
            Create account
          </Link>
        </p>
      </div>
    </div>
  );
};

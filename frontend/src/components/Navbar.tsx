import React from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';

export const Navbar: React.FC = () => {
  const { isAuthenticated, userEmail, logout } = useAuth();

  // Extract email prefix for display
  const getUserDisplay = (email: string | null): { initial: string; prefix: string } => {
    if (!email) return { initial: 'U', prefix: 'User' };
    
    // Check if it's an email
    if (email.includes('@')) {
      const prefix = email.split('@')[0];
      const initial = prefix.charAt(0).toUpperCase();
      return { initial, prefix };
    }
    
    // Fallback for non-email IDs (show first 10 chars or full if shorter)
    const displayName = email.length > 10 ? email.substring(0, 10) : email;
    return { initial: email.charAt(0).toUpperCase(), prefix: displayName };
  };

  const userDisplay = getUserDisplay(userEmail);

  return (
    <nav className="bg-gradient-to-r from-slate-900 to-slate-800 text-white shadow-lg">
      <div className="container mx-auto px-4 sm:px-6 py-3 sm:py-4">
        <div className="flex justify-between items-center">
          {/* Logo and Tagline */}
          <div className="flex flex-col">
            <Link to="/" className="flex items-center gap-2 group">
              <span className="text-2xl sm:text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">
                Atlas
              </span>
            </Link>
            <span className="hidden sm:block text-xs text-gray-400 mt-1">
              Production-Grade Recommendation Platform
            </span>
          </div>

          {/* Navigation Links */}
          <div className="flex items-center gap-2 sm:gap-4 md:gap-8">
            <Link 
              to="/" 
              className="text-gray-300 hover:text-white transition-colors font-medium text-sm sm:text-base"
            >
              Home
            </Link>
            <Link 
              to="/products" 
              className="text-gray-300 hover:text-white transition-colors font-medium text-sm sm:text-base"
            >
              Products
            </Link>
            <Link 
              to="/cart" 
              className="flex items-center gap-1 sm:gap-2 text-gray-300 hover:text-white transition-colors font-medium text-sm sm:text-base"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 sm:h-5 sm:w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 3h2l.4 2M7 13h10l4-8H5.4M7 13L5.4 5M7 13l-2.293 2.293c-.63.63-.184 1.707.707 1.707H17m0 0a2 2 0 100 4 2 2 0 000-4zm-8 2a2 2 0 11-4 0 2 2 0 014 0z" />
              </svg>
              <span className="hidden sm:inline">Cart</span>
            </Link>

            {/* User Section */}
            {isAuthenticated ? (
              <div className="flex items-center gap-2 sm:gap-4">
                <div className="flex items-center gap-2">
                  <div className="w-8 h-8 sm:w-10 sm:h-10 rounded-full bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center text-white font-bold shadow-md text-sm sm:text-base">
                    {userDisplay.initial}
                  </div>
                  <span className="hidden md:inline text-sm text-gray-300">{userDisplay.prefix}</span>
                </div>
                <button
                  onClick={logout}
                  className="bg-red-600 hover:bg-red-700 px-3 py-1.5 sm:px-4 sm:py-2 rounded-lg transition-colors font-medium text-sm sm:text-base"
                >
                  <span className="hidden sm:inline">Logout</span>
                  <span className="sm:hidden">Exit</span>
                </button>
              </div>
            ) : (
              <div className="flex gap-2 sm:gap-3">
                <Link
                  to="/login"
                  className="bg-blue-600 hover:bg-blue-700 px-3 py-1.5 sm:px-5 sm:py-2 rounded-lg transition-colors font-medium text-sm sm:text-base"
                >
                  Login
                </Link>
                <Link
                  to="/register"
                  className="bg-purple-600 hover:bg-purple-700 px-3 py-1.5 sm:px-5 sm:py-2 rounded-lg transition-colors font-medium text-sm sm:text-base"
                >
                  <span className="hidden sm:inline">Register</span>
                  <span className="sm:hidden">Sign Up</span>
                </Link>
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
};

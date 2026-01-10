import React, { createContext, useContext, useState, useEffect } from 'react';
import type { ReactNode } from 'react';
import api from '../services/api';

interface AuthContextType {
  isAuthenticated: boolean;
  userId: string | null;
  userEmail: string | null;
  userName: string | null;
  token: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (name: string, email: string, password: string) => Promise<void>;
  logout: () => void;
  loading: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userName, setUserName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Load from localStorage on mount
    const storedToken = localStorage.getItem('token');
    const storedUserId = localStorage.getItem('userId');
    const storedEmail = localStorage.getItem('userEmail');
    const storedName = localStorage.getItem('userName');
    
    if (storedToken && storedUserId) {
      setToken(storedToken);
      setUserId(storedUserId);
      setUserEmail(storedEmail);
      setUserName(storedName);
      // Set default Authorization header
      api.defaults.headers.common['Authorization'] = `Bearer ${storedToken}`;
    }
    setLoading(false);
  }, []);

  const login = async (email: string, password: string) => {
    const response = await api.post('/api/auth/login', { email, password });
    const { token, id } = response.data;
    
    // Set token first for subsequent requests
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    
    // Fetch user profile to get name
    const profileResponse = await api.get('/api/auth/me');
    const { name } = profileResponse.data;
    
    setToken(token);
    setUserId(id);
    setUserEmail(email);
    setUserName(name);
    localStorage.setItem('token', token);
    localStorage.setItem('userId', id);
    localStorage.setItem('userEmail', email);
    localStorage.setItem('userName', name);
  };

  const register = async (name: string, email: string, password: string) => {
    // First register the user
    const signupResponse = await api.post('/api/auth/signup', { name, email, password });
    const { id } = signupResponse.data;
    
    // Then automatically log them in
    const loginResponse = await api.post('/api/auth/login', { email, password });
    const { token } = loginResponse.data;
    
    // Set token first for subsequent requests
    api.defaults.headers.common['Authorization'] = `Bearer ${token}`;
    
    setToken(token);
    setUserId(id);
    setUserEmail(email);
    setUserName(name);
    localStorage.setItem('token', token);
    localStorage.setItem('userId', id);
    localStorage.setItem('userEmail', email);
    localStorage.setItem('userName', name);
  };

  const logout = () => {
    setToken(null);
    setUserId(null);
    setUserEmail(null);
    setUserName(null);
    localStorage.removeItem('token');
    localStorage.removeItem('userId');
    localStorage.removeItem('userEmail');
    localStorage.removeItem('userName');
    delete api.defaults.headers.common['Authorization'];
  };

  return (
    <AuthContext.Provider
      value={{
        isAuthenticated: !!token,
        userId,
        userEmail,
        userName,
        token,
        login,
        register,
        logout,
        loading,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

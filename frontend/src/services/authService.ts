import api from './api';

export interface RegisterPayload {
  name: string;
  email: string;
  password: string;
}

export interface RegisterResponse {
  id: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  id: string;
}

export interface UserProfileResponse {
  id: string;
  email: string;
  name: string;
}

export interface ForgotPasswordResponse {
  message: string;
  success: boolean;
}

export interface VerifyResetTokenResponse {
  valid: boolean;
  message: string;
}

export interface ResetPasswordResponse {
  message: string;
  success: boolean;
}

class AuthService {
  async register(data: RegisterPayload): Promise<RegisterResponse> {
    const response = await api.post<RegisterResponse>('/auth/register', data);
    return response.data;
  }

  async login(data: LoginPayload): Promise<LoginResponse> {
    const response = await api.post<LoginResponse>('/auth/login', data);
    return response.data;
  }

  async getProfile(): Promise<UserProfileResponse> {
    const response = await api.get<UserProfileResponse>('/auth/me');
    return response.data;
  }

  async forgotPassword(email: string): Promise<ForgotPasswordResponse> {
    const response = await api.post<ForgotPasswordResponse>('/auth/forgot-password', { email });
    return response.data;
  }

  async verifyResetToken(email: string, token: string): Promise<VerifyResetTokenResponse> {
    const response = await api.post<VerifyResetTokenResponse>('/auth/verify-reset-token', {
      email,
      token,
    });
    return response.data;
  }

  async resetPassword(email: string, token: string, newPassword: string): Promise<ResetPasswordResponse> {
    const response = await api.post<ResetPasswordResponse>('/auth/reset-password', {
      email,
      token,
      new_password: newPassword,
    });
    return response.data;
  }
}

export const authService = new AuthService();

import axios from 'axios';

const api = axios.create({
  baseURL: 'http://localhost:8000', // API Gateway URL
  headers: {
    'Content-Type': 'application/json',
  },
});

// Add interceptor to handle 401 Unauthorized
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Clear auth data and redirect to login
      localStorage.removeItem('token');
      localStorage.removeItem('userId');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

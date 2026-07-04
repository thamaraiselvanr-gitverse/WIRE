import axios from 'axios';

// Base URL is configurable at build time via VITE_API_BASE_URL so the same
// bundle can point at any backend; defaults to the local dev server.
export const API_BASE: string =
  import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const api = axios.create({
  baseURL: API_BASE,
});

// Interceptor to add JWT
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('wire_token');
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export default api;
 

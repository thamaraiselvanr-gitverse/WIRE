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

// Silent refresh: on a 401 (expired access token), exchange the rotating
// refresh token for a new pair and retry the request once. Concurrent 401s
// share one in-flight refresh so rotation isn't raced. On refresh failure
// the session is over: clear tokens and send the user back to login.
let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('wire_refresh_token');
  if (!refreshToken) return null;
  try {
    // Plain axios: the api instance's interceptors must not recurse here.
    const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
      refresh_token: refreshToken,
    });
    localStorage.setItem('wire_token', data.access_token);
    localStorage.setItem('wire_refresh_token', data.refresh_token);
    return data.access_token;
  } catch {
    localStorage.removeItem('wire_token');
    localStorage.removeItem('wire_refresh_token');
    return null;
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const original = error.config;
    const isAuthCall = original?.url?.includes('/auth/');
    if (error.response?.status === 401 && original && !original._retried && !isAuthCall) {
      original._retried = true;
      refreshInFlight = refreshInFlight ?? refreshAccessToken();
      const token = await refreshInFlight;
      refreshInFlight = null;
      if (token) {
        original.headers = { ...original.headers, Authorization: `Bearer ${token}` };
        return api.request(original);
      }
      window.location.href = '/';
    }
    return Promise.reject(error);
  },
);

/** Extract a human-readable message from an API/network error without `any`. */
export function apiErrorMessage(
  err: unknown,
  fallback = 'An error occurred.',
): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: string } | undefined;
    return data?.detail || err.message || fallback;
  }
  if (err instanceof Error) return err.message;
  return fallback;
}

export default api;
 

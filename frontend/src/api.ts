const API_BASE = import.meta.env.VITE_API_BASE?.replace(/\/$/, "") ||
  (window.location.protocol === "chrome-extension:" ? "http://127.0.0.1:8000" : "");
const AUTH_KEY = "clarity-auth-token";

export const getAuthToken = () => localStorage.getItem(AUTH_KEY);
export const setAuthToken = (token: string) => localStorage.setItem(AUTH_KEY, token);
export const clearAuthToken = () => localStorage.removeItem(AUTH_KEY);

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || `请求失败 (${response.status})`);
  }
  return response.json();
}

export const get = <T,>(path: string) => request<T>(path);
export const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
export const del = <T,>(path: string) => request<T>(path, { method: "DELETE" });

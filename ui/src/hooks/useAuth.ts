import { useCallback, useEffect, useState } from 'react';
import {
  type AuthUser,
  deleteAccount as apiDeleteAccount,
  fetchMe,
  login as apiLogin,
  logout as apiLogout,
  signup as apiSignup,
} from '../api';

const TOKEN_KEY = 'liva-session-token';

export interface AuthState {
  user: AuthUser | null;
  token: string | null;
  // `loading` is true while the initial /api/me probe is in flight.
  // Lets the app render a tiny "checking session..." instead of
  // flashing the LoginScreen for a tenth of a second on every reload.
  loading: boolean;
  error: string | null;
  signup: (username: string, password: string, displayName?: string) => Promise<void>;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  // Permanently delete the current user + all their memories. Drops
  // localStorage on success so the app falls back to LoginScreen.
  deleteAccount: (password: string) => Promise<void>;
  // Surface profile updates back into auth state so the LiveKit /api/token
  // response (which includes the latest user row) can refresh display
  // immediately without an extra /api/me round-trip.
  setUser: (user: AuthUser) => void;
}

/**
 * Manages the session JWT in localStorage and the cached user profile.
 *
 * Boot sequence:
 *   1. If a token is in localStorage, hit /api/me to validate it.
 *      - 200 → set user, hide loading.
 *      - 401 → clear localStorage, show LoginScreen.
 *   2. No token → show LoginScreen immediately.
 */
export function useAuth(): AuthState {
  const [token, setTokenState] = useState<string | null>(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState<boolean>(() => !!localStorage.getItem(TOKEN_KEY));
  const [error, setError] = useState<string | null>(null);

  // Re-validate token whenever it changes (login, signup, or initial mount).
  useEffect(() => {
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchMe(token).then(
      (u) => {
        if (cancelled) return;
        setUser(u);
        setLoading(false);
      },
      () => {
        if (cancelled) return;
        // Token expired or revoked. Boot back to LoginScreen.
        localStorage.removeItem(TOKEN_KEY);
        setTokenState(null);
        setUser(null);
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [token]);

  const signup = useCallback(async (username: string, password: string, displayName?: string) => {
    setError(null);
    try {
      const { user: u, session_token } = await apiSignup(username, password, displayName);
      localStorage.setItem(TOKEN_KEY, session_token);
      setTokenState(session_token);
      setUser(u);
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    setError(null);
    try {
      const { user: u, session_token } = await apiLogin(username, password);
      localStorage.setItem(TOKEN_KEY, session_token);
      setTokenState(session_token);
      setUser(u);
    } catch (e) {
      setError((e as Error).message);
      throw e;
    }
  }, []);

  const logout = useCallback(async () => {
    if (token) await apiLogout(token);
    localStorage.removeItem(TOKEN_KEY);
    setTokenState(null);
    setUser(null);
  }, [token]);

  const deleteAccount = useCallback(async (password: string) => {
    if (!token) return;
    await apiDeleteAccount(token, password);
    // Same teardown as logout — token is now useless server-side anyway.
    localStorage.removeItem(TOKEN_KEY);
    setTokenState(null);
    setUser(null);
  }, [token]);

  return { user, token, loading, error, signup, login, logout, deleteAccount, setUser };
}

import type { SessionSetup, TokenResponse, VoiceInfo } from './types';
import { AVATARS, DEFAULT_AVATAR_KEY } from './data/avatars';
import { languageFromVoice } from './data/voice_lang';

// ── Auth + Avatar types ────────────────────────────────────────────────
// AuthUser mirrors the User dataclass in src/db.py — auth/identity only.
// Persona/voice/avatar/mood/tools moved to Avatar (per-avatar, not
// per-user) so a user can have multiple companions, each with their
// own memory.
export interface AuthUser {
  id: string;
  username: string;
  display_name: string;
}

export interface Avatar {
  id: string;
  user_id: string;
  name: string;
  persona: string | null;
  voice: string | null;
  avatar_key: string | null;
  tools: string[];
  proactive: boolean;
  last_used_at: string | null;
}

interface AuthResponse {
  user: AuthUser;
  session_token: string;
}

// ── Voices / voice-sample (unchanged — public endpoints) ────────────────
export async function fetchVoices(): Promise<VoiceInfo[]> {
  const res = await fetch('/api/voices');
  if (!res.ok) throw new Error(`voices: HTTP ${res.status}`);
  const data = (await res.json()) as { voices: VoiceInfo[] };
  return data.voices;
}

export function voiceSampleUrl(voiceId: string, text: string): string {
  const params = new URLSearchParams({ voice: voiceId, text });
  return `/api/voice-sample?${params.toString()}`;
}

// ── Auth API ────────────────────────────────────────────────────────────
async function postJson<T>(path: string, body: unknown, token?: string | null): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const res = await fetch(path, {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as { error?: string };
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || `${path}: HTTP ${res.status}`);
  }
  return data as T;
}

export async function signup(
  username: string,
  password: string,
  display_name?: string,
): Promise<AuthResponse> {
  return postJson<AuthResponse>('/api/signup', { username, password, display_name });
}

export async function login(username: string, password: string): Promise<AuthResponse> {
  return postJson<AuthResponse>('/api/login', { username, password });
}

export async function logout(token: string): Promise<void> {
  // Best-effort — server is stateless so a network error is benign;
  // clearing localStorage is what actually logs the user out client-side.
  try {
    await postJson<{ ok: boolean }>('/api/logout', {}, token);
  } catch { /* swallow */ }
}

export async function fetchMe(token: string): Promise<AuthUser> {
  const res = await fetch('/api/me', { headers: { Authorization: `Bearer ${token}` } });
  const data = (await res.json().catch(() => ({}))) as { user?: AuthUser; error?: string };
  if (!res.ok || !data.user) {
    throw new Error(data.error || `me: HTTP ${res.status}`);
  }
  return data.user;
}

export async function deleteAccount(token: string): Promise<void> {
  // DELETE /api/me wipes the user row AND every Mem0 memory under
  // their id. The session JWT is then useless — caller is expected
  // to clear localStorage on a successful response.
  const res = await fetch('/api/me', {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(data.error || `delete: HTTP ${res.status}`);
  }
}

// ── Avatars CRUD ───────────────────────────────────────────────────────
async function authedFetch(path: string, token: string, init: RequestInit = {}): Promise<Response> {
  return fetch(path, {
    ...init,
    headers: {
      ...(init.headers || {}),
      Authorization: `Bearer ${token}`,
      ...(init.body ? { 'Content-Type': 'application/json' } : {}),
    },
  });
}

export async function listAvatars(token: string): Promise<Avatar[]> {
  const res = await authedFetch('/api/avatars', token);
  const data = (await res.json().catch(() => ({}))) as { avatars?: Avatar[]; error?: string };
  if (!res.ok) throw new Error(data.error || `avatars: HTTP ${res.status}`);
  return data.avatars || [];
}

export async function createAvatar(token: string, body: Partial<Avatar> & { name: string }): Promise<Avatar> {
  const res = await authedFetch('/api/avatars', token, {
    method: 'POST',
    body: JSON.stringify(body),
  });
  const data = (await res.json().catch(() => ({}))) as { avatar?: Avatar; error?: string };
  if (!res.ok || !data.avatar) throw new Error(data.error || `create: HTTP ${res.status}`);
  return data.avatar;
}

export async function getAvatar(token: string, avatarId: string): Promise<Avatar> {
  const res = await authedFetch(`/api/avatars/${avatarId}`, token);
  const data = (await res.json().catch(() => ({}))) as { avatar?: Avatar; error?: string };
  if (!res.ok || !data.avatar) throw new Error(data.error || `get: HTTP ${res.status}`);
  return data.avatar;
}

export async function updateAvatar(token: string, avatarId: string, patch: Partial<Avatar>): Promise<Avatar> {
  const res = await authedFetch(`/api/avatars/${avatarId}`, token, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
  const data = (await res.json().catch(() => ({}))) as { avatar?: Avatar; error?: string };
  if (!res.ok || !data.avatar) throw new Error(data.error || `update: HTTP ${res.status}`);
  return data.avatar;
}

export async function deleteAvatar(token: string, avatarId: string): Promise<void> {
  const res = await authedFetch(`/api/avatars/${avatarId}`, token, { method: 'DELETE' });
  if (!res.ok) {
    const data = (await res.json().catch(() => ({}))) as { error?: string };
    throw new Error(data.error || `delete: HTTP ${res.status}`);
  }
}

// ── Session token (LiveKit) ─────────────────────────────────────────────
export async function requestToken(
  setup: SessionSetup,
  token: string,
  avatarId: string,
): Promise<TokenResponse> {
  const avatar = AVATARS[setup.avatar] ?? AVATARS[DEFAULT_AVATAR_KEY];
  // Voice fully drives language. Any voice works with any avatar; if the
  // user didn't pick a voice, the agent picks an English default.
  const language = languageFromVoice(setup.voice, 'en');
  const payload = {
    ...setup,
    avatar_id: avatarId,    // tells the token server which avatar to bind the session to
    voice: setup.voice || null,
    body: avatar.body,
    language,
  };
  const res = await fetch('/api/token', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
  const data = (await res.json()) as TokenResponse & { error?: string };
  if (!res.ok || !data.token) {
    throw new Error(data.error || `token: HTTP ${res.status}`);
  }
  return data;
}

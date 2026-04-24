import type { SessionSetup, TokenResponse, VoiceInfo } from './types';
import { AVATARS, DEFAULT_AVATAR_KEY } from './data/avatars';

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

export async function requestToken(setup: SessionSetup): Promise<TokenResponse> {
  const avatar = AVATARS[setup.avatar] ?? AVATARS[DEFAULT_AVATAR_KEY];
  const payload = {
    ...setup,
    voice: setup.voice || null,
    body: avatar.body,
    language: avatar.language ?? 'en',
  };
  const res = await fetch('/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const data = (await res.json()) as TokenResponse & { error?: string };
  if (!res.ok || !data.token) {
    throw new Error(data.error || `token: HTTP ${res.status}`);
  }
  return data;
}

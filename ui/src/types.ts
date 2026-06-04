import type { Mood } from './data/cues';

export type Body = 'F' | 'M';

export type AvatarCategory = 'a' | 'm' | 'w';

export type { Mood };

export interface AvatarMeta {
  file: string;
  category: AvatarCategory;
  body: Body;
  label: string;
  lipsyncScale?: number;
  retarget?: Record<string, unknown>;
  baseline?: Record<string, number>;
  modelDynamicBones?: unknown[];
}

export interface ToolDef {
  id: string;
  label: string;
  description: string;
}

export type VoiceBackend = 'kokoro' | 'orpheus' | 'supertonic';

export interface VoiceInfo {
  id: string;
  language: string;
  gender: Body;
  grade: string;
  backend?: VoiceBackend;
  description?: string;
}

export interface SessionSetup {
  avatar: string;
  name: string;
  persona: string;
  mood: Mood;
  voice: string;
  tools: string[];
  camera: boolean;
  // Per-avatar opt-in: when true the agent runs ProactiveSpeaker on the
  // backend so the avatar will break silence and check in on the user.
  // Off by default — quiet companion mode is the safer baseline.
  proactive: boolean;
  // Per-avatar toggle for the ambient mood watcher (the small VLM that
  // reads facial expressions when camera is on). On by default to mirror
  // historical behavior; turn off when you don't want passive analysis
  // of your face but still want the camera available for chat.
  vision_watcher: boolean;
}

export interface TokenRequest extends Omit<SessionSetup, 'voice'> {
  body: Body;
  language: string;
  voice: string | null;
}

export interface TokenResponse {
  token: string;
  url: string;
  config: Record<string, unknown>;
}

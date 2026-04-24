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

export interface VoiceInfo {
  id: string;
  language: string;
  gender: Body;
  grade: string;
}

export interface SessionSetup {
  avatar: string;
  name: string;
  persona: string;
  mood: Mood;
  voice: string;
  tools: string[];
  camera: boolean;
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

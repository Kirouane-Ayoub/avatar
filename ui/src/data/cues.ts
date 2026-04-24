// Canonical cue vocabulary for the avatar — mirrors src/cues.py.
// The LLM emits `[mood:X][gesture:Y][pose:Z]` tags; the UI validates/routes
// those tags here. When editing, update src/cues.py too.

export const MOODS = [
  'neutral', 'happy', 'sad', 'angry', 'fear', 'disgust', 'love', 'sleep',
] as const;

export const GESTURES = [
  'handup', 'index', 'ok', 'thumbup', 'thumbdown', 'side', 'shrug', 'namaste',
] as const;

export const POSES = [
  'straight', 'side', 'hip', 'wide', 'turn', 'bend', 'back',
  'oneknee', 'kneel', 'sitting',
] as const;

export type Mood = typeof MOODS[number];
export type Gesture = typeof GESTURES[number];
export type Pose = typeof POSES[number];

export const POSE_SET: ReadonlySet<string> = new Set(POSES);

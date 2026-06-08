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

// Human-readable display names for the cue ids. The ids are terse engine
// tokens (`thumbup`, `oneknee`, `handup`); these are what we actually show
// to a person in the preview UI. Display-only — never sent to the agent.
export const MOOD_LABELS: Record<string, string> = {
  neutral: 'Neutral', happy: 'Happy', sad: 'Sad', angry: 'Angry',
  fear: 'Afraid', disgust: 'Disgusted', love: 'Loving', sleep: 'Sleepy',
};
export const GESTURE_LABELS: Record<string, string> = {
  handup: 'Wave', index: 'Point', ok: 'OK', thumbup: 'Thumbs up',
  thumbdown: 'Thumbs down', side: 'Open hand', shrug: 'Shrug', namaste: 'Namaste',
};
export const POSE_LABELS: Record<string, string> = {
  straight: 'Standing', side: 'Side stance', hip: 'Hand on hip', wide: 'Arms wide',
  turn: 'Turning', bend: 'Leaning', back: 'Leaning back', oneknee: 'One knee',
  kneel: 'Kneeling', sitting: 'Sitting',
};

/** Display label for a cue value, with a Title-cased fallback for any id
 *  that lacks an explicit label (e.g. a newly-added cue). */
export function cueLabel(kind: 'mood' | 'gesture' | 'pose', value: string): string {
  const map = kind === 'mood' ? MOOD_LABELS : kind === 'gesture' ? GESTURE_LABELS : POSE_LABELS;
  return map[value] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

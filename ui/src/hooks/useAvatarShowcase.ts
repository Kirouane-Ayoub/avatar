import { useCallback, useEffect, useRef, useState } from 'react';
import { MOODS, GESTURES, POSES, cueLabel } from '../data/cues';
import { phonemizeWord } from '../data/phonemes';

type Kind = 'mood' | 'gesture' | 'pose' | 'lipsync';
export interface ShowcaseStep { kind: Kind; value: string }
export interface ShowcaseCurrent {
  step: ShowcaseStep;
  /** Human-readable name of the move on screen (e.g. "Thumbs up"). */
  label: string;
  index: number;
  total: number;
}

export interface ShowcaseState {
  /** True from start() until the run finishes or is stopped. */
  running: boolean;
  /** The move on screen right now (+ progress), or null when idle. */
  current: ShowcaseCurrent | null;
  start: () => void;
  stop: () => void;
}

// Short, friendly sentence the lip-sync demo "speaks". Kept brief so the
// preview is quick; punctuation is stripped per word before phonemizing.
const LIPSYNC_SAMPLE = 'Hey — watch my mouth move while I talk!';

// One ordered run: every mood (face close-up), every gesture, every pose,
// then a lip-sync demo. Moods/gestures/poses come from the canonical cue
// vocabulary so they stay in sync with what the agent can emit.
function buildRun(): ShowcaseStep[] {
  return [
    ...MOODS.map((value) => ({ kind: 'mood' as const, value })),
    ...GESTURES.map((value) => ({ kind: 'gesture' as const, value })),
    ...POSES.map((value) => ({ kind: 'pose' as const, value })),
    { kind: 'lipsync' as const, value: LIPSYNC_SAMPLE },
  ];
}

// How long each (non-lipsync) move is held before advancing. Poses tween
// over ~1.5 s and need a beat to settle; gestures are quick; moods instant.
const HOLD_MS: Record<'mood' | 'gesture' | 'pose', number> = {
  mood: 1300, gesture: 1900, pose: 2600,
};
// Moods + lip-sync read on the face → head close-up. Gestures and poses are
// whole-body movements → full framing so arms/stance stay in shot.
const VIEW_FOR: Record<Kind, 'head' | 'upper' | 'full'> = {
  mood: 'head', gesture: 'full', pose: 'full', lipsync: 'head',
};
export const KIND_LABEL: Record<Kind, string> = {
  mood: 'Mood', gesture: 'Gesture', pose: 'Pose', lipsync: 'Lip sync',
};

// ── Lip-sync demo internals ──────────────────────────────────────────────
// Drives the same morphs the live lipsync driver does (viseme_* + jawOpen),
// but from a synthetic timeline instead of agent audio + word timestamps, so
// it works in the editor preview where there's no session.
const ALL_VISEMES = [
  'sil', 'PP', 'FF', 'TH', 'DD', 'kk', 'CH', 'SS', 'nn', 'RR',
  'aa', 'E', 'I', 'O', 'U',
];
const VOWEL_VISEMES = new Set(['aa', 'E', 'I', 'O', 'U']);

function setMorph(head: TalkingHeadInstance, name: string, val: number) {
  if (!head.morphs) return;
  for (const m of head.morphs) {
    const i = m.morphTargetDictionary?.[name];
    if (i !== undefined && m.morphTargetInfluences) m.morphTargetInfluences[i] = val;
  }
}
function clearMouth(head: TalkingHeadInstance) {
  setMorph(head, 'jawOpen', 0);
  ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
}

interface TimedViseme { vis: string; start: number; end: number }

// Phonemize the sample into an absolute viseme timeline (ms). Falls back to a
// simple alternating open/close per character if the EN phonemizer isn't
// loaded, so the mouth still moves.
function buildLipsyncTimeline(text: string): { items: TimedViseme[]; duration: number } {
  const words = text.split(/\s+/).filter(Boolean);
  const items: TimedViseme[] = [];
  const GAP = 110;
  let cursor = 0;
  for (const w of words) {
    const clean = w.replace(/[^A-Za-z']/g, '');
    if (!clean) continue;
    const ph = phonemizeWord(clean, 'en');
    if (ph && ph.visemes.length > 0) {
      const dur = Math.max(280, ph.visemes.length * 95);
      ph.visemes.forEach((vis, i) => {
        items.push({ vis, start: cursor + ph.starts[i] * dur, end: cursor + ph.ends[i] * dur });
      });
      cursor += dur + GAP;
    } else {
      const per = 95;
      for (let i = 0; i < clean.length; i++) {
        items.push({ vis: i % 2 === 0 ? 'aa' : 'DD', start: cursor + i * per, end: cursor + (i + 1) * per });
      }
      cursor += clean.length * per + GAP;
    }
  }
  return { items, duration: cursor + 250 };
}

function runLipsyncDemo(
  head: TalkingHeadInstance,
  scale: number,
): { duration: number; cancel: () => void } {
  const { items, duration } = buildLipsyncTimeline(LIPSYNC_SAMPLE);
  const t0 = performance.now();
  let raf = 0;
  let cancelled = false;
  const frame = () => {
    if (cancelled) return;
    const elapsed = performance.now() - t0;
    let active: TimedViseme | null = null;
    for (const it of items) {
      if (elapsed >= it.start && elapsed < it.end) { active = it; break; }
    }
    ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
    if (active) {
      setMorph(head, 'viseme_' + active.vis, 0.42 * scale);
      setMorph(head, 'jawOpen', (VOWEL_VISEMES.has(active.vis) ? 0.26 : 0.1) * scale);
    } else {
      setMorph(head, 'jawOpen', 0);
    }
    if (elapsed < duration) raf = requestAnimationFrame(frame);
    else clearMouth(head);
  };
  raf = requestAnimationFrame(frame);
  return {
    duration,
    cancel: () => { cancelled = true; cancelAnimationFrame(raf); clearMouth(head); },
  };
}

/**
 * Drives a TalkingHead instance through every mood, gesture, and pose — then a
 * lip-sync demo — on a timer, so a user can preview the avatar's full range
 * before picking it.
 *
 * Logic lives in a hook (not the component) so the trigger and the live
 * status readout can render in different places — e.g. in kiosk mode the
 * "Preview" button sits in the Customize sheet while the running card floats
 * over the full-bleed avatar after the sheet closes.
 *
 * Drives the avatar imperatively (bypassing React mood/view state so it
 * doesn't fight the editor's own effects); restores the editor's framing +
 * mood on finish/stop.
 */
export function useAvatarShowcase(
  head: TalkingHeadInstance | null,
  opts: { restoreView?: 'head' | 'upper' | 'full'; restoreMood?: string; lipsyncScale?: number } = {},
): ShowcaseState {
  const { restoreView = 'full', restoreMood = 'neutral', lipsyncScale = 1 } = opts;
  const [current, setCurrent] = useState<ShowcaseCurrent | null>(null);
  const [running, setRunning] = useState(false);
  const cancelRef = useRef(false);
  const runningRef = useRef(false);
  const lipsyncCancelRef = useRef<null | (() => void)>(null);

  const sleep = (ms: number) =>
    new Promise<void>((resolve) => window.setTimeout(resolve, ms));

  const apply = useCallback((step: ShowcaseStep) => {
    if (!head) return;
    try {
      head.setView(VIEW_FOR[step.kind]);
      if (step.kind === 'mood') {
        head.setMood(step.value);
      } else if (step.kind === 'gesture') {
        // Neutral face so the hand/arm gesture reads on its own.
        head.setMood('neutral');
        head.playGesture(step.value, 2.5, false, 600);
      } else if (step.kind === 'pose') {
        head.setMood('neutral');
        const tpl = head.poseTemplates?.[step.value];
        if (tpl && head.setPoseFromTemplate) head.setPoseFromTemplate(tpl, 1500);
      }
    } catch { /* ignore — a single bad morph shouldn't kill the run */ }
  }, [head]);

  const cancelLipsync = useCallback(() => {
    if (lipsyncCancelRef.current) {
      lipsyncCancelRef.current();
      lipsyncCancelRef.current = null;
    }
  }, []);

  const restore = useCallback(() => {
    if (!head) return;
    cancelLipsync();
    try {
      clearMouth(head);
      const tpl = head.poseTemplates?.['straight'];
      if (tpl && head.setPoseFromTemplate) head.setPoseFromTemplate(tpl, 800);
      head.setMood(restoreMood);
      head.setView(restoreView);
    } catch { /* ignore */ }
  }, [head, restoreMood, restoreView, cancelLipsync]);

  const stop = useCallback(() => {
    cancelRef.current = true;
    runningRef.current = false;
    setRunning(false);
    setCurrent(null);
    restore();
  }, [restore]);

  const start = useCallback(async () => {
    if (!head || runningRef.current) return;
    const run = buildRun();
    cancelRef.current = false;
    runningRef.current = true;
    setRunning(true);
    for (let i = 0; i < run.length; i++) {
      if (cancelRef.current) break;
      const step = run[i];
      const label = step.kind === 'lipsync' ? step.value : cueLabel(step.kind, step.value);
      setCurrent({ step, label, index: i + 1, total: run.length });
      let holdMs: number;
      if (step.kind === 'lipsync') {
        try { head.setView(VIEW_FOR.lipsync); head.setMood('neutral'); } catch { /* ignore */ }
        const demo = runLipsyncDemo(head, lipsyncScale);
        lipsyncCancelRef.current = demo.cancel;
        holdMs = demo.duration;
      } else {
        apply(step);
        holdMs = HOLD_MS[step.kind];
      }
      await sleep(holdMs);
      cancelLipsync();
    }
    if (!cancelRef.current) {
      runningRef.current = false;
      setRunning(false);
      setCurrent(null);
      restore();
    }
  }, [head, apply, restore, cancelLipsync, lipsyncScale]);

  // Abort the run if the avatar unloads or swaps mid-showcase.
  useEffect(() => {
    return () => {
      cancelRef.current = true;
      runningRef.current = false;
      cancelLipsync();
    };
  }, [head, cancelLipsync]);

  return { running, current, start, stop };
}

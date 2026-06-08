import { useCallback, useEffect, useRef, useState } from 'react';
import { MOODS, GESTURES, POSES } from '../data/cues';

interface Props {
  head: TalkingHeadInstance | null;
  // Framing + mood to restore to when the showcase ends or is stopped, so
  // the stage returns to whatever the editor was showing.
  restoreView?: 'head' | 'upper' | 'full';
  restoreMood?: string;
}

type Kind = 'mood' | 'gesture' | 'pose';
interface Step { kind: Kind; value: string }

// One ordered run: every mood (face close-up), then every gesture (upper
// framing), then every pose (full body). Pulls straight from the canonical
// cue vocabulary so it stays in sync with what the agent can actually emit.
function buildRun(): Step[] {
  return [
    ...MOODS.map((value) => ({ kind: 'mood' as const, value })),
    ...GESTURES.map((value) => ({ kind: 'gesture' as const, value })),
    ...POSES.map((value) => ({ kind: 'pose' as const, value })),
  ];
}

// How long each move is held on screen before advancing. Poses tween over
// ~1.5 s and need a beat to settle; gestures are quick; moods are instant.
const HOLD_MS: Record<Kind, number> = { mood: 1300, gesture: 1900, pose: 2600 };
// Moods read on the face → close-up head framing. Gestures and poses are
// whole-body movements → full framing so arms/stance stay in shot.
const VIEW_FOR: Record<Kind, 'head' | 'upper' | 'full'> = {
  mood: 'head',
  gesture: 'full',
  pose: 'full',
};
const KIND_LABEL: Record<Kind, string> = {
  mood: 'Mood',
  gesture: 'Gesture',
  pose: 'Pose',
};

/**
 * "Preview all moves" control on the avatar stage. Lets a user watch every
 * mood, gesture, and pose the avatar can do before committing to it — the
 * same vocabulary the LLM drives during a real session, run on a timer.
 *
 * Drives the avatar imperatively via the TalkingHead instance (bypassing the
 * editor's mood/view React state), so it doesn't fight the preview's own
 * state effects. On finish/stop it restores the editor's framing + mood.
 */
export function AvatarShowcase({ head, restoreView = 'full', restoreMood = 'neutral' }: Props) {
  const [current, setCurrent] = useState<{ step: Step; index: number; total: number } | null>(null);
  const cancelRef = useRef(false);
  const runningRef = useRef(false);

  const sleep = (ms: number) =>
    new Promise<void>((resolve) => window.setTimeout(resolve, ms));

  const apply = useCallback((step: Step) => {
    if (!head) return;
    try {
      head.setView(VIEW_FOR[step.kind]);
      if (step.kind === 'mood') {
        head.setMood(step.value);
      } else if (step.kind === 'gesture') {
        // Neutral face so the hand/arm gesture reads on its own.
        head.setMood('neutral');
        head.playGesture(step.value, 2.5, false, 600);
      } else {
        head.setMood('neutral');
        const tpl = head.poseTemplates?.[step.value];
        if (tpl && head.setPoseFromTemplate) head.setPoseFromTemplate(tpl, 1500);
      }
    } catch { /* ignore — a single bad morph shouldn't kill the run */ }
  }, [head]);

  const restore = useCallback(() => {
    if (!head) return;
    try {
      const tpl = head.poseTemplates?.['straight'];
      if (tpl && head.setPoseFromTemplate) head.setPoseFromTemplate(tpl, 800);
      head.setMood(restoreMood);
      head.setView(restoreView);
    } catch { /* ignore */ }
  }, [head, restoreMood, restoreView]);

  const stop = useCallback(() => {
    cancelRef.current = true;
    runningRef.current = false;
    setCurrent(null);
    restore();
  }, [restore]);

  const start = useCallback(async () => {
    if (!head || runningRef.current) return;
    const run = buildRun();
    cancelRef.current = false;
    runningRef.current = true;
    for (let i = 0; i < run.length; i++) {
      if (cancelRef.current) break;
      const step = run[i];
      setCurrent({ step, index: i + 1, total: run.length });
      apply(step);
      await sleep(HOLD_MS[step.kind]);
    }
    if (!cancelRef.current) {
      runningRef.current = false;
      setCurrent(null);
      restore();
    }
  }, [head, apply, restore]);

  // Abort the run if the avatar unloads or swaps mid-showcase.
  useEffect(() => {
    return () => {
      cancelRef.current = true;
      runningRef.current = false;
    };
  }, [head]);

  if (!head) return null;

  return (
    <div className="showcase">
      {!current ? (
        <button
          type="button"
          className="showcase-btn"
          onClick={start}
          title="Preview every mood, gesture, and pose this avatar can do"
        >
          ▶ Preview all moves
        </button>
      ) : (
        <div className="showcase-running" role="status" aria-live="polite">
          <div className="showcase-now">
            <span className="showcase-kind">{KIND_LABEL[current.step.kind]}</span>
            <span className="showcase-value">{current.step.value}</span>
          </div>
          <div className="showcase-meta">
            <span className="showcase-count">{current.index} / {current.total}</span>
            <button type="button" className="showcase-stop" onClick={stop}>Stop</button>
          </div>
        </div>
      )}
    </div>
  );
}

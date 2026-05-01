import type { Mood } from '../types';
import { MOODS } from '../data/moods';

interface Props {
  value: Mood;
  onChange: (mood: Mood) => void;
}

// Emoji glyphs make the strip readable at a glance — a text-only row
// of mood names felt list-like; on the stage we want it to read as a
// row of expressions.
const MOOD_GLYPH: Record<string, string> = {
  neutral: '😐',
  happy: '😊',
  sad: '😢',
  angry: '😠',
  fear: '😨',
  disgust: '🤢',
  love: '🥰',
  sleep: '😴',
};

/**
 * Floating expression-preview strip rendered over the avatar stage.
 * Lives over the canvas (not in the form grid) because mood is
 * preview-only: nothing about the user's pick is saved or sent to the
 * agent. Mood during conversation is driven by the LLM cue tags and
 * the ambient affect watcher.
 *
 * Visually this is a small horizontal row of emoji-led chips with a
 * "Try expressions" hint above so users understand it's a viewing
 * control, not a setting.
 */
export function StageMoodStrip({ value, onChange }: Props) {
  return (
    <div className="stage-mood-strip" role="group" aria-label="Try expressions">
      <div className="stage-mood-hint" title="Mood updates automatically during conversation — this just changes the preview">
        Try expressions
      </div>
      <div className="stage-mood-chips">
        {MOODS.map((m) => (
          <button
            key={m}
            type="button"
            className={`stage-mood-chip${value === m ? ' active' : ''}`}
            onClick={() => onChange(m)}
            // Tooltip + aria-label carry the mood name now that the
            // visible text label has been dropped to keep the strip
            // narrow enough to coexist with the bottom-right camera.
            title={m.charAt(0).toUpperCase() + m.slice(1)}
            aria-label={m}
            aria-pressed={value === m}
          >
            <span className="stage-mood-glyph">{MOOD_GLYPH[m] || '·'}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

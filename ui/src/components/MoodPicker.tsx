import type { Mood } from '../types';
import { MOODS } from '../data/moods';

interface Props {
  value: Mood;
  onChange: (mood: Mood) => void;
}

export function MoodPicker({ value, onChange }: Props) {
  return (
    <div className="mood-picker">
      {MOODS.map((m) => (
        <button
          key={m}
          type="button"
          className={`mood-chip${value === m ? ' active' : ''}`}
          onClick={() => onChange(m)}
        >
          {m}
        </button>
      ))}
    </div>
  );
}

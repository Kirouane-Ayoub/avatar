import { useMemo } from 'react';
import { PERSONA_PRESETS } from '../data/personas';

interface Props {
  value: string;
  onChange: (text: string) => void;
}

const MAX_LEN = 2000;

/**
 * Persona picker: three preset cards across the top + a clearly-labeled
 * "Write your own" textarea below. Preset cards show label + a one-line
 * teaser so users can pick at a glance without reading the full prompt.
 *
 * The textarea is the customization path. When `value` doesn't match any
 * preset, the cards de-highlight and a small "Custom" indicator shows
 * above the textarea so the user understands their text is in effect.
 */
export function PersonaField({ value, onChange }: Props) {
  const trimmed = value.trim();

  // Which preset (if any) is currently selected. Equality is on
  // trimmed text so trailing whitespace from copy/paste doesn't break
  // the highlight.
  const activePresetId = useMemo(() => {
    const match = PERSONA_PRESETS.find((p) => trimmed === p.text.trim());
    return match?.id ?? null;
  }, [trimmed]);

  const isCustom = trimmed.length > 0 && activePresetId === null;
  const charsLeft = MAX_LEN - value.length;
  const charClass =
    charsLeft < 0 ? 'over' : charsLeft < 100 ? 'warn' : 'ok';

  return (
    <div className="persona-field">
      <div className="persona-presets">
        {PERSONA_PRESETS.map((p) => (
          <button
            key={p.id}
            type="button"
            className={`preset-card${activePresetId === p.id ? ' active' : ''}`}
            onClick={() => onChange(p.text)}
            title={p.text}
          >
            <span className="preset-label">{p.label}</span>
            <span className="preset-hint">{p.hint}</span>
          </button>
        ))}
      </div>

      <div className="persona-custom">
        <div className="persona-custom-head">
          <label htmlFor="persona-textarea" className="persona-custom-label">
            Or write your own
          </label>
          {isCustom && <span className="persona-custom-badge">custom</span>}
          <span className={`persona-charcount ${charClass}`}>
            {value.length}/{MAX_LEN}
          </span>
        </div>
        <textarea
          id="persona-textarea"
          rows={4}
          maxLength={MAX_LEN}
          value={value}
          placeholder="A late-30s woodworker who explains things via metaphors. Calm, deliberate. Drops ‘mm-hm’ when thinking..."
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </div>
  );
}

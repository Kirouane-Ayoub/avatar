import { PERSONA_PRESETS } from '../data/personas';

interface Props {
  value: string;
  onChange: (text: string) => void;
}

export function PersonaField({ value, onChange }: Props) {
  return (
    <div className="persona-field">
      <div className="persona-presets">
        {PERSONA_PRESETS.map((p) => {
          const active = value.trim() === p.text.trim();
          return (
            <button
              key={p.id}
              type="button"
              className={`preset-card${active ? ' active' : ''}`}
              onClick={() => onChange(p.text)}
              title={p.text}
            >
              {p.label}
            </button>
          );
        })}
      </div>
      <textarea
        rows={3}
        maxLength={2000}
        value={value}
        placeholder="Or describe their vibe in your own words..."
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

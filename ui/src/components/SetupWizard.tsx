import { useCallback, useEffect, useState } from 'react';
import type { SessionSetup } from '../types';
import { AVATARS } from '../data/avatars';
import { TOOL_CATALOG } from '../data/tools';
import { AvatarPicker } from './AvatarPicker';
import { TalkingHeadView } from './TalkingHeadView';
import { MoodPicker } from './MoodPicker';
import { VoicePicker } from './VoicePicker';
import { PersonaField } from './PersonaField';
import { DevicePanel } from './DevicePanel';

interface Props {
  setup: SessionSetup;
  onChange: (patch: Partial<SessionSetup>) => void;
  onStart: (devices: { micId: string | null; camId: string | null }) => void;
  starting: boolean;
  error: string | null;
}

export function SetupWizard({ setup, onChange, onStart, starting, error }: Props) {
  const [micId, setMicId] = useState<string>('');
  const [camId, setCamId] = useState<string>('');

  const currentAvatar = AVATARS[setup.avatar] ?? AVATARS.brunette;

  const cycleAvatar = useCallback(
    (dir: 1 | -1) => {
      const keys = Object.keys(AVATARS);
      const idx = keys.indexOf(setup.avatar);
      const next = keys[(idx + dir + keys.length) % keys.length];
      onChange({ avatar: next });
    },
    [setup.avatar, onChange],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
      if (e.key === 'ArrowLeft') { e.preventDefault(); cycleAvatar(-1); }
      if (e.key === 'ArrowRight') { e.preventDefault(); cycleAvatar(1); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [cycleAvatar]);

  const toggleTool = (id: string) => {
    const next = setup.tools.includes(id)
      ? setup.tools.filter((t) => t !== id)
      : [...setup.tools, id];
    onChange({ tools: next });
  };

  const canStart = !!setup.name.trim() && !starting;

  return (
    <div className="builder">
      <AvatarPicker
        selected={setup.avatar}
        onSelect={(key) => onChange({ avatar: key })}
      />

      <div className="stage">
        <div className="stage-preview">
          <TalkingHeadView avatar={currentAvatar} mood={setup.mood} />
          <DevicePanel
            cameraOn={setup.camera}
            onCameraChange={(on) => onChange({ camera: on })}
            micId={micId}
            onMicChange={setMicId}
            camId={camId}
            onCamChange={setCamId}
          />
          <div className="stage-hud">
            <div className="stage-title">{currentAvatar.label}</div>
            <div className="stage-sub">
              {currentAvatar.body === 'F' ? 'female' : 'male'}
              <span className="kbd-hint"> · ← → to cycle</span>
            </div>
          </div>
        </div>

        <div className="stage-form">
          <div className="form-header">
            <h2>Build your companion</h2>
            <p>Pick an avatar, give them a voice, a persona, and abilities.</p>
          </div>

          <div className="form-grid">
            <div className="form-field">
              <label>Name</label>
              <input
                type="text"
                maxLength={60}
                value={setup.name}
                placeholder="Lisa"
                onChange={(e) => onChange({ name: e.target.value })}
              />
            </div>

            <div className="form-field">
              <label>Mood</label>
              <MoodPicker
                value={setup.mood}
                onChange={(mood) => onChange({ mood })}
              />
            </div>

            <div className="form-field span-2">
              <label>Persona</label>
              <PersonaField
                value={setup.persona}
                onChange={(text) => onChange({ persona: text })}
              />
            </div>

            <div className="form-field span-2">
              <label>Voice</label>
              <VoicePicker
                value={setup.voice}
                onChange={(voice) => onChange({ voice })}
                name={setup.name}
              />
            </div>

            <div className="form-field span-2">
              <label>Abilities</label>
              <div className="tool-chips">
                {TOOL_CATALOG.map((t) => {
                  const checked = setup.tools.includes(t.id);
                  return (
                    <button
                      key={t.id}
                      type="button"
                      className={`tool-chip${checked ? ' on' : ''}`}
                      title={t.description}
                      aria-pressed={checked}
                      onClick={() => toggleTool(t.id)}
                    >
                      <span className="tool-check" aria-hidden />
                      {t.label}
                    </button>
                  );
                })}
              </div>
            </div>

          </div>

          {error && <div className="form-error">{error}</div>}

          <div className="form-footer">
            <div className="form-footer-info">
              {setup.voice
                ? <>Voice: <b>{setup.voice}</b></>
                : <>Voice: <b>auto</b> (from avatar)</>}
            </div>
            <button
              type="button"
              className="start-btn"
              disabled={!canStart}
              onClick={() => onStart({ micId: micId || null, camId: camId || null })}
            >
              {starting ? 'Starting…' : `Start session${setup.name ? ` with ${setup.name}` : ''}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

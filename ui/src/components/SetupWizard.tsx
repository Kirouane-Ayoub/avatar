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

type PreviewView = 'head' | 'upper' | 'full';
const VIEW_OPTIONS: { id: PreviewView; label: string }[] = [
  { id: 'head', label: 'Head' },
  { id: 'upper', label: 'Upper' },
  { id: 'full', label: 'Full' },
];

export function SetupWizard({ setup, onChange, onStart, starting, error }: Props) {
  const [micId, setMicId] = useState<string>('');
  const [camId, setCamId] = useState<string>('');
  const [view, setView] = useState<PreviewView>('full');
  const [railCollapsed, setRailCollapsed] = useState(
    () => localStorage.getItem('avatar.railCollapsed') === '1',
  );
  const [formCollapsed, setFormCollapsed] = useState(
    () => localStorage.getItem('avatar.formCollapsed') === '1',
  );

  useEffect(() => {
    localStorage.setItem('avatar.railCollapsed', railCollapsed ? '1' : '0');
  }, [railCollapsed]);
  useEffect(() => {
    localStorage.setItem('avatar.formCollapsed', formCollapsed ? '1' : '0');
  }, [formCollapsed]);

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
    <div
      className={`builder${railCollapsed ? ' rail-collapsed' : ''}${
        formCollapsed ? ' form-collapsed' : ''
      }`}
    >
      {railCollapsed ? (
        <button
          type="button"
          className="panel-stub stub-left"
          onClick={() => setRailCollapsed(false)}
          title="Show avatars"
          aria-label="Show avatars panel"
        >
          ›
        </button>
      ) : (
        <div className="rail-wrap">
          <AvatarPicker
            selected={setup.avatar}
            onSelect={(key) => onChange({ avatar: key })}
          />
          <button
            type="button"
            className="panel-toggle toggle-rail"
            onClick={() => setRailCollapsed(true)}
            title="Hide avatars"
            aria-label="Hide avatars panel"
          >
            ‹
          </button>
        </div>
      )}

      <div className="stage">
        <div className="stage-preview">
          <TalkingHeadView avatar={currentAvatar} mood={setup.mood} view={view} />
          <div className="view-toggle" role="group" aria-label="Preview framing">
            {VIEW_OPTIONS.map((v) => (
              <button
                key={v.id}
                type="button"
                className={`view-toggle-btn${view === v.id ? ' on' : ''}`}
                aria-pressed={view === v.id}
                onClick={() => setView(v.id)}
              >
                {v.label}
              </button>
            ))}
          </div>
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

        {formCollapsed ? (
          <button
            type="button"
            className="panel-stub stub-right"
            onClick={() => setFormCollapsed(false)}
            title="Show build panel"
            aria-label="Show build panel"
          >
            ‹
          </button>
        ) : (
        <div className="stage-form">
          <button
            type="button"
            className="panel-toggle toggle-form"
            onClick={() => setFormCollapsed(true)}
            title="Hide build panel"
            aria-label="Hide build panel"
          >
            ›
          </button>
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
                placeholder="Liva"
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
        )}
      </div>
    </div>
  );
}

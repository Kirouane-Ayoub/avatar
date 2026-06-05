import { useEffect, useState, type ReactNode } from 'react';
import type { ThemeAccent, ThemeMode } from '../hooks/useTheme';
import { ACCENT_OPTIONS } from '../hooks/useTheme';

interface Props {
  open: boolean;
  onClose: () => void;
  username?: string;
  mode: ThemeMode;
  accent: ThemeAccent;
  onModeChange: (m: ThemeMode) => void;
  onAccentChange: (a: ThemeAccent) => void;
  kiosk?: boolean;
  onKioskChange?: (v: boolean) => void;
}

type Section = 'appearance' | 'profile';

const MODES: { id: ThemeMode; label: string; icon: ReactNode }[] = [
  { id: 'light', label: 'Light', icon: <SunIcon /> },
  { id: 'dark', label: 'Dark', icon: <MoonIcon /> },
  { id: 'system', label: 'System', icon: <SystemIcon /> },
];

/**
 * Settings home — a left-nav modal. "Appearance" (theme mode + accent) is
 * live; "Profile" is a scaffolded slot for the upcoming profile feature so
 * there's an obvious place to grow into. Reachable app-wide via the floating
 * control in App.tsx. Closes on overlay click or Escape.
 */
export function SettingsModal({
  open, onClose, username, mode, accent, onModeChange, onAccentChange,
  kiosk = false, onKioskChange,
}: Props) {
  const [section, setSection] = useState<Section>('appearance');

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="settings-overlay" onMouseDown={onClose}>
      <div
        className="settings-modal"
        role="dialog"
        aria-modal="true"
        aria-label="Settings"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <aside className="settings-nav">
          <div className="settings-nav-title">Settings</div>
          <button
            type="button"
            className={`settings-nav-item${section === 'appearance' ? ' active' : ''}`}
            onClick={() => setSection('appearance')}
          >
            <PaletteIcon /> <span>Appearance</span>
          </button>
          <button
            type="button"
            className={`settings-nav-item${section === 'profile' ? ' active' : ''}`}
            onClick={() => setSection('profile')}
          >
            <UserIcon /> <span>Profile</span>
          </button>
        </aside>

        <div className="settings-body">
          <button type="button" className="settings-close" onClick={onClose} aria-label="Close settings">
            <CloseIcon />
          </button>

          {section === 'appearance' && (
            <div className="settings-section">
              <h3 className="settings-title">Appearance</h3>
              <p className="settings-desc">Choose a mode and accent color. Saved to this browser.</p>

              <div className="settings-group">
                <div className="settings-label">Mode</div>
                <div className="mode-segment" role="radiogroup" aria-label="Color mode">
                  {MODES.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      role="radio"
                      aria-checked={mode === m.id}
                      className={`mode-seg${mode === m.id ? ' active' : ''}`}
                      onClick={() => onModeChange(m.id)}
                    >
                      {m.icon}<span>{m.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div className="settings-group">
                <div className="settings-label">Accent</div>
                <div className="accent-swatches" role="radiogroup" aria-label="Accent color">
                  {ACCENT_OPTIONS.map((a) => (
                    <button
                      key={a.id}
                      type="button"
                      role="radio"
                      aria-checked={accent === a.id}
                      className={`accent-swatch${accent === a.id ? ' active' : ''}`}
                      onClick={() => onAccentChange(a.id)}
                      title={a.label}
                    >
                      <span
                        className="accent-swatch-dot"
                        style={{ background: `linear-gradient(135deg, ${a.from}, ${a.to})` }}
                      />
                      <span className="accent-swatch-label">{a.label}</span>
                    </button>
                  ))}
                </div>
              </div>

              {onKioskChange && (
                <div className="settings-group">
                  <div className="settings-label">Display</div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={kiosk}
                    className={`settings-toggle${kiosk ? ' on' : ''}`}
                    onClick={() => onKioskChange(!kiosk)}
                  >
                    <span className="settings-toggle-track"><span className="settings-toggle-thumb" /></span>
                    <span className="settings-toggle-text">
                      <span className="settings-toggle-title">Kiosk mode</span>
                      <span className="settings-toggle-hint">
                        Full-screen avatar + reachable control dock for large vertical touch screens
                      </span>
                    </span>
                  </button>
                </div>
              )}
            </div>
          )}

          {section === 'profile' && (
            <div className="settings-section">
              <h3 className="settings-title">Profile</h3>
              {username && (
                <p className="settings-desc">
                  Signed in as <strong>@{username}</strong>.
                </p>
              )}
              <div className="settings-placeholder">
                <UserIcon />
                <p>More profile settings are coming soon.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── inline icons (Lucide-style, 1.7 stroke) ─────────────────────────── */
function SunIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
    </svg>
  );
}
function MoonIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}
function SystemIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <rect x="2" y="3" width="20" height="14" rx="2" /><path d="M8 21h8M12 17v4" />
    </svg>
  );
}
function PaletteIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="13.5" cy="6.5" r=".5" fill="currentColor" /><circle cx="17.5" cy="10.5" r=".5" fill="currentColor" />
      <circle cx="8.5" cy="7.5" r=".5" fill="currentColor" /><circle cx="6.5" cy="12.5" r=".5" fill="currentColor" />
      <path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.926 0 1.648-.746 1.648-1.688 0-.437-.18-.835-.437-1.125-.29-.289-.438-.652-.438-1.125a1.64 1.64 0 0 1 1.668-1.668h1.996c3.051 0 5.555-2.503 5.555-5.554C21.965 6.012 17.461 2 12 2z" />
    </svg>
  );
}
function UserIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" />
    </svg>
  );
}
function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

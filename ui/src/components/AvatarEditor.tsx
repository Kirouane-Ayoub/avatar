import { useCallback, useEffect, useState } from 'react';
import type { SessionSetup } from '../types';
import type { AuthUser } from '../api';
import { AVATARS } from '../data/avatars';
import { TOOL_CATALOG } from '../data/tools';
import { AvatarPicker } from './AvatarPicker';
import { TalkingHeadView } from './TalkingHeadView';
import { AvatarShowcase } from './AvatarShowcase';
import { useAvatarShowcase, KIND_LABEL } from '../hooks/useAvatarShowcase';
import { StageMoodStrip } from './StageMoodStrip';
import { VoicePicker } from './VoicePicker';
import { PersonaField } from './PersonaField';
import { DevicePanel } from './DevicePanel';
import { UserMenu } from './UserMenu';
import { ConfirmDialog } from './ConfirmDialog';

interface Props {
  setup: SessionSetup;
  onChange: (patch: Partial<SessionSetup>) => void;
  onStart: (devices: { micId: string | null; camId: string | null }) => void;
  starting: boolean;
  error: string | null;
  // Optional so the wizard stays usable in non-auth contexts (tests,
  // future single-user demo mode). When passed, a small "logged in as
  // X / Sign out / Delete account" widget renders in the top corner.
  user?: AuthUser;
  onLogout?: () => void | Promise<void>;
  // Permanently delete the user + all memories. Wizard prompts for the
  // username typed back AND the current password as confirmation
  // before calling — JWT alone isn't enough authority for irreversible
  // wipe.
  onDeleteAccount?: (password: string) => void | Promise<void>;
  // Return to the avatar picker without disconnecting / signing out.
  // Wizard is per-avatar so this is the "switch companion" affordance.
  // Per-avatar "Forget memory" lives on the picker cards, not here.
  onBackToPicker?: () => void;
  // Large-format vertical touch screen (kiosk): full-bleed avatar + a
  // floating control dock / config sheet placed in the reachable band.
  kiosk?: boolean;
  // Persisted kiosk avatar framing (head / upper / full) + setter, so it can
  // be changed from the UI and shared with the in-call session.
  kioskView?: PreviewView;
  onKioskViewChange?: (v: PreviewView) => void;
}

type PreviewView = 'head' | 'upper' | 'full';
const VIEW_OPTIONS: { id: PreviewView; label: string }[] = [
  { id: 'head', label: 'Head' },
  { id: 'upper', label: 'Upper' },
  { id: 'full', label: 'Full' },
];

export function AvatarEditor({
  setup, onChange, onStart, starting, error,
  user, onLogout, onDeleteAccount, onBackToPicker, kiosk = false,
  kioskView, onKioskViewChange,
}: Props) {
  // Type-the-username + re-enter-password confirmation prevents both
  // accidental account loss AND a stolen-JWT remote wipe.
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const confirmDeleteAccount = async (args?: { password?: string }) => {
    if (!onDeleteAccount) return;
    const password = args?.password ?? '';
    if (!password) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDeleteAccount(password);
      setDeleteOpen(false);
    } catch (err) {
      setDeleteError((err as Error).message || 'Delete failed');
    } finally {
      setDeleting(false);
    }
  };

  const [micId, setMicId] = useState<string>('');
  const [camId, setCamId] = useState<string>('');
  // Loaded TalkingHead instance, lifted from the preview so the "preview all
  // moves" showcase can drive it imperatively.
  const [previewHead, setPreviewHead] = useState<TalkingHeadInstance | null>(null);
  // Kiosk defaults to the head+upper framing (more engaging on a big vertical
  // screen than a small full-body figure).
  const [view, setView] = useState<PreviewView>(kiosk ? 'upper' : 'full');
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

  // Kiosk: the config form is a sheet that slides up over the full-bleed
  // avatar, into the reachable band. Closed by default so the avatar owns
  // the screen until someone taps "Customize".
  const [sheetOpen, setSheetOpen] = useState(false);

  const currentAvatar = AVATARS[setup.avatar] ?? AVATARS.brunette;

  // Showcase state is held here (not inside AvatarShowcase) so kiosk mode can
  // trigger it from the Customize sheet while the live status card renders on
  // the full-bleed avatar after the sheet closes.
  const showcase = useAvatarShowcase(previewHead, {
    restoreView: kiosk && kioskView ? kioskView : view,
    restoreMood: setup.mood,
    lipsyncScale: currentAvatar.lipsyncScale,
  });

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
      }${kiosk ? ' kiosk' : ''}${kiosk && sheetOpen ? ' sheet-open' : ''}`}
    >
      {/* Kiosk dock — floats in the reachable band over the full-bleed
          avatar. Avatar switch + Customize (opens the config sheet) +
          Start. Only rendered in kiosk mode; CSS positions it via
          --reach-offset. */}
      {kiosk && (
        <div className="kiosk-dock" role="toolbar" aria-label="Avatar controls">
          <div className="kiosk-dock-name">
            {/* Show the companion's chosen name (its identity) — fall back to
                the avatar model label only when unnamed. The look is visible
                on screen and cycles with the arrows, so the name slot belongs
                to the companion, not the model. */}
            <span className="kiosk-dock-title">
              {setup.name.trim() && setup.name.trim() !== 'Companion'
                ? setup.name.trim()
                : currentAvatar.label}
            </span>
            <span className="kiosk-dock-sub">{currentAvatar.body === 'F' ? 'Female' : 'Male'}</span>
          </div>
          <button
            type="button"
            className="kiosk-dock-btn"
            onClick={() => setSheetOpen((v) => !v)}
            aria-expanded={sheetOpen}
          >
            {sheetOpen ? 'Close' : 'Customize'}
          </button>
          <button
            type="button"
            className="kiosk-dock-btn primary"
            disabled={!canStart}
            onClick={() => onStart({ micId: micId || null, camId: camId || null })}
          >
            {starting ? 'Starting…' : 'Start'}
          </button>
        </div>
      )}
      {kiosk && sheetOpen && (
        <div className="kiosk-backdrop" onClick={() => setSheetOpen(false)} aria-hidden />
      )}

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
          <TalkingHeadView
            avatar={currentAvatar}
            mood={setup.mood}
            view={kiosk && kioskView ? kioskView : view}
            onHead={setPreviewHead}
          />
          {/* Touch-friendly avatar prev/next — same action as ← → keys, for
              touchscreens where the keyboard isn't always available. */}
          <button
            type="button"
            className="avatar-nav avatar-nav-prev"
            onClick={() => cycleAvatar(-1)}
            aria-label="Previous avatar"
            title="Previous avatar"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="m15 18-6-6 6-6" />
            </svg>
          </button>
          <button
            type="button"
            className="avatar-nav avatar-nav-next"
            onClick={() => cycleAvatar(1)}
            aria-label="Next avatar"
            title="Next avatar"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4"
              strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="m9 18 6-6-6-6" />
            </svg>
          </button>
          <StageMoodStrip
            value={setup.mood}
            onChange={(mood) => onChange({ mood })}
          />
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
          {/* "Preview all moves" — cycles through every mood/gesture/pose so
              the user can see the avatar's full range before picking it.
              Off-kiosk it's a stage control; in kiosk the trigger lives in the
              Customize sheet and only the running card floats over the stage. */}
          {!kiosk && previewHead && <AvatarShowcase {...showcase} />}
          {kiosk && showcase.current && (
            <div className="kiosk-showcase" role="status" aria-live="polite">
              <div className="showcase-now">
                <span className="showcase-kind">{KIND_LABEL[showcase.current.step.kind]}</span>
                <span className="showcase-value">{showcase.current.label}</span>
              </div>
              <div className="showcase-meta">
                <span className="showcase-count">
                  {showcase.current.index} / {showcase.current.total}
                </span>
                <button type="button" className="showcase-stop" onClick={showcase.stop}>
                  Stop
                </button>
              </div>
            </div>
          )}
          {/* Stage device pills only off-kiosk; in kiosk the selectors
              live in the Customize sheet instead (see below). */}
          {!kiosk && (
            <DevicePanel
              cameraOn={setup.camera}
              onCameraChange={(on) => onChange({ camera: on })}
              micId={micId}
              onMicChange={setMicId}
              camId={camId}
              onCamChange={setCamId}
            />
          )}
          <div className="stage-hud">
            <div className="stage-title">{currentAvatar.label}</div>
            <div className="stage-sub">
              {currentAvatar.body === 'F' ? 'female' : 'male'}
              <span className="kbd-hint"> · ‹ › to switch</span>
            </div>
          </div>
        </div>

        {!kiosk && formCollapsed ? (
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
          {kiosk && (
            <div className="kiosk-sheet-head">
              <span className="kiosk-sheet-grip" aria-hidden />
              <button
                type="button"
                className="kiosk-sheet-done"
                onClick={() => setSheetOpen(false)}
              >
                Done
              </button>
            </div>
          )}
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
            <div className="form-header-row">
              <div className="form-header-title">
                {/* Title shifts based on whether this is a brand-new
                    avatar (default name "Companion") or one the user
                    has already personalized. Subtle but it changes the
                    framing from "create" to "edit". */}
                <h2>
                  {setup.name && setup.name !== 'Companion'
                    ? setup.name
                    : 'Your new companion'}
                </h2>
                <p className="form-header-sub">
                  Personalize the look, voice, and personality.
                  <span className="form-header-saved-hint"> · changes save as you type</span>
                </p>
              </div>
              {user && onLogout && (
                <UserMenu
                  username={user.username}
                  onSwitch={onBackToPicker}
                  onLogout={onLogout}
                  onDeleteAccount={onDeleteAccount ? () => setDeleteOpen(true) : undefined}
                />
              )}
            </div>
          </div>

          {kiosk && onKioskViewChange && (
            <div className="form-field span-2 kiosk-framing-field">
              <label>Framing</label>
              <div className="mode-segment" role="radiogroup" aria-label="Avatar framing">
                {VIEW_OPTIONS.map((v) => (
                  <button
                    key={v.id}
                    type="button"
                    role="radio"
                    aria-checked={(kioskView ?? 'upper') === v.id}
                    className={`mode-seg${(kioskView ?? 'upper') === v.id ? ' active' : ''}`}
                    onClick={() => onKioskViewChange(v.id)}
                  >
                    {v.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Kiosk: trigger the full-range preview, then close the sheet so the
              avatar (and the floating status card) own the screen. */}
          {kiosk && previewHead && (
            <div className="form-field span-2">
              <label>Preview moves</label>
              <button
                type="button"
                className="kiosk-preview-btn"
                disabled={showcase.running}
                onClick={() => { showcase.start(); setSheetOpen(false); }}
              >
                ▶ Preview moods, gestures, poses &amp; lip sync
              </button>
            </div>
          )}

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

            {kiosk && (
              <div className="form-field span-2">
                <label>Mic &amp; Camera</label>
                <DevicePanel
                  variant="sheet"
                  cameraOn={setup.camera}
                  onCameraChange={(on) => onChange({ camera: on })}
                  micId={micId}
                  onMicChange={setMicId}
                  camId={camId}
                  onCamChange={setCamId}
                />
              </div>
            )}

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

            {/* Behaviors row — per-avatar opt-in toggles for the things
                the agent does on its own (without an explicit user turn).
                Each one has clear "what it does" tooltip text. */}
            <div className="form-field span-2">
              <label>Behaviors</label>
              <div className="tool-chips">
                <button
                  type="button"
                  className={`tool-chip${setup.proactive ? ' on' : ''}`}
                  title={
                    'When on, the avatar will gently break silence with a soft '
                    + 'check-in or react to your mood on camera. Limited to a '
                    + 'few times per session so it never feels pushy.'
                  }
                  aria-pressed={setup.proactive}
                  onClick={() => onChange({ proactive: !setup.proactive })}
                >
                  <span className="tool-check" aria-hidden />
                  Proactive — speak first when you're quiet
                </button>
                <button
                  type="button"
                  className={`tool-chip${setup.vision_watcher ? ' on' : ''}`}
                  title={
                    'When on, the avatar passively reads your facial '
                    + 'expression on camera and adjusts its own mood. Off = '
                    + 'camera still works for the avatar to see you when you '
                    + "ask, but no passive mood analysis."
                  }
                  aria-pressed={setup.vision_watcher}
                  onClick={() => onChange({ vision_watcher: !setup.vision_watcher })}
                >
                  <span className="tool-check" aria-hidden />
                  Mood awareness — read facial expressions on camera
                </button>
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

      {user && onDeleteAccount && (
        <ConfirmDialog
          open={deleteOpen}
          tone="danger"
          title={`Delete @${user.username}?`}
          description={
            deleteError
              ? `${deleteError}. This permanently erases your account, every companion, and all conversation memory.`
              : 'This permanently erases your account, every companion, and all conversation memory. This action cannot be undone.'
          }
          confirmPhrase={user.username}
          confirmPhraseLabel="Type your username to confirm:"
          passwordLabel="Re-enter your password:"
          confirmLabel="Delete account"
          cancelLabel="Keep account"
          busy={deleting}
          onConfirm={confirmDeleteAccount}
          onCancel={() => {
            if (deleting) return;
            setDeleteError(null);
            setDeleteOpen(false);
          }}
        />
      )}
    </div>
  );
}

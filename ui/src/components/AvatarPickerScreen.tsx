import { useEffect, useState } from 'react';
import {
  type Avatar,
  createAvatar,
  deleteAvatar as apiDeleteAvatar,
  forgetAvatar as apiForgetAvatar,
  listAvatars,
} from '../api';
import { AVATARS, DEFAULT_AVATAR_KEY } from '../data/avatars';
import { UserMenu } from './UserMenu';
import { ConfirmDialog } from './ConfirmDialog';

interface Props {
  token: string;
  onPick: (avatar: Avatar) => void;
  // The whole user object — surfaced so we can show "@username" and a
  // sign-out affordance from the picker too (no need to bounce back
  // to the wizard just to log out).
  username: string;
  onLogout: () => void | Promise<void>;
}

/**
 * Lands here right after login. Shows the user's saved avatars
 * (most-recently-chatted-with first) and a "+ New companion" tile.
 *
 * Picking an avatar goes to the wizard pre-loaded with its profile;
 * "+ New" creates a fresh row server-side and goes to the wizard with
 * default settings so the user can customize before starting.
 */
export function AvatarPickerScreen({ token, onPick, username, onLogout }: Props) {
  const [avatars, setAvatars] = useState<Avatar[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Avatar | null>(null);
  const [deleting, setDeleting] = useState(false);
  // "Forget memory" parallels delete but keeps the card around. Lower
  // friction (no name typing) since the avatar itself survives.
  const [pendingForget, setPendingForget] = useState<Avatar | null>(null);
  const [forgetting, setForgetting] = useState(false);
  // Brief success line shown above the grid after a wipe — auto-clears
  // when the user navigates away from the screen so it doesn't get stale.
  const [forgetMsg, setForgetMsg] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAvatars(token).then(
      (xs) => {
        if (cancelled) return;
        setAvatars(xs);
        setLoading(false);
      },
      (e) => {
        if (cancelled) return;
        setError((e as Error).message);
        setLoading(false);
      },
    );
    return () => { cancelled = true; };
  }, [token]);

  const handleNew = async () => {
    setCreating(true);
    setError(null);
    try {
      // Default name is just "Companion" — the wizard immediately
      // becomes the rename surface. We don't show a separate "name your
      // avatar" prompt to keep clicks low; the wizard already has a
      // Name field.
      const fresh = await createAvatar(token, {
        name: 'Companion',
        avatar_key: DEFAULT_AVATAR_KEY,
      });
      onPick(fresh);
    } catch (e) {
      setError((e as Error).message);
      setCreating(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    setError(null);
    try {
      await apiDeleteAvatar(token, pendingDelete.id);
      setAvatars((xs) => xs?.filter((a) => a.id !== pendingDelete.id) ?? null);
      setPendingDelete(null);
    } catch (e) {
      setError(`Delete failed: ${(e as Error).message}`);
    } finally {
      setDeleting(false);
    }
  };

  const confirmForget = async () => {
    if (!pendingForget) return;
    setForgetting(true);
    setError(null);
    setForgetMsg(null);
    try {
      const r = await apiForgetAvatar(token, pendingForget.id);
      setForgetMsg(
        `Cleared ${pendingForget.name}'s memory — `
        + `${r.transcripts_deleted} message${r.transcripts_deleted === 1 ? '' : 's'} wiped`
        + (r.memory_cleared ? '.' : ' (long-term memory partial — check logs).'),
      );
      setPendingForget(null);
    } catch (e) {
      setError(`Forget failed: ${(e as Error).message}`);
    } finally {
      setForgetting(false);
    }
  };

  if (loading) {
    return <div className="auth-splash">Loading your companions…</div>;
  }

  return (
    <div className="picker-screen">
      <header className="picker-header">
        <div>
          <h1>Pick a companion</h1>
          <p className="muted">Choose who you want to talk to today</p>
        </div>
        {/* Delete-account lives only on the editor (which has the
            password-confirm modal). Picker keeps the menu lighter — sign
            out, switch — to avoid duplicating the destructive flow. */}
        <UserMenu
          username={username}
          onLogout={onLogout}
        />
      </header>

      {error && <div className="login-error" style={{ marginBottom: 12 }}>{error}</div>}
      {forgetMsg && (
        <div className="picker-toast" role="status">{forgetMsg}</div>
      )}

      <div className="picker-grid">
        {(avatars || []).map((a) => {
          const meta = a.avatar_key ? AVATARS[a.avatar_key] : null;
          return (
            <div key={a.id} className="picker-card">
              <button
                type="button"
                className="picker-card-main"
                onClick={() => onPick(a)}
              >
                <div className="picker-avatar-thumb">
                  <span>{a.name[0]?.toUpperCase() || '?'}</span>
                </div>
                <div className="picker-card-meta">
                  <div className="picker-card-name">{a.name}</div>
                  <div className="picker-card-sub">
                    {meta?.label || a.avatar_key || '—'}
                    {' · '}
                    {a.last_used_at
                      ? `last chatted ${formatRel(a.last_used_at)}`
                      : 'never chatted'}
                  </div>
                </div>
              </button>
              <div className="picker-card-actions">
                <button
                  type="button"
                  className="link picker-card-action"
                  onClick={() => setPendingForget(a)}
                  title={`Wipe ${a.name}'s memory — keeps the avatar, persona, and voice`}
                >
                  Forget memory
                </button>
                <button
                  type="button"
                  className="link danger-btn picker-card-action"
                  onClick={() => setPendingDelete(a)}
                  title="Delete avatar + memories"
                >
                  Delete
                </button>
              </div>
            </div>
          );
        })}

        <button
          type="button"
          className="picker-card picker-new"
          onClick={handleNew}
          disabled={creating}
        >
          <div className="picker-new-plus">+</div>
          <div className="picker-card-name">{creating ? 'Creating…' : 'New companion'}</div>
        </button>
      </div>

      <ConfirmDialog
        open={!!pendingDelete}
        tone="danger"
        title={pendingDelete ? `Delete ${pendingDelete.name}?` : ''}
        description="This permanently removes this companion and every memory shared with them. This action cannot be undone."
        confirmPhrase={pendingDelete?.name}
        confirmPhraseLabel="Type the name to confirm:"
        confirmLabel="Delete companion"
        cancelLabel="Keep"
        busy={deleting}
        onConfirm={confirmDelete}
        onCancel={() => !deleting && setPendingDelete(null)}
      />

      <ConfirmDialog
        open={!!pendingForget}
        tone="danger"
        title={pendingForget ? `Forget ${pendingForget.name}'s memory?` : ''}
        description={
          'Wipes every past message and every learned fact for this '
          + 'companion. The avatar itself, persona, voice, and tools '
          + 'are kept — use this to start fresh without losing the '
          + 'character you built.'
        }
        confirmLabel="Forget"
        cancelLabel="Keep memory"
        busy={forgetting}
        onConfirm={confirmForget}
        onCancel={() => !forgetting && setPendingForget(null)}
      />
    </div>
  );
}

function formatRel(iso: string): string {
  // Tiny date-ago helper. Avoids pulling in date-fns just for this.
  const ms = Date.now() - new Date(iso).getTime();
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return 'just now';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day}d ago`;
  return new Date(iso).toLocaleDateString();
}

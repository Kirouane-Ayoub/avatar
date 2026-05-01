import { useEffect, useState } from 'react';
import {
  type Avatar,
  createAvatar,
  deleteAvatar as apiDeleteAvatar,
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
  onDeleteAccount?: () => void | Promise<void>;
}

/**
 * Lands here right after login. Shows the user's saved avatars
 * (most-recently-chatted-with first) and a "+ New companion" tile.
 *
 * Picking an avatar goes to the wizard pre-loaded with its profile;
 * "+ New" creates a fresh row server-side and goes to the wizard with
 * default settings so the user can customize before starting.
 */
export function AvatarPickerScreen({ token, onPick, username, onLogout, onDeleteAccount }: Props) {
  const [avatars, setAvatars] = useState<Avatar[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Avatar | null>(null);
  const [deleting, setDeleting] = useState(false);

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
        <UserMenu
          username={username}
          onLogout={onLogout}
          onDeleteAccount={onDeleteAccount}
        />
      </header>

      {error && <div className="login-error" style={{ marginBottom: 12 }}>{error}</div>}

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
              <button
                type="button"
                className="link danger-btn picker-card-delete"
                onClick={() => setPendingDelete(a)}
                title="Delete avatar + memories"
              >
                Delete
              </button>
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

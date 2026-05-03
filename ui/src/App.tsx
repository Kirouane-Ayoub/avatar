import { useCallback, useEffect, useRef, useState } from 'react';
import type { SessionSetup } from './types';
import { type Avatar, requestToken, updateAvatar } from './api';
import { AVATARS, DEFAULT_AVATAR_KEY } from './data/avatars';
import { TOOL_CATALOG } from './data/tools';
import { useAuth } from './hooks/useAuth';
import { useLocalStorage } from './hooks/useLocalStorage';
import { AvatarEditor } from './components/AvatarEditor';
import { AvatarPickerScreen } from './components/AvatarPickerScreen';
import { LoginScreen } from './components/LoginScreen';
import { SessionView, type ConnectionInfo } from './components/SessionView';

const DEFAULT_PERSONA =
  'A warm, curious friend in their late 20s. Easygoing, honest, a little playful.';

const DEFAULT_SETUP: SessionSetup = {
  avatar: DEFAULT_AVATAR_KEY,
  name: 'Liva',
  persona: DEFAULT_PERSONA,
  mood: 'happy',
  voice: '',
  tools: TOOL_CATALOG.map((t) => t.id),
  camera: false,
  // Quiet companion by default — proactive check-ins are opt-in per
  // avatar via the AvatarEditor toggle.
  proactive: false,
  // ON by default to preserve historical behavior (watcher always ran
  // when VLM was configured). Toggle off in the editor to disable
  // passive mood reading without disabling the camera entirely.
  vision_watcher: true,
};

/**
 * App boot flow:
 *   useAuth.loading → splash (avoids flashing LoginScreen on reload)
 *   no user        → LoginScreen
 *   no avatar      → AvatarPickerScreen
 *   no connection  → AvatarEditor (per-avatar editor; saves via PATCH)
 *   otherwise      → SessionView (in-call)
 */
export default function App() {
  const auth = useAuth();
  // The avatar the user picked from the AvatarPickerScreen. The wizard
  // edits this avatar in place via PATCH on every onChange.
  const [activeAvatar, setActiveAvatar] = useState<Avatar | null>(null);
  const [setup, setSetup] = useLocalStorage<SessionSetup>('voice-agent-setup-v1', DEFAULT_SETUP);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionInfo | null>(null);

  // Seed the wizard's setup from the active avatar whenever the user
  // picks a different one. Tracked via ref so subsequent edits within
  // the same avatar don't get clobbered.
  const seededAvatarId = useRef<string | null>(null);
  useEffect(() => {
    if (!activeAvatar) {
      seededAvatarId.current = null;
      return;
    }
    if (seededAvatarId.current === activeAvatar.id) return;
    seededAvatarId.current = activeAvatar.id;
    setSetup((prev) => ({
      ...prev,
      // Avatar fields beat wizard cache; nulls fall through to defaults.
      name: activeAvatar.name || prev.name,
      persona: activeAvatar.persona || prev.persona,
      voice: activeAvatar.voice ?? prev.voice,
      avatar: activeAvatar.avatar_key || prev.avatar,
      tools: activeAvatar.tools.length ? activeAvatar.tools : prev.tools,
      proactive: activeAvatar.proactive,
      vision_watcher: activeAvatar.vision_watcher,
      // mood is intentionally NOT seeded from the avatar — it has no
      // persisted mood. Use whatever the wizard previously had.
    }));
  }, [activeAvatar, setSetup]);

  // When the user signs out, drop the active avatar so we go back to
  // LoginScreen on next render.
  useEffect(() => {
    if (!auth.user) setActiveAvatar(null);
  }, [auth.user]);

  const patch = useCallback(
    (next: Partial<SessionSetup>) => {
      setSetup((prev) => ({ ...prev, ...next }));
      // Persist non-mood changes to the avatar row in the background.
      // Mood is wizard-preview-only; it never round-trips to the DB.
      if (!activeAvatar || !auth.token) return;
      const dbPatch: Partial<Avatar> = {};
      if ('name' in next) dbPatch.name = next.name;
      if ('persona' in next) dbPatch.persona = next.persona ?? null;
      if ('voice' in next) dbPatch.voice = next.voice || null;
      if ('avatar' in next) dbPatch.avatar_key = next.avatar ?? null;
      if ('tools' in next) dbPatch.tools = next.tools;
      if (Object.keys(dbPatch).length === 0) return;
      // Fire-and-forget — UI doesn't block on the persist round-trip.
      // Errors are non-fatal: the wizard still works locally; the
      // /api/token call on session start re-saves anyway.
      updateAvatar(auth.token, activeAvatar.id, dbPatch).catch(() => {});
    },
    [setSetup, activeAvatar, auth.token],
  );

  const handleStart = useCallback(
    async ({ micId, camId }: { micId: string | null; camId: string | null }) => {
      if (!auth.token || !activeAvatar) {
        setError('not logged in or no avatar selected');
        return;
      }
      setError(null);
      setStarting(true);
      try {
        const { token, url } = await requestToken(setup, auth.token, activeAvatar.id);
        setConnection({ token, url, micId, camId });
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setStarting(false);
      }
    },
    [setup, auth.token, activeAvatar],
  );

  if (auth.loading) {
    return <div className="auth-splash">Checking session…</div>;
  }
  if (!auth.user) {
    return <LoginScreen auth={auth} />;
  }
  if (!activeAvatar) {
    return (
      <AvatarPickerScreen
        token={auth.token!}
        username={auth.user.username}
        onLogout={auth.logout}
        onDeleteAccount={auth.deleteAccount}
        onPick={setActiveAvatar}
      />
    );
  }

  if (!connection) {
    return (
      <AvatarEditor
        setup={setup}
        onChange={patch}
        onStart={handleStart}
        starting={starting}
        error={error}
        user={auth.user}
        onLogout={auth.logout}
        onDeleteAccount={auth.deleteAccount}
        onBackToPicker={() => setActiveAvatar(null)}
      />
    );
  }

  const avatar = AVATARS[setup.avatar] ?? AVATARS[DEFAULT_AVATAR_KEY];

  return (
    <SessionView
      setup={setup}
      avatar={avatar}
      connection={connection}
      onExit={() => setConnection(null)}
    />
  );
}

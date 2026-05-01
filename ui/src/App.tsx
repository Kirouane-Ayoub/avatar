import { useCallback, useState } from 'react';
import type { SessionSetup } from './types';
import { AVATARS, DEFAULT_AVATAR_KEY } from './data/avatars';
import { TOOL_CATALOG } from './data/tools';
import { useLocalStorage } from './hooks/useLocalStorage';
import { SetupWizard } from './components/SetupWizard';
import { SessionView, type ConnectionInfo } from './components/SessionView';
import { requestToken } from './api';

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
};

export default function App() {
  const [setup, setSetup] = useLocalStorage<SessionSetup>('voice-agent-setup-v1', DEFAULT_SETUP);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [connection, setConnection] = useState<ConnectionInfo | null>(null);

  const patch = useCallback(
    (next: Partial<SessionSetup>) => {
      setSetup((prev) => ({ ...prev, ...next }));
    },
    [setSetup],
  );

  const handleStart = useCallback(
    async ({ micId, camId }: { micId: string | null; camId: string | null }) => {
      setError(null);
      setStarting(true);
      try {
        const { token, url } = await requestToken(setup);
        setConnection({ token, url, micId, camId });
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setStarting(false);
      }
    },
    [setup],
  );

  if (!connection) {
    return (
      <SetupWizard
        setup={setup}
        onChange={patch}
        onStart={handleStart}
        starting={starting}
        error={error}
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

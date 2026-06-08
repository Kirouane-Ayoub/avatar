import { useEffect, useState } from 'react';
import type { AvatarMeta } from '../types';
import { useTalkingHead } from '../hooks/useTalkingHead';

interface Props {
  avatar: AvatarMeta;
  mood: string;
  view?: 'head' | 'upper' | 'full';
  // Lifts the loaded TalkingHead instance up to the parent so it can drive
  // the avatar imperatively (e.g. the "preview all moves" showcase). Fires
  // with the instance once loaded, and with null on unload/avatar swap.
  onHead?: (head: TalkingHeadInstance | null) => void;
}

export function TalkingHeadView({ avatar, mood, view = 'full', onHead }: Props) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const { progress, error, head } = useTalkingHead(container, avatar, mood, view);

  useEffect(() => {
    onHead?.(head);
  }, [head, onHead]);

  return (
    <div className="th-wrap">
      <div ref={setContainer} className="th-stage" />
      {progress !== null && (
        <span className="th-status">Loading… {progress}%</span>
      )}
      {error && <span className="th-status error">{error}</span>}
    </div>
  );
}

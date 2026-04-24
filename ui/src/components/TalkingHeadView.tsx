import { useState } from 'react';
import type { AvatarMeta } from '../types';
import { useTalkingHead } from '../hooks/useTalkingHead';

interface Props {
  avatar: AvatarMeta;
  mood: string;
}

export function TalkingHeadView({ avatar, mood }: Props) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const { progress, error } = useTalkingHead(container, avatar, mood);

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

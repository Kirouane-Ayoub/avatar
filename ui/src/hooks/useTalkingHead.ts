import { useEffect, useRef, useState } from 'react';
import type { AvatarMeta } from '../types';
import { avatarUrl } from '../data/avatars';

function waitForTalkingHead(): Promise<TalkingHeadConstructor> {
  if (window.TalkingHead) return Promise.resolve(window.TalkingHead);
  return new Promise((resolve) => {
    window.addEventListener(
      'talkinghead-ready',
      () => resolve(window.TalkingHead!),
      { once: true },
    );
  });
}

export function useTalkingHead(
  container: HTMLElement | null,
  avatar: AvatarMeta | null,
  mood: string,
  view: 'head' | 'upper' | 'full' = 'full',
) {
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [head, setHead] = useState<TalkingHeadInstance | null>(null);
  const instanceRef = useRef<TalkingHeadInstance | null>(null);

  const initialMoodRef = useRef(mood);
  const initialViewRef = useRef(view);

  useEffect(() => {
    if (!container || !avatar) return;
    let cancelled = false;
    setProgress(0);
    setError(null);

    (async () => {
      try {
        const TalkingHead = await waitForTalkingHead();
        if (cancelled) return;

        const instance = new TalkingHead(container, {
          ttsEndpoint: null,
          cameraView: 'upper',
          cameraRotateEnable: true,
          lipsyncModules: ['en'],
        });
        instanceRef.current = instance;

        const args: Record<string, unknown> = {
          url: avatarUrl(avatar),
          body: avatar.body,
          avatarMood: initialMoodRef.current,
          lipsyncLang: 'en',
        };
        if (avatar.retarget) args.retarget = avatar.retarget;
        if (avatar.baseline) args.baseline = avatar.baseline;
        if (avatar.modelDynamicBones) args.modelDynamicBones = avatar.modelDynamicBones;

        await instance.showAvatar(args, (ev) => {
          if (!cancelled && ev.lengthComputable) {
            setProgress(Math.round((ev.loaded / ev.total) * 100));
          }
        });

        if (cancelled) return;
        setProgress(null);
        try { instance.setMood(initialMoodRef.current); } catch { /* mood not loaded yet */ }
        try { instance.setView(initialViewRef.current); } catch { /* optional */ }
        setHead(instance);
      } catch (e) {
        if (!cancelled) {
          setError((e as Error).message || 'Failed to load avatar');
          setProgress(null);
        }
      }
    })();

    return () => {
      cancelled = true;
      setHead(null);
      try {
        instanceRef.current?.stop?.();
        instanceRef.current?.dispose?.();
      } catch { /* ignore */ }
      instanceRef.current = null;
      while (container.firstChild) container.removeChild(container.firstChild);
    };
  }, [container, avatar]);

  useEffect(() => {
    if (!head) return;
    try { head.setMood(mood); } catch { /* ignore */ }
  }, [head, mood]);

  useEffect(() => {
    if (!head) return;
    try { head.setView(view); } catch { /* ignore */ }
  }, [head, view]);

  return { progress, error, head };
}

import { useEffect } from 'react';
import type { MutableRefObject } from 'react';
import type { AvatarMeta } from '../types';
import type { LipsyncData } from './useSession';

const CHAR_VISEME: Record<string, string> = {
  a: 'aa', e: 'E', i: 'I', o: 'O', u: 'U',
  b: 'PP', p: 'PP', m: 'PP',
  f: 'FF', v: 'FF',
  t: 'DD', d: 'DD', n: 'nn', l: 'nn',
  s: 'SS', z: 'SS', c: 'SS',
  r: 'RR', k: 'kk', g: 'kk',
  w: 'U', y: 'I', h: 'sil',
};

const ALL_VISEMES = [
  'sil', 'PP', 'FF', 'TH', 'DD', 'kk', 'CH', 'SS', 'nn', 'RR',
  'aa', 'E', 'I', 'O', 'U',
];

function setMorph(head: TalkingHeadInstance, name: string, val: number) {
  if (!head.morphs) return;
  for (const m of head.morphs) {
    const i = m.morphTargetDictionary?.[name];
    if (i !== undefined && m.morphTargetInfluences) {
      m.morphTargetInfluences[i] = val;
    }
  }
}

export function useLipsyncDriver(
  head: TalkingHeadInstance | null,
  remoteAudio: MediaStream | null,
  avatar: AvatarMeta | null,
  language: string,
  queueRef: MutableRefObject<LipsyncData[]>,
  enabled: boolean,
) {
  useEffect(() => {
    if (!head || !remoteAudio || !avatar || !enabled) return;

    const ctx = new AudioContext();
    const source = ctx.createMediaStreamSource(remoteAudio);
    const analyser = ctx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.3;
    source.connect(analyser);

    const freqData = new Uint8Array(analyser.frequencyBinCount);
    const scale = avatar.lipsyncScale ?? 1;
    // English visemes: char→viseme map. Non-English: jaw-only (the English
    // phoneme map doesn't apply to other languages' mouth shapes).
    const isEnglish = language === 'en';

    let cancelled = false;
    let currentData: LipsyncData | null = null;
    let playStart = 0;
    let wordIdx = 0;
    let charIdx = 0;

    function tick() {
      if (cancelled) return;
      requestAnimationFrame(tick);
      if (!head) return;

      analyser.getByteFrequencyData(freqData);
      let sum = 0;
      for (let i = 2; i < 30; i++) sum += freqData[i];
      const level = sum / 28 / 255;
      const speaking = level > 0.015;

      if (speaking) {
        if (!currentData && queueRef.current.length > 0) {
          currentData = queueRef.current.shift()!;
          playStart = performance.now();
          wordIdx = 0;
          charIdx = 0;
        }

        if (currentData) {
          const elapsed = performance.now() - playStart;
          const { words, wtimes, wdurations } = currentData;
          while (
            wordIdx < words.length &&
            elapsed > wtimes[wordIdx] + wdurations[wordIdx]
          ) {
            wordIdx++;
            charIdx = 0;
          }

          if (wordIdx < words.length) {
            if (!isEnglish) {
              ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
              setMorph(head, 'jawOpen', Math.min(level * 2.5 * scale, 0.4 * scale));
            } else {
              const word = words[wordIdx].toLowerCase().replace(/[^a-z]/g, '');
              const wStart = wtimes[wordIdx];
              const wDur = wdurations[wordIdx];
              if (word.length > 0) {
                const charDur = wDur / word.length;
                const wordElapsed = elapsed - wStart;
                const target = Math.min(
                  Math.floor(wordElapsed / charDur),
                  word.length - 1,
                );
                if (target >= 0 && target !== charIdx) charIdx = target;
                const ch = word[Math.max(0, charIdx)] || '';
                const vis = CHAR_VISEME[ch] || 'sil';
                ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
                setMorph(head, 'viseme_' + vis, 0.35 * scale);
                setMorph(head, 'jawOpen', Math.min(level * 2 * scale, 0.3 * scale));
              }
            }
          } else {
            currentData = null;
          }
        } else {
          setMorph(head, 'jawOpen', Math.min(level * 1.5 * scale, 0.25 * scale));
        }
      } else {
        setMorph(head, 'jawOpen', 0);
        ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
        if (currentData) {
          const elapsed = performance.now() - playStart;
          const { wtimes, wdurations } = currentData;
          const lastEnd =
            wtimes[wtimes.length - 1] + wdurations[wdurations.length - 1];
          if (elapsed > lastEnd + 300) currentData = null;
        }
      }
    }
    tick();

    return () => {
      cancelled = true;
      try { ctx.close(); } catch { /* ignore */ }
      if (head) {
        setMorph(head, 'jawOpen', 0);
        ALL_VISEMES.forEach((v) => setMorph(head, 'viseme_' + v, 0));
      }
      queueRef.current = [];
    };
  }, [head, remoteAudio, avatar, language, queueRef, enabled]);
}

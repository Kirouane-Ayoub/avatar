import { useEffect, useMemo, useRef, useState } from 'react';
import type { VoiceBackend, VoiceInfo } from '../types';
import { fetchVoices, fetchVoiceSample } from '../api';
import { sampleTextFor } from '../data/voice_samples';

type BackendFilter = 'all' | VoiceBackend;

interface Props {
  value: string;
  onChange: (voiceId: string) => void;
  name: string;
}

const GRADE_ORDER = [
  'A', 'A-', 'B+', 'B', 'B-',
  'C+', 'C', 'C-',
  'D+', 'D', 'D-',
  'F+', 'F',
];

function gradeRank(grade: string): number {
  if (!grade) return 999;
  const idx = GRADE_ORDER.indexOf(grade);
  return idx === -1 ? 900 : idx;
}

// Collapse Kokoro's 13-tier grade scheme (A..F) into a 4-pip signal-strength
// indicator so users can eyeball quality without memorising the rubric.
function gradeTier(grade: string): 0 | 1 | 2 | 3 | 4 {
  if (!grade) return 1;
  const first = grade[0];
  const hasMinus = grade.includes('-');
  const hasPlus = grade.includes('+');
  if (first === 'A') return hasMinus ? 3 : 4;
  if (first === 'B') return hasPlus || !hasMinus ? 3 : 2;
  if (first === 'C') return hasPlus ? 2 : 1;
  if (first === 'D') return 1;
  return 0;
}

// Human-readable tier description for tooltips. The pips alone look
// decorative without context — hovering should explain what they mean.
function tierLabel(tier: 0 | 1 | 2 | 3 | 4): string {
  return ['Untested', 'Basic quality', 'Decent quality', 'Good quality', 'Best quality'][tier];
}

// Friendly backend names. Users don't know what "Kokoro" / "Orpheus" mean.
// Show plain-English labels in the chips; keep the technical name in
// a tooltip for users who care.
const BACKEND_LABELS: Record<VoiceBackend, { label: string; hint: string }> = {
  kokoro: {
    label: 'Standard',
    hint: 'Kokoro — fast, lightweight, 8+ accents. Best for everyday chat.',
  },
  orpheus: {
    label: 'Expressive',
    hint: 'Orpheus — slower but richer, more emotion. Best for deeper conversations.',
  },
};

function parseVoice(v: VoiceInfo) {
  const rest = v.id.includes('_') ? v.id.slice(v.id.indexOf('_') + 1) : v.id;
  const firstName = rest.replace(/_/g, ' ');
  const displayName = firstName.charAt(0).toUpperCase() + firstName.slice(1);
  return { ...v, displayName };
}

function PlayGlyph({ state }: { state: 'idle' | 'loading' | 'playing' }) {
  if (state === 'loading') return <span className="play-glyph spin" />;
  if (state === 'playing') {
    return (
      <span className="eq" aria-hidden>
        <span /><span /><span />
      </span>
    );
  }
  return (
    <svg viewBox="0 0 12 12" width="10" height="10" aria-hidden>
      <path d="M3 2 L10 6 L3 10 Z" fill="currentColor" />
    </svg>
  );
}

function GradePips({ tier }: { tier: 0 | 1 | 2 | 3 | 4 }) {
  const label = tierLabel(tier);
  return (
    <span
      className={`grade-pips tier-${tier}`}
      title={`${label} (${tier}/4)`}
      aria-label={`${label} — quality tier ${tier} of 4`}
    >
      {[0, 1, 2, 3].map((i) => (
        <span key={i} className={i < tier ? 'on' : 'off'} />
      ))}
    </span>
  );
}

export function VoicePicker({ value, onChange, name }: Props) {
  const [voices, setVoices] = useState<VoiceInfo[]>([]);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [langFilter, setLangFilter] = useState<string>('all');
  const [backendFilter, setBackendFilter] = useState<BackendFilter>('all');
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const objectUrlRef = useRef<string | null>(null);

  const cleanup = () => {
    abortRef.current?.abort();
    abortRef.current = null;
    audioRef.current?.pause();
    audioRef.current = null;
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  };

  useEffect(() => {
    fetchVoices().then(setVoices).catch((err) => console.warn('voices:', err));
  }, []);

  useEffect(() => cleanup, []);

  // Backend chips show only when the catalog actually contains both — no point
  // rendering a "Kokoro / Orpheus" toggle when only one is available.
  const backendCounts = useMemo(() => {
    const counts: Record<VoiceBackend, number> = { kokoro: 0, orpheus: 0 };
    for (const v of voices) {
      const b = v.backend ?? 'kokoro';
      counts[b] += 1;
    }
    return counts;
  }, [voices]);
  const showBackendChips = backendCounts.kokoro > 0 && backendCounts.orpheus > 0;

  // Language counts are scoped to the active backend filter so the chip
  // counts reflect what the user will actually see in the list below.
  const languages = useMemo(() => {
    const counts = new Map<string, number>();
    for (const v of voices) {
      if (backendFilter !== 'all' && (v.backend ?? 'kokoro') !== backendFilter) continue;
      counts.set(v.language, (counts.get(v.language) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([lang, count]) => ({ lang, count }))
      .sort((a, b) => a.lang.localeCompare(b.lang));
  }, [voices, backendFilter]);

  // Reset the language chip if it's no longer offered under the active
  // backend filter, otherwise the list would silently go empty.
  useEffect(() => {
    if (langFilter === 'all') return;
    if (!languages.some((l) => l.lang === langFilter)) {
      setLangFilter('all');
    }
  }, [languages, langFilter]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = voices
      .map(parseVoice)
      .filter((v) => backendFilter === 'all' || (v.backend ?? 'kokoro') === backendFilter)
      .filter((v) => langFilter === 'all' || v.language === langFilter)
      .filter((v) => {
        if (!q) return true;
        return (
          v.id.toLowerCase().includes(q) ||
          v.displayName.toLowerCase().includes(q) ||
          v.language.toLowerCase().includes(q)
        );
      });
    list.sort((a, b) => {
      // Pin the currently-selected voice to the top so the user
      // always sees their pick first, even after filter changes.
      if (a.id === value && b.id !== value) return -1;
      if (b.id === value && a.id !== value) return 1;
      if (a.language !== b.language) return a.language.localeCompare(b.language);
      return gradeRank(a.grade) - gradeRank(b.grade);
    });
    return list;
  }, [voices, query, langFilter, backendFilter, value]);

  // Resolve the currently-selected voice for the header banner. Empty
  // value means "auto" — agent picks one based on avatar gender + language.
  const selectedVoice = useMemo(() => {
    if (!value) return null;
    return voices.map(parseVoice).find((v) => v.id === value) ?? null;
  }, [voices, value]);

  const play = async (voice: ReturnType<typeof parseVoice>) => {
    const toggleOff = playingId === voice.id || loadingId === voice.id;
    cleanup();
    setPlayingId(null);
    if (toggleOff) {
      setLoadingId(null);
      return;
    }

    setLoadingId(voice.id);
    const text = sampleTextFor(voice.language, name);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const blob = await fetchVoiceSample(voice.id, text, controller.signal);
      if (controller.signal.aborted) return;

      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;
      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        setPlayingId(null);
        cleanup();
      };
      audio.onerror = () => {
        setPlayingId(null);
        setLoadingId(null);
      };

      await audio.play();
      setPlayingId(voice.id);
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        console.warn('voice sample failed:', err);
      }
    } finally {
      setLoadingId((id) => (id === voice.id ? null : id));
    }
  };

  return (
    <div className="voice-picker">
      {/* "Currently using" banner — answers the user's #1 question
          ("which voice did I pick?") without scrolling, and surfaces
          the auto-pick fallback when nothing's selected so users know
          they don't *have* to pick. */}
      <div className="voice-current">
        {selectedVoice ? (
          <>
            <span className="voice-current-label">Currently using</span>
            <strong className="voice-current-name">{selectedVoice.displayName}</strong>
            <span className="voice-current-meta">
              {selectedVoice.language} · {selectedVoice.gender === 'F' ? 'female' : 'male'}
            </span>
            <button
              type="button"
              className="voice-current-reset"
              onClick={() => onChange('')}
              title="Let the system pick a voice based on the avatar"
            >
              reset to auto
            </button>
          </>
        ) : (
          <>
            <span className="voice-current-label">No voice picked</span>
            <span className="voice-current-auto">
              we'll auto-pick one based on your avatar — or browse below
            </span>
          </>
        )}
      </div>

      <div className="voice-picker-head">
        <input
          type="text"
          placeholder="Search by name or accent"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {showBackendChips && (
          <div className="voice-lang-chips voice-backend-chips">
            <button
              type="button"
              className={`lang-chip${backendFilter === 'all' ? ' active' : ''}`}
              onClick={() => setBackendFilter('all')}
              title="Show every voice across both engines"
            >
              All voices <span className="lang-count">{voices.length}</span>
            </button>
            <button
              type="button"
              className={`lang-chip${backendFilter === 'kokoro' ? ' active' : ''}`}
              onClick={() => setBackendFilter('kokoro')}
              title={BACKEND_LABELS.kokoro.hint}
            >
              {BACKEND_LABELS.kokoro.label} <span className="lang-count">{backendCounts.kokoro}</span>
            </button>
            <button
              type="button"
              className={`lang-chip${backendFilter === 'orpheus' ? ' active' : ''}`}
              onClick={() => setBackendFilter('orpheus')}
              title={BACKEND_LABELS.orpheus.hint}
            >
              {BACKEND_LABELS.orpheus.label} <span className="lang-count">{backendCounts.orpheus}</span>
            </button>
          </div>
        )}
        {languages.length > 1 && (
          <div className="voice-lang-chips">
            <button
              type="button"
              className={`lang-chip${langFilter === 'all' ? ' active' : ''}`}
              onClick={() => setLangFilter('all')}
            >
              All <span className="lang-count">
                {languages.reduce((s, l) => s + l.count, 0)}
              </span>
            </button>
            {languages.map(({ lang, count }) => (
              <button
                key={lang}
                type="button"
                className={`lang-chip${langFilter === lang ? ' active' : ''}`}
                onClick={() => setLangFilter(lang)}
              >
                {lang.replace(' English', '')}
                <span className="lang-count">{count}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="voice-list">
        {filtered.length === 0 && (
          <div className="voice-empty">
            {query ? `No voices match “${query}”` : 'No voices available'}
          </div>
        )}
        {filtered.map((v) => {
          const isSelected = v.id === value;
          const isPlaying = v.id === playingId;
          const isLoading = v.id === loadingId;
          const state: 'idle' | 'loading' | 'playing' = isLoading
            ? 'loading'
            : isPlaying
              ? 'playing'
              : 'idle';
          return (
            <div
              key={v.id}
              className={`voice-card${isSelected ? ' selected' : ''}${isPlaying ? ' live' : ''}`}
              onClick={() => onChange(v.id)}
            >
              <span className="voice-shimmer" aria-hidden />
              <div className={`voice-avatar body-${v.gender}`}>
                {v.displayName.charAt(0).toUpperCase()}
              </div>
              <div className="voice-meta">
                <div className="voice-top">
                  <span className="voice-display">{v.displayName}</span>
                  {isSelected && <span className="voice-check" aria-label="selected" />}
                </div>
                <div className="voice-bottom">
                  <span className="voice-lang">{v.language}</span>
                  <span className="voice-dot" />
                  <span className="voice-sex">{v.gender === 'F' ? 'female' : 'male'}</span>
                  <span className="voice-spacer" />
                  <GradePips tier={gradeTier(v.grade)} />
                </div>
              </div>
              <button
                type="button"
                className={`voice-play-lg${isPlaying ? ' playing' : ''}${isLoading ? ' loading' : ''}`}
                onClick={(e) => {
                  e.stopPropagation();
                  play(v);
                }}
                aria-label={isPlaying ? 'Stop sample' : 'Play sample'}
              >
                <PlayGlyph state={state} />
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

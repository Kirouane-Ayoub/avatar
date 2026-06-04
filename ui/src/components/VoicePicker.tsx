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
  supertonic: {
    label: 'Studio',
    hint: 'Supertonic — 44.1kHz studio-quality, multilingual styles. Crisp and high-fidelity.',
  },
};

// Flag / script badge per language label, so languages are scannable at a
// glance in the rail and the cards. Falls back to a globe for anything
// unmapped. Keys are the verbatim `language` values from /api/voices.
const LANG_BADGE: Record<string, string> = {
  'American English': '🇺🇸',
  'British English': '🇬🇧',
  English: '🇬🇧',
  Greek: '🇬🇷',
  Japanese: '🇯🇵',
  'Mandarin Chinese': '🇨🇳',
  Spanish: '🇪🇸',
  French: '🇫🇷',
  German: '🇩🇪',
  Italian: '🇮🇹',
  Hindi: '🇮🇳',
  Korean: '🇰🇷',
  'Brazilian Portuguese': '🇧🇷',
};
function langBadge(language: string): string {
  return LANG_BADGE[language] ?? '🌐';
}

// Compact rail labels — drop redundant qualifiers so the narrow left
// column reads cleanly (full label still shown via title attr).
function shortLang(language: string): string {
  switch (language) {
    case 'American English': return 'American';
    case 'British English': return 'British';
    case 'Mandarin Chinese': return 'Mandarin';
    case 'Brazilian Portuguese': return 'Portuguese';
    default: return language;
  }
}

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

// Live waveform shown on a card while its sample is playing — clearer
// "this one is speaking" feedback than the small spinner alone.
function Waveform() {
  return (
    <span className="voice-wave" aria-label="playing">
      {Array.from({ length: 7 }).map((_, i) => (
        <span key={i} style={{ animationDelay: `${i * 0.09}s` }} />
      ))}
    </span>
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

  // Language rail — one row per distinct language across ALL engines, so the
  // rail is stable regardless of the engine sub-filter. Sorted by population
  // (busiest language first) then name, with the avatar's currently-selected
  // language guaranteed visible.
  const languages = useMemo(() => {
    const counts = new Map<string, number>();
    for (const v of voices) counts.set(v.language, (counts.get(v.language) ?? 0) + 1);
    return [...counts.entries()]
      .map(([lang, count]) => ({ lang, count }))
      .sort((a, b) => (b.count - a.count) || a.lang.localeCompare(b.lang));
  }, [voices]);

  // Voices in the selected language (or all) — drives the engine chip counts
  // and their visibility (only worth showing when a language spans engines).
  const langScopedVoices = useMemo(
    () => (langFilter === 'all' ? voices : voices.filter((v) => v.language === langFilter)),
    [voices, langFilter],
  );
  const backendCounts = useMemo(() => {
    const counts: Record<VoiceBackend, number> = { kokoro: 0, orpheus: 0, supertonic: 0 };
    for (const v of langScopedVoices) counts[v.backend ?? 'kokoro'] += 1;
    return counts;
  }, [langScopedVoices]);
  const activeBackends = useMemo(
    () => (Object.keys(backendCounts) as VoiceBackend[]).filter((b) => backendCounts[b] > 0),
    [backendCounts],
  );
  const showBackendChips = activeBackends.length > 1;

  // Switching language clears any engine sub-filter that may not exist under
  // the new language (otherwise the list silently goes empty).
  useEffect(() => {
    setBackendFilter('all');
  }, [langFilter]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    // When the user is actively searching, ignore the language rail and look
    // across every language — finding a voice by name shouldn't require first
    // landing on its language.
    let list = (q ? voices : langScopedVoices).map(parseVoice);
    list = list.filter((v) => backendFilter === 'all' || (v.backend ?? 'kokoro') === backendFilter);
    if (q) {
      list = list.filter(
        (v) =>
          v.id.toLowerCase().includes(q) ||
          v.displayName.toLowerCase().includes(q) ||
          v.language.toLowerCase().includes(q),
      );
    }
    list.sort((a, b) => {
      // Pin the currently-selected voice to the top so the user always sees
      // their pick first, even after filter changes.
      if (a.id === value && b.id !== value) return -1;
      if (b.id === value && a.id !== value) return 1;
      if (a.language !== b.language) return a.language.localeCompare(b.language);
      return gradeRank(a.grade) - gradeRank(b.grade);
    });
    return list;
  }, [voices, langScopedVoices, query, backendFilter, value]);

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
    <div className="voice-picker voice-picker-split">
      {/* "Currently using" banner — answers the user's #1 question
          ("which voice did I pick?") without scrolling, and surfaces
          the auto-pick fallback when nothing's selected so users know
          they don't *have* to pick. */}
      <div className="voice-current">
        {selectedVoice ? (
          <>
            <span className="voice-current-flag" aria-hidden>{langBadge(selectedVoice.language)}</span>
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
      </div>

      <div className="voice-split">
        {/* LEFT: language rail */}
        <div className="voice-langrail" role="tablist" aria-label="Language">
          <button
            type="button"
            role="tab"
            aria-selected={langFilter === 'all'}
            className={`lang-row${langFilter === 'all' ? ' active' : ''}`}
            onClick={() => setLangFilter('all')}
            title="Show every language"
          >
            <span className="lang-row-badge" aria-hidden>🌐</span>
            <span className="lang-row-name">All</span>
            <span className="lang-row-count">{voices.length}</span>
          </button>
          {languages.map(({ lang, count }) => (
            <button
              key={lang}
              type="button"
              role="tab"
              aria-selected={langFilter === lang}
              className={`lang-row${langFilter === lang ? ' active' : ''}`}
              onClick={() => setLangFilter(lang)}
              title={lang}
            >
              <span className="lang-row-badge" aria-hidden>{langBadge(lang)}</span>
              <span className="lang-row-name">{shortLang(lang)}</span>
              <span className="lang-row-count">{count}</span>
            </button>
          ))}
        </div>

        {/* RIGHT: voices for the selected language */}
        <div className="voice-rightpane">
          {showBackendChips && (
            <div className="voice-engine-row">
              <button
                type="button"
                className={`lang-chip${backendFilter === 'all' ? ' active' : ''}`}
                onClick={() => setBackendFilter('all')}
                title="Show every voice across all engines"
              >
                All engines <span className="lang-count">{langScopedVoices.length}</span>
              </button>
              {activeBackends.map((b) => (
                <button
                  key={b}
                  type="button"
                  className={`lang-chip${backendFilter === b ? ' active' : ''}`}
                  onClick={() => setBackendFilter(b)}
                  title={BACKEND_LABELS[b].hint}
                >
                  {BACKEND_LABELS[b].label} <span className="lang-count">{backendCounts[b]}</span>
                </button>
              ))}
            </div>
          )}

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
                      <span className="voice-flag" aria-hidden>{langBadge(v.language)}</span>
                      <span className="voice-lang">{v.language}</span>
                      <span className="voice-dot" />
                      <span className="voice-sex">{v.gender === 'F' ? 'female' : 'male'}</span>
                      <span className="voice-spacer" />
                      {isPlaying ? <Waveform /> : <GradePips tier={gradeTier(v.grade)} />}
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
      </div>
    </div>
  );
}

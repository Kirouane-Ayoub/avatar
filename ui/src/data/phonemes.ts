// Wraps TalkingHead's per-language Lipsync* modules so the lipsync driver
// can phonemize words client-side and step through phoneme-shaped visemes
// instead of guessing per-character. Modules are loaded via the import map
// in index.html alongside TalkingHead itself.

interface PhonemizerInstance {
  wordsToVisemes(word: string): {
    words: string;
    visemes: string[];
    times: number[];
    durations: number[];
    i?: number;
  };
}

// Language code → factory that constructs the phonemizer if the module
// loaded successfully via the importmap. Add a new language here + an
// importmap entry in index.html and you're done.
const FACTORIES: Record<string, () => PhonemizerInstance | null> = {
  en: () => (window.LipsyncEn ? new window.LipsyncEn() : null),
  fr: () => (window.LipsyncFr ? new window.LipsyncFr() : null),
};

const instanceCache = new Map<string, PhonemizerInstance | null>();
const wordCache = new Map<string, Map<string, NormalizedVisemes | null>>();

export interface NormalizedVisemes {
  visemes: string[];
  // Normalized to 0..1 — fractions of the word's total duration. The driver
  // multiplies by the actual word duration from Kokoro to get absolute times.
  starts: number[];
  ends: number[];
}

function getInstance(lang: string): PhonemizerInstance | null {
  if (instanceCache.has(lang)) return instanceCache.get(lang) ?? null;
  const factory = FACTORIES[lang];
  const inst = factory ? factory() : null;
  instanceCache.set(lang, inst);
  return inst;
}

export function phonemizeWord(word: string, lang: string): NormalizedVisemes | null {
  const cleaned = word.trim();
  if (!cleaned) return null;

  let cache = wordCache.get(lang);
  if (!cache) {
    cache = new Map();
    wordCache.set(lang, cache);
  }
  if (cache.has(cleaned)) return cache.get(cleaned) ?? null;

  const inst = getInstance(lang);
  if (!inst) {
    cache.set(cleaned, null);
    return null;
  }

  let result: NormalizedVisemes | null = null;
  try {
    const out = inst.wordsToVisemes(cleaned);
    if (out && out.visemes.length > 0) {
      const last =
        out.times[out.times.length - 1] +
        out.durations[out.durations.length - 1];
      const total = last > 0 ? last : 1;
      result = {
        visemes: out.visemes.slice(),
        starts: out.times.map((t) => t / total),
        ends: out.times.map((t, i) => (t + out.durations[i]) / total),
      };
    }
  } catch {
    // Lipsync* modules occasionally trip on punctuation-only or empty inputs.
    result = null;
  }
  cache.set(cleaned, result);
  return result;
}

export function hasPhonemizer(lang: string): boolean {
  return lang in FACTORIES;
}

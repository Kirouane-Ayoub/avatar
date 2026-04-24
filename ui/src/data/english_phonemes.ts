// Wraps TalkingHead's LipsyncEn module so the lipsync driver can phonemize
// English words client-side and step through real phoneme-shaped visemes
// instead of guessing per-character. The module is loaded via the import
// map in index.html alongside TalkingHead itself.

let cached: LipsyncEnInstance | null = null;
const wordCache = new Map<string, EnglishVisemes | null>();

export interface EnglishVisemes {
  visemes: string[];
  // Normalized to 0..1 — fractions of the word's duration. The driver
  // multiplies by the actual word duration from Kokoro to get absolute times.
  starts: number[];
  ends: number[];
}

function getInstance(): LipsyncEnInstance | null {
  if (cached) return cached;
  if (window.LipsyncEn) {
    cached = new window.LipsyncEn();
    return cached;
  }
  return null;
}

export function phonemizeEnglishWord(word: string): EnglishVisemes | null {
  const cleaned = word.trim();
  if (!cleaned) return null;
  if (wordCache.has(cleaned)) return wordCache.get(cleaned) ?? null;

  const inst = getInstance();
  if (!inst) {
    wordCache.set(cleaned, null);
    return null;
  }

  let result: EnglishVisemes | null = null;
  try {
    const out = inst.wordsToVisemes(cleaned);
    if (out && out.visemes.length > 0) {
      const last = out.times[out.times.length - 1] + out.durations[out.durations.length - 1];
      const total = last > 0 ? last : 1;
      result = {
        visemes: out.visemes.slice(),
        starts: out.times.map((t) => t / total),
        ends: out.times.map((t, i) => (t + out.durations[i]) / total),
      };
    }
  } catch {
    // LipsyncEn occasionally trips on punctuation-only or empty inputs.
    result = null;
  }
  wordCache.set(cleaned, result);
  return result;
}

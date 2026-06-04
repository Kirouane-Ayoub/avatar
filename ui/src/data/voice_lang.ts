// Mirrors src/voices.py:stt_language_for — Kokoro voice ids encode their
// language in the first letter; Orpheus voice ids are plain names with no
// such convention, so we look them up explicitly.
const LANG_BY_PREFIX: Record<string, string> = {
  // Kokoro: a/b → en (American/British), e → es, f → fr, h → hi, i → it,
  // j → ja, p → pt (Brazilian Portuguese), z → zh (Mandarin)
  a: 'en', b: 'en',
  e: 'es', f: 'fr', h: 'hi', i: 'it',
  j: 'ja', p: 'pt', z: 'zh',
};

// Orpheus voice id → language code. Keep in sync with
// src/voices.py:ORPHEUS_VOICES (the `stt` field).
const ORPHEUS_VOICE_LANG: Record<string, string> = {
  // English
  tara: 'en', leah: 'en', jess: 'en', mia: 'en', zoe: 'en',
  leo: 'en', dan: 'en', zac: 'en',
  // French
  pierre: 'fr', amelie: 'fr', marie: 'fr',
  // German
  jana: 'de', thomas: 'de', max: 'de',
  // Spanish
  javi: 'es', sergio: 'es', maria: 'es',
  // Italian
  pietro: 'it', giulia: 'it', carlo: 'it',
  // Korean
  유나: 'ko', 준서: 'ko',
  // Hindi
  ऋतिका: 'hi',
  // Mandarin Chinese
  长乐: 'zh', 白芷: 'zh',
};

// Supertonic ids encode (language × style). English keeps bare style ids
// (F1-F5 / M1-M5); other languages are prefixed (el_* for Greek). The style
// itself carries no language signal, so look these up explicitly before the
// prefix heuristic (which would misread "f"/"m"/"el_" as French/Spanish).
// Keep in sync with src/tts/voices.py:SUPERTONIC_VOICES (the `stt` field).
const SUPERTONIC_VOICE_LANG: Record<string, string> = {
  F1: 'en', F2: 'en', F3: 'en', F4: 'en', F5: 'en',
  M1: 'en', M2: 'en', M3: 'en', M4: 'en', M5: 'en',
  el_F1: 'el', el_F2: 'el', el_F3: 'el', el_F4: 'el', el_F5: 'el',
  el_M1: 'el', el_M2: 'el', el_M3: 'el', el_M4: 'el', el_M5: 'el',
};

export function languageFromVoice(
  voiceId: string | undefined | null,
  fallback = 'en',
): string {
  if (!voiceId) return fallback;
  const orpheus = ORPHEUS_VOICE_LANG[voiceId];
  if (orpheus) return orpheus;
  const supertonic = SUPERTONIC_VOICE_LANG[voiceId];
  if (supertonic) return supertonic;
  const prefix = voiceId[0]?.toLowerCase();
  return prefix ? (LANG_BY_PREFIX[prefix] ?? fallback) : fallback;
}

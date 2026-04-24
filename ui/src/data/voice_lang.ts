// Mirrors src/voices.py:stt_language_for — given a Kokoro voice id, return
// the BCP-47-ish language code based on the voice's prefix letter:
//   a/b → en (American/British English)
//   e   → es (Spanish)
//   f   → fr (French)
//   h   → hi (Hindi)
//   i   → it (Italian)
//   j   → ja (Japanese)
//   p   → pt (Brazilian Portuguese)
//   z   → zh (Mandarin Chinese)
const LANG_BY_PREFIX: Record<string, string> = {
  a: 'en', b: 'en',
  e: 'es', f: 'fr', h: 'hi', i: 'it',
  j: 'ja', p: 'pt', z: 'zh',
};

export function languageFromVoice(
  voiceId: string | undefined | null,
  fallback = 'en',
): string {
  if (!voiceId) return fallback;
  const prefix = voiceId[0]?.toLowerCase();
  return prefix ? (LANG_BY_PREFIX[prefix] ?? fallback) : fallback;
}

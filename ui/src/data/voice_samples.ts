// Short greeting phrases used for the "play sample" button on each voice.
// The language label comes from the Kokoro VOICES.md catalog verbatim.
//
// Strategy: match the voice's language. Personalize English with the user's
// name when provided; for other languages, use a generic greeting to avoid
// mispronouncing a name with the wrong phoneme rules.

const FALLBACK = 'Hi there. This is how I sound.';

const SAMPLES: Record<string, string> = {
  'American English': 'Hi there. This is how I sound — nice to meet you.',
  'British English': 'Hello there. This is how I sound — lovely to meet you.',
  English: 'Hi there. This is how I sound — nice to meet you.',
  Greek: 'Γειά σου, αυτή είναι η φωνή μου. Χαίρομαι που σε γνωρίζω.',
  Japanese: 'こんにちは。これが私の声です。よろしくね。',
  'Mandarin Chinese': '你好，这是我的声音，很高兴认识你。',
  Spanish: 'Hola, así suena mi voz. Encantada de conocerte.',
  French: 'Salut, voici ma voix. Ravi de te rencontrer.',
  Hindi: 'नमस्ते, यह मेरी आवाज़ है। मिलकर खुशी हुई।',
  Italian: 'Ciao, questa è la mia voce. Piacere di conoscerti.',
  'Brazilian Portuguese': 'Oi, esta é a minha voz. Prazer em te conhecer.',
};

export function sampleTextFor(language: string, name?: string): string {
  const cleanName = (name ?? '').trim();
  if ((language === 'American English' || language === 'British English') && cleanName) {
    return `Hi, I'm ${cleanName}. Nice to meet you.`;
  }
  return SAMPLES[language] ?? FALLBACK;
}

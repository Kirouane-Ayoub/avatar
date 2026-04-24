const MOOD_KEYWORDS: Record<string, RegExp> = {
  love:  /\b(love|loved|adore|heart|sweet|cute|beautiful|gorgeous|amazing|wonderful|precious|darling|amour|aime|habibi)\b|❤|🥰|😍|💕/i,
  sad:   /\b(sorry|sad|sadly|unfortunately|bad news|miss you|lonely|cry|crying|hurt|hurts|tough|sucks|ugh|triste|désolé|حزين|آسف)\b|😢|😭|💔|😞/i,
  angry: /\b(angry|mad|annoyed|frustrated|hate|terrible|awful|ridiculous|pissed|énervé|fâché|غاضب)\b|😡|🤬|😤/i,
  fear:  /\b(afraid|scared|scary|worried|nervous|anxious|panic|yikes|peur|خائف)\b|😨|😱|😰/i,
  sleep: /\b(bye|goodbye|goodnight|night night|sleep|sleepy|tired|exhausted|bonne nuit|تصبح على خير)\b|😴|💤|🥱/i,
  happy: /\b(great|awesome|happy|glad|nice|good|cool|sweet|haha|lol|yay|hi|hey|hello|welcome|thanks|thank|love it|génial|super|merci|bien|سعيد|ممتاز|مرحبا)\b|😀|😄|😊|🙂|😁|😎|🎉/i,
};

const GESTURE_KEYWORDS: Record<string, RegExp> = {
  shrug:    /\b(don't know|dunno|not sure|no idea|whatever|maybe|i guess|qui sait|ما أدري)\b/i,
  thumbup:  /\b(yes|yep|yeah|yup|correct|right|exactly|perfect|nailed it|sounds good|sure|absolutely|true|makes sense|i agree|for sure|of course|definitely|oui|نعم|تمام)\b|👍/i,
  thumbdown:/\b(nope|no way|never|terrible|awful|bad idea|don't like|absolutely not|impossible)\b|👎/i,
  handup:   /\b(hi|hello|hey|hiya|wave|waving|bye|goodbye|see ya|salut|bonjour|مرحبا|مع السلامة)\b|👋/i,
  ok:       /\b(ok|okay|fine|alright|all right|got it|d'accord|تمام)\b|👌/i,
  namaste:  /\b(thank|thanks|grateful|appreciate|much obliged|merci|شكرا)\b|🙏/i,
  index:    /\b(look|notice|check this|by the way|fyi|here|important|remember)\b|☝/i,
  side:     /\b(hmm|hmmm|let me think|interesting|wait what|really\?)\b/i,
};

function pickByScore(text: string, table: Record<string, RegExp>): string | null {
  const t = text.toLowerCase();
  let best: string | null = null;
  let bestScore = 0;
  for (const [label, re] of Object.entries(table)) {
    const flags = re.flags.includes('g') ? re.flags : re.flags + 'g';
    const matches = t.match(new RegExp(re.source, flags));
    const score = matches ? matches.length : 0;
    if (score > bestScore) { best = label; bestScore = score; }
  }
  return best;
}

export function detectMood(text: string): string | null {
  const m = pickByScore(text, MOOD_KEYWORDS);
  if (m) return m;
  if (/!{2,}|🎉|❗/.test(text)) return 'happy';
  return null;
}

export function detectGesture(text: string): string | null {
  return pickByScore(text, GESTURE_KEYWORDS);
}

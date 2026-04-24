// Japanese kana → TalkingHead viseme.
//
// Kana is mora-based: each character is roughly one syllable with a single
// dominant mouth shape (the vowel of its row). We map each kana to one of
// the 5 vowel visemes (aa/I/U/E/O) plus 'nn' for ん and 'sil' for the
// glottal-stop sokuon (っ). Yo-on small kana (ゃゅょ) are vowel-like
// glides → vowel visemes. The long-vowel mark (ー) repeats the previous
// vowel — handled by the caller via `kanaViseme(ch, prevVowel)`.
//
// This avoids needing a real phonemizer for Japanese: kana + a 90-entry
// lookup table reads as the same mora rate Yuki's TTS speaks at.

const KANA_VISEME: Record<string, string> = {
  // Hiragana — a-row
  あ: 'aa', か: 'aa', が: 'aa', さ: 'aa', ざ: 'aa',
  た: 'aa', だ: 'aa', な: 'aa', は: 'aa', ば: 'aa', ぱ: 'aa',
  ま: 'aa', や: 'aa', ら: 'aa', わ: 'aa',
  // Hiragana — i-row
  い: 'I', き: 'I', ぎ: 'I', し: 'I', じ: 'I',
  ち: 'I', ぢ: 'I', に: 'I', ひ: 'I', び: 'I', ぴ: 'I',
  み: 'I', り: 'I',
  // Hiragana — u-row
  う: 'U', く: 'U', ぐ: 'U', す: 'U', ず: 'U',
  つ: 'U', づ: 'U', ぬ: 'U', ふ: 'U', ぶ: 'U', ぷ: 'U',
  む: 'U', ゆ: 'U', る: 'U',
  // Hiragana — e-row
  え: 'E', け: 'E', げ: 'E', せ: 'E', ぜ: 'E',
  て: 'E', で: 'E', ね: 'E', へ: 'E', べ: 'E', ぺ: 'E',
  め: 'E', れ: 'E',
  // Hiragana — o-row
  お: 'O', こ: 'O', ご: 'O', そ: 'O', ぞ: 'O',
  と: 'O', ど: 'O', の: 'O', ほ: 'O', ぼ: 'O', ぽ: 'O',
  も: 'O', よ: 'O', ろ: 'O', を: 'O',
  // Hiragana — small yo-on / nasals / sokuon
  ゃ: 'aa', ゅ: 'U', ょ: 'O',
  ん: 'nn',
  っ: 'sil',

  // Katakana — a-row
  ア: 'aa', カ: 'aa', ガ: 'aa', サ: 'aa', ザ: 'aa',
  タ: 'aa', ダ: 'aa', ナ: 'aa', ハ: 'aa', バ: 'aa', パ: 'aa',
  マ: 'aa', ヤ: 'aa', ラ: 'aa', ワ: 'aa',
  // Katakana — i-row
  イ: 'I', キ: 'I', ギ: 'I', シ: 'I', ジ: 'I',
  チ: 'I', ヂ: 'I', ニ: 'I', ヒ: 'I', ビ: 'I', ピ: 'I',
  ミ: 'I', リ: 'I',
  // Katakana — u-row
  ウ: 'U', ク: 'U', グ: 'U', ス: 'U', ズ: 'U',
  ツ: 'U', ヅ: 'U', ヌ: 'U', フ: 'U', ブ: 'U', プ: 'U',
  ム: 'U', ユ: 'U', ル: 'U',
  // Katakana — e-row
  エ: 'E', ケ: 'E', ゲ: 'E', セ: 'E', ゼ: 'E',
  テ: 'E', デ: 'E', ネ: 'E', ヘ: 'E', ベ: 'E', ペ: 'E',
  メ: 'E', レ: 'E',
  // Katakana — o-row
  オ: 'O', コ: 'O', ゴ: 'O', ソ: 'O', ゾ: 'O',
  ト: 'O', ド: 'O', ノ: 'O', ホ: 'O', ボ: 'O', ポ: 'O',
  モ: 'O', ヨ: 'O', ロ: 'O', ヲ: 'O',
  // Katakana — small yo-on / nasals / sokuon
  ャ: 'aa', ュ: 'U', ョ: 'O',
  ン: 'nn',
  ッ: 'sil',
};

const VOWEL_VISEMES = new Set(['aa', 'I', 'U', 'E', 'O']);

export function kanaViseme(ch: string, prevVowel: string): string {
  // Long-vowel mark: hold the previous vowel.
  if (ch === 'ー' || ch === 'ｰ') return prevVowel || 'aa';
  return KANA_VISEME[ch] ?? 'sil';
}

export function isVowelViseme(v: string): boolean {
  return VOWEL_VISEMES.has(v);
}

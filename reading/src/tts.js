// Smart voice selection and Web Speech playback for the reader.
//
// Ported from the kb corpus pipeline's tts_page.py runtime (2026-10): the same
// weighted ranking, Chromium defenses and voice cache, minus the corpus page
// language bar — this app speaks one language at a time, the loaded document's.
const synth = window.speechSynthesis;

let voices = [];
// lang-prefix -> [Voice], sorted best-first
let voiceIndex = new Map();
let voicesReady = false;
// Playback bookkeeping: Chromium stops long utterances on its own after a
// while and leaves the queue silently paused, so a heartbeat nudges it and
// onend/onerror are what actually clear the "speaking" state.
let keepAliveTimer = null;
let speakingEl = null;
let playSeq = 0;
// A speak() that arrived before the live voice list. Speaking now would hand
// the text to whatever default voice the browser picks, which reads Japanese
// with an English voice; the click is held until the real list lands.
let pendingSpeak = null;
let cachedLangs = new Set();
// v2 adds voiceURI: macOS keeps the quality tier (compact/enhanced/premium)
// in the URI, not the display name, so status hints need it before the live
// list lands.
const VOICE_CACHE_KEY = 'tts.voices.v2';
const CANCEL_SETTLE_MS = 60;
const KEEPALIVE_MS = 10000;
const MAC_NOVELTY = /^(bad news|bahh|bells|boing|bubbles|cellos|good news|organ|superstar|trinoids|whisper|wobble|zarvox|albert|fred|ralph|junior|kathy|jester)/i;
// macOS ships the 1980s Eloquence Klatt synthesizer as a persona per locale
// ("Eddy", "Flo", "Grandma", "Grandpa", "Reed", "Rocko", "Sandy", "Shelley";
// French adds "Jacques"). Those robots are registered for a dozen locales
// (fr, es, ja, ko, de, it, zh…) and alphabetically they sort AHEAD of the
// real voices (Kyoko, Mónica, Thomas, Yuna), so without a penalty "Eddy"
// hijacks every language whose real voice starts with a later letter.
const ELOQUENCE_PERSONA = /^(eddy|flo|grandma|grandpa|reed|rocko|sandy|shelley|jacques)(\s*\([^()]*(\([^()]*\))?[^()]*\))?$/i;
// URIs that identify a voice's origin well enough to trust over the
// persona-name fallback, which would otherwise misfire on real voices
// that merely share a persona name (a downloaded premium "Amélie").
const URI_ORIGIN_KNOWN = /eloquence|com\.apple\.(voice|ttsbundle|siri)|com\.apple\.speech\.synthesis|microsoft|google|urn:moz-tts/i;
// Platforms disagree on locale spellings: macOS calls Cantonese "yue-HK"
// (documents ask for zh-HK) and generic Arabic "ar-001" (documents ask for
// ar-SA).
const LANG_ALIASES = { 'yue-hk': 'zh-hk', 'ar-001': 'ar-sa' };
export const VOICE_INSTALL_HINT =
  '（macOS：系统设置 → 辅助功能 → 朗读内容 → 系统声线，下载 Enhanced/Premium 音色；' +
  'Windows：设置 → 时间和语言 → 语音，添加语言语音包）';

function normLang(tag) {
  const t = String(tag || '').toLowerCase();
  return LANG_ALIASES[t] || t;
}

function isEloquence(v) {
  const uri = String(v.voiceURI || '');
  if (/eloquence/i.test(uri)) return true;
  if (URI_ORIGIN_KNOWN.test(uri)) return false; // trust the origin
  // Some engines expose only the display name: "Eddy", "Eddy (Japanese (Japan))".
  return ELOQUENCE_PERSONA.test(String(v.name || '').trim());
}

// Quality tier of a voice: 'hi' (Enhanced/Premium/Neural/Siri), 'robot'
// (Eloquence/novelty), 'lo' (macOS super-compact), 'base' (macOS compact),
// or 'plain'. macOS puts the tier in the voiceURI, not the display name,
// so both are consulted.
export function voiceTier(v) {
  const hay = (String(v.name || '') + ' ' + String(v.voiceURI || '')).toLowerCase();
  if (/enhanced|premium|natural|neural|siri/.test(hay)) return 'hi';
  if (isEloquence(v) || MAC_NOVELTY.test(String(v.name || ''))) return 'robot';
  if (/super[\s_-]?compact/.test(hay)) return 'lo';
  if (/compact/.test(hay)) return 'base';
  return 'plain';
}

// Windows hands the browser SAPI5 ("Microsoft Zira Desktop") and OneCore
// ("Microsoft Zira") voices side by side; macOS hands legacy novelty voices
// (Bad News, Cellos...), Eloquence robot personas AND real voices in
// disk-saving tiers (super-compact/compact/enhanced/premium). Rank instead
// of trusting enumeration order:
// 1. Penalize macOS novelty sound effect voices heavily (+100)
// 2. Penalize macOS Eloquence robot voices (+80) — they read every language
//    with the same 1980s Klatt buzz and alphabetically precede the real
//    French/Spanish/Japanese/Korean voices
// 3. Penalize legacy Windows SAPI5 Desktop voices (+1) over OneCore
// 4. Prefer localService over online (+2) for offline zero-latency stability
// 5. Reward default voices (-1) and Enhanced/Premium/Natural/Neural/Siri
//    voices (-3) — macOS hides that tier in the voiceURI, so check both
// 6. Penalize macOS disk-saving tiers: compact +2, super-compact +4
// The sort is a ranking, never a filter — a language with only a robot
// voice still speaks.
export function voiceRank(v) {
  let rank = 0;
  const name = v.name || '';
  const uri = String(v.voiceURI || '');
  if (MAC_NOVELTY.test(name) || /com\.apple\.speech\.synthesis\.voice\./i.test(uri)) rank += 100;
  if (isEloquence(v)) rank += 80;
  if (/desktop/i.test(name)) rank += 1;
  if (!v.localService) rank += 2;
  if (v.default) rank -= 1;
  const tier = voiceTier(v);
  if (tier === 'hi') rank -= 3;
  else if (tier === 'lo') rank += 4;
  else if (tier === 'base') rank += 2;
  return rank;
}

export function pickVoice(lang) {
  const target = normLang(lang);
  const list = voiceIndex.get(target.split('-')[0]) || [];
  // Exact locale first (en-US must not fall onto an en-GB voice, and the
  // yue-HK Cantonese voice must serve a zh-HK document), then the
  // best-ranked voice of the language family.
  return list.find(v => normLang(v.lang) === target) || list[0] || null;
}

// The installed voice set barely changes between visits, and getVoices() is
// the slow part — on Chromium it is empty until the OS finishes loading. Cache
// the list so status hints can be honest before the live list arrives.
function saveVoiceCache(list) {
  try {
    localStorage.setItem(VOICE_CACHE_KEY, JSON.stringify(list.map(v => (
      { name: v.name, lang: v.lang, default: v.default, voiceURI: v.voiceURI }
    ))));
  } catch (e) {
    // Private mode or quota exceeded — the cache is only an optimisation.
  }
}

function loadVoiceCache() {
  try {
    const raw = localStorage.getItem(VOICE_CACHE_KEY);
    if (!raw) return [];
    const list = JSON.parse(raw);
    if (!Array.isArray(list)) return [];
    cachedLangs = new Set(list
      .map(v => normLang(v.lang).split('-')[0])
      .filter(Boolean));
    return list;
  } catch (e) {
    return [];
  }
}

function stopKeepAlive() {
  if (keepAliveTimer) {
    clearInterval(keepAliveTimer);
    keepAliveTimer = null;
  }
}

function startKeepAlive() {
  stopKeepAlive();
  keepAliveTimer = setInterval(() => {
    if (synth && synth.speaking && !synth.paused) {
      synth.pause();
      synth.resume();
    }
  }, KEEPALIVE_MS);
}

function endPlayback() {
  stopKeepAlive();
  if (speakingEl) {
    speakingEl.classList.remove('speaking');
    speakingEl = null;
  }
}

function loadVoices() {
  const v = synth.getVoices() || [];
  if (v.length > 0) {
    voicesReady = true;
    saveVoiceCache(v);
  }
  // Rank once per load instead of trusting registry enumeration order.
  voices = v.slice().sort((a, b) =>
    voiceRank(a) - voiceRank(b) || String(a.name).localeCompare(String(b.name)));
  voiceIndex = new Map();
  for (const it of voices) {
    const prefix = normLang(it.lang).split('-')[0];
    if (!voiceIndex.has(prefix)) voiceIndex.set(prefix, []);
    voiceIndex.get(prefix).push(it);
  }
  flushPendingSpeak();
}

function runSpeech(el, lang, text) {
  try {
    endPlayback();
    const seq = ++playSeq;
    // cancel() can leave the Chromium queue wedged, and a speak() issued in
    // the same tick as a cancel() is silently swallowed — no error, no sound.
    // Yield one tick, and let a newer click supersede this one.
    synth.cancel();
    setTimeout(() => {
      if (seq !== playSeq) return;
      const u = new SpeechSynthesisUtterance(text);
      // Every utterance pins its parameters: without this, engines reuse the
      // rate/pitch of whatever played last on the page.
      u.lang = lang;
      u.rate = 1.0;
      u.pitch = 1.0;
      const v = pickVoice(lang);
      if (v) u.voice = v;
      u.onend = endPlayback;
      u.onerror = (e) => {
        endPlayback();
        console.warn('TTS error for', lang, text, e);
      };
      speakingEl = el || null;
      if (el) el.classList.add('speaking');
      synth.speak(u);
      startKeepAlive();
    }, CANCEL_SETTLE_MS);
  } catch (err) {
    console.error('speak() failed:', err);
    throw err;
  }
}

function flushPendingSpeak() {
  if (!pendingSpeak || !voicesReady) return; // still nothing to pick from
  const p = pendingSpeak;
  pendingSpeak = null;
  runSpeech(p.el, p.lang, p.text);
}

// If the voice list never turns up we must not leave a click hanging forever.
function giveUpOnPendingSpeak() {
  if (!pendingSpeak) return;
  const p = pendingSpeak;
  pendingSpeak = null;
  runSpeech(p.el, p.lang, p.text);
}

// Speaks `text` in `lang`. `el` is the button that started it: it gets the
// .speaking class while talking, and a second speak() from the same element
// is the stop affordance (there is no dedicated stop button).
//
// Returns 'unsupported' | 'stopped' | 'empty' | 'pending' | 'started' so the
// caller can surface a toast for the states the user cannot see.
export function speak(el, text, lang) {
  if (!synth) return 'unsupported';
  // Emphasis markers should never reach the voice ("perdu star star e"), so
  // strip any that survive unbalanced markdown before reading.
  const clean = String(text || '').replace(/\*/g, '').trim();
  if (!clean) return 'empty';
  if (el && el === speakingEl) {
    playSeq++;
    pendingSpeak = null;
    endPlayback();
    synth.cancel();
    return 'stopped';
  }
  if (!voicesReady) {
    pendingSpeak = { el, lang, text: clean };
    return 'pending';
  }
  runSpeech(el, lang, clean);
  return 'started';
}

export function stop() {
  if (!synth) return;
  playSeq++;
  pendingSpeak = null;
  endPlayback();
  synth.cancel();
}

// What will actually read `lang` right now: the picked voice's tier and name,
// or `voice: null` when the language is missing from the local voice set.
// `ready` is false until the live voice list lands; `cached` then tells the
// caller whether the last visit had the language at all.
export function voiceStatus(lang) {
  const prefix = normLang(lang).split('-')[0];
  if (!voicesReady) {
    return { ready: false, cached: cachedLangs.size > 0 && cachedLangs.has(prefix), voice: null };
  }
  const v = pickVoice(lang);
  return { ready: true, cached: true, voice: v ? { name: v.name, tier: voiceTier(v), localService: !!v.localService } : null };
}

if (synth) {
  loadVoiceCache();
  loadVoices();
  if (typeof synth.addEventListener === 'function') {
    synth.addEventListener('voiceschanged', loadVoices);
  } else if ('onvoiceschanged' in synth) {
    synth.onvoiceschanged = loadVoices;
  }
  // Some browsers never fire voiceschanged. Poll a few times as a fallback.
  let polls = 0;
  const poll = setInterval(() => {
    polls++;
    if (voicesReady || polls >= 10) {
      clearInterval(poll);
      // No voice list after 2.5s — play what was clicked rather than
      // silently dropping it.
      giveUpOnPendingSpeak();
      return;
    }
    loadVoices();
  }, 250);
}

// Headless regression hook: test harnesses stub the DOM and speechSynthesis,
// feed a fixture voice list through loadVoices(), and read voiceRank,
// voiceTier and pickVoice back through this slot. Inert while browsing —
// nothing in the app itself ever sets window.__ttsTestHook.
if (typeof window !== 'undefined' && typeof window.__ttsTestHook === 'function') {
  window.__ttsTestHook({
    voiceRank, voiceTier, isEloquence, normLang, pickVoice, loadVoices
  });
}

import { api } from './api.js';
import { speak as ttsSpeak, voiceStatus, VOICE_INSTALL_HINT } from './tts.js';

export class InspectorDrawer {
  constructor(drawerElement, readerContainer, showToast, onSentenceUpdated) {
    this.drawer = drawerElement;
    this.readerContainer = readerContainer;
    this.showToast = showToast;
    this.onSentenceUpdated = onSentenceUpdated;
    this.currentSentence = null;
    // Set by main.js from the loaded document; drives TTS voice picking.
    this.language = 'en-US';

    this.contentEl = this.drawer.querySelector('.drawer-content');
    this.closeBtn = this.drawer.querySelector('.btn-close-drawer');

    this.bindEvents();
  }

  bindEvents() {
    this.closeBtn.addEventListener('click', () => {
      this.close();
    });
  }

  open() {
    this.drawer.classList.add('open');
    this.readerContainer.classList.add('with-drawer');
  }

  close() {
    this.drawer.classList.remove('open');
    this.readerContainer.classList.remove('with-drawer');
  }

  async inspectSentence(sentenceObj) {
    this.currentSentence = sentenceObj;
    this.open();

    // Show loading skeleton
    this.contentEl.innerHTML = `
      <div class="inspector-hero">
        <div class="hero-sentence-id">
          <span>${sentenceObj.sentence_id}</span>
          <span>⏳ 正在进行语法透视拆解...</span>
        </div>
        <div class="hero-orig">${this.escapeHtml(sentenceObj.original)}</div>
        <div class="hero-trans">${this.escapeHtml(sentenceObj.translation || '（解析后呈现精准翻译）')}</div>
      </div>
      <div style="text-align: center; padding: 40px 0; color: var(--text-muted); font-size: 13px;">
        <div style="font-size: 24px; margin-bottom: 8px;">🔬</div>
        正在通过结构化引擎切片句法主干、锁定多义词语境与文化背景...
      </div>
    `;

    try {
      const deepAnalysis = await api.getSentenceAnalysis(sentenceObj.sentence_id);
      this.renderAnalysis(deepAnalysis);
      if (this.onSentenceUpdated) {
        this.onSentenceUpdated(sentenceObj.sentence_id, deepAnalysis);
      }
    } catch (err) {
      console.error(err);
      this.contentEl.innerHTML += `
        <div style="margin-top: 16px; padding: 12px; background: #fee2e2; color: #dc2626; border-radius: 8px; font-size: 13px;">
          解析失败: ${err.message}
        </div>
      `;
    }
  }

  renderAnalysis(analysis) {
    const orig = analysis.original || this.currentSentence.original;
    const trans = analysis.translation || this.currentSentence.translation || '（暂无译文）';
    const tone = analysis.overall_tone || '沉静文学叙事';

    // 1. Syntax Components
    let grammarHtml = '';
    if (analysis.grammar_analysis) {
      const g = analysis.grammar_analysis;
      const structName = g.structure || '通用句型';
      let compList = '';
      if (g.components && g.components.length > 0) {
        compList = g.components.map(c => `
          <div class="component-badge">
            <span class="comp-role">${this.escapeHtml(c.role)}</span>
            <span class="comp-element">"${this.escapeHtml(c.element)}"</span>
          </div>
        `).join('');
      } else {
        compList = '<div style="color:var(--text-light); font-size:13px;">基础陈述句式</div>';
      }

      grammarHtml = `
        <div class="inspector-section">
          <div class="section-label">
            <span>📐 句法主干结构化切片</span>
          </div>
          <div class="syntax-structure-card">
            <div class="structure-name">
              <span>🏷️</span>
              <span>${this.escapeHtml(structName)}</span>
            </div>
            <div class="components-flow">
              ${compList}
            </div>
          </div>
        </div>
      `;
    }

    // 2. Vocabulary & Phrases
    let vocabHtml = '';
    if (analysis.vocabulary_and_phrases && analysis.vocabulary_and_phrases.length > 0) {
      const vCards = analysis.vocabulary_and_phrases.map((v, idx) => `
        <div class="vocab-card" id="vocab_card_${idx}">
          <div class="vocab-top">
            <span class="vocab-token">${this.escapeHtml(v.token)}</span>
            <span class="vocab-pos">${this.escapeHtml(v.pos || '词汇')}</span>
          </div>
          <div class="vocab-meaning">📖 <strong>${this.escapeHtml(v.literal_meaning)}</strong></div>
          ${v.cultural_background ? `<div class="vocab-notes">🏛️ ${this.escapeHtml(v.cultural_background)}</div>` : ''}
          <div style="display:flex; justify-content:flex-end;">
            <button class="btn-add-vocab" 
                    data-word="${this.escapeHtml(v.token)}" 
                    data-pos="${this.escapeHtml(v.pos || '')}"
                    data-trans="${this.escapeHtml(v.literal_meaning)}"
                    data-notes="${this.escapeHtml(v.cultural_background || '')}"
                    data-ctx="${this.escapeHtml(orig)}"
                    data-sid="${this.escapeHtml(analysis.sentence_id)}">
              + 加入生词本
            </button>
          </div>
        </div>
      `).join('');

      vocabHtml = `
        <div class="inspector-section">
          <div class="section-label">
            <span>🔍 词法速查与语境锁定（非通用词典）</span>
          </div>
          <div class="vocab-list">
            ${vCards}
          </div>
        </div>
      `;
    }

    // 3. Idioms & Allusions
    let idiomHtml = '';
    if (analysis.idioms_and_conventions && analysis.idioms_and_conventions.length > 0) {
      const iCards = analysis.idioms_and_conventions.map(i => `
        <div class="idiom-card">
          <div class="idiom-expression">✨ ${this.escapeHtml(i.expression)}</div>
          <div class="idiom-usage">${this.escapeHtml(i.usage)}</div>
        </div>
      `).join('');

      idiomHtml = `
        <div class="inspector-section">
          <div class="section-label">
            <span>🎭 语境典故与约定俗成</span>
          </div>
          ${iCards}
        </div>
      `;
    }

    this.contentEl.innerHTML = `
      <div class="inspector-hero">
        <div class="hero-sentence-id">
          <span>${this.escapeHtml(analysis.sentence_id)}</span>
          <button class="btn-mini btn-speak-sentence" title="朗读句子">🔊 发音</button>
        </div>
        <div class="hero-orig">${this.escapeHtml(orig)}</div>
        <div class="hero-trans">${this.escapeHtml(trans)}</div>
        <div class="hero-tone">🎨 语调基调：${this.escapeHtml(tone)}</div>
      </div>

      ${grammarHtml}
      ${vocabHtml}
      ${idiomHtml}
    `;

    // Attach listeners inside drawer
    // Audio speech
    const speakBtn = this.contentEl.querySelector('.btn-speak-sentence');
    if (speakBtn) {
      speakBtn.addEventListener('click', () => {
        this.speakText(speakBtn, orig);
      });
    }

    // Add to vocab buttons
    const addVocabBtns = this.contentEl.querySelectorAll('.btn-add-vocab');
    addVocabBtns.forEach(btn => {
      btn.addEventListener('click', async () => {
        try {
          await api.addVocabulary({
            word: btn.dataset.word,
            pos: btn.dataset.pos,
            translation: btn.dataset.trans,
            cultural_background: btn.dataset.notes,
            sentence_context: btn.dataset.ctx,
            sentence_id: btn.dataset.sid
          });
          btn.classList.add('added');
          btn.innerHTML = '✓ 已加入生词本';
          this.showToast(`已将 "${btn.dataset.word}" 加入生词本`, 'success');
        } catch (e) {
          this.showToast(`添加生词失败: ${e.message}`, 'error');
        }
      });
    });
  }

  // Reads `text` in the document's language through tts.js: ranked voice
  // picking instead of trusting the default voice, playback heartbeat against
  // the Chromium pause bug, and the same click doubling as the stop button.
  // A missing local voice is worth a hint — the user hears the wrong accent
  // otherwise and has no way to know why.
  speakText(btn, text) {
    const status = ttsSpeak(btn, text, this.language);
    if (status === 'unsupported') {
      this.showToast('当前浏览器不支持语音发音', 'error');
      return;
    }
    const vs = voiceStatus(this.language);
    if (status !== 'stopped' && vs.ready && !vs.voice) {
      this.showToast(`本机未安装「${this.language}」的语音，朗读将由其他声线代替。${VOICE_INSTALL_HINT}`, 'info');
    }
  }

  escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }
}

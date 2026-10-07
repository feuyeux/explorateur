import { api } from './api.js';

export class DualReader {
  constructor(sourceContainer, transContainer, onSentenceSelected, showToast) {
    this.sourceContainer = sourceContainer;
    this.transContainer = transContainer;
    this.onSentenceSelected = onSentenceSelected;
    this.showToast = showToast;
    this.currentDoc = null;
    this.activeSentenceId = null;

    this.bindGlobalEvents();
  }

  bindGlobalEvents() {
    // Synchronized scroll hint or smooth interactions can be added here
  }

  loadDocument(docData) {
    this.currentDoc = docData;
    this.activeSentenceId = null;
    this.render();
  }

  render() {
    if (!this.currentDoc || !this.currentDoc.paragraphs || this.currentDoc.paragraphs.length === 0) {
      this.sourceContainer.innerHTML = `
        <div class="empty-state">
          <svg class="empty-icon" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          <div class="empty-title">暂无文档内容</div>
          <div class="empty-desc">请点击上方“导入原著”或选择“经典样例”开启精读之旅。</div>
        </div>
      `;
      this.transContainer.innerHTML = `
        <div class="empty-state">
          <div class="empty-title" style="color:var(--text-light);">等待原文导入</div>
        </div>
      `;
      return;
    }

    let sourceHtml = '';
    let transHtml = '';

    this.currentDoc.paragraphs.forEach((p, pIndex) => {
      const pId = p.paragraph_id;
      const pNumber = p.order_index || (pIndex + 1);

      // Check if all sentences in paragraph have translation
      const hasTranslations = p.sentences.some(s => s.translation);

      // Left pane (Source)
      let pSourceSentences = '';
      p.sentences.forEach(s => {
        const hasAnalysisClass = s.has_deep_analysis ? 'has-analysis' : '';
        pSourceSentences += `<span class="sentence-item source-sentence ${hasAnalysisClass}" data-sentence-id="${s.sentence_id}">${this.escapeHtml(s.original)} </span>`;
      });

      sourceHtml += `
        <div class="reader-paragraph" id="src_${pId}" data-paragraph-id="${pId}">
          <div class="para-meta">
            <span>§ ${pNumber}</span>
            <div class="para-tools">
              <button class="btn-mini btn-parse-para" data-paragraph-id="${pId}">
                ⚡ 一键解析本段
              </button>
            </div>
          </div>
          <div class="para-content">${pSourceSentences}</div>
        </div>
      `;

      // Right pane (Translation)
      let pTransSentences = '';
      p.sentences.forEach(s => {
        const transText = s.translation || '（待点击或解析整段生成译文）';
        const isUntranslated = !s.translation ? 'style="color: var(--text-light); font-style: italic;"' : '';
        pTransSentences += `<span class="sentence-item trans-sentence" data-sentence-id="${s.sentence_id}" ${isUntranslated}>${this.escapeHtml(transText)} </span>`;
      });

      transHtml += `
        <div class="reader-paragraph" id="trans_${pId}" data-paragraph-id="${pId}">
          <div class="para-meta">
            <span>中文对齐 § ${pNumber}</span>
            <span style="font-size:11px; color:${hasTranslations ? '#10b981' : 'var(--text-light)'};">
              ${hasTranslations ? '✓ 已对齐' : '等待拆解'}
            </span>
          </div>
          <div class="para-content">${pTransSentences}</div>
        </div>
      `;
    });

    this.sourceContainer.innerHTML = sourceHtml;
    this.transContainer.innerHTML = transHtml;

    this.attachSentenceListeners();
  }

  attachSentenceListeners() {
    // 1. Sentence hover and click bindings
    const allSentenceNodes = document.querySelectorAll('.sentence-item');
    allSentenceNodes.forEach(node => {
      const sentId = node.dataset.sentenceId;

      node.addEventListener('mouseenter', () => {
        this.highlightPair(sentId, true);
      });

      node.addEventListener('mouseleave', () => {
        this.highlightPair(sentId, false);
      });

      node.addEventListener('click', () => {
        this.selectSentence(sentId);
      });
    });

    // 2. Paragraph batch parse buttons
    const parseButtons = document.querySelectorAll('.btn-parse-para');
    parseButtons.forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const pId = btn.dataset.paragraphId;
        await this.handleAnalyzeParagraph(pId, btn);
      });
    });
  }

  highlightPair(sentenceId, isHovered) {
    const pairNodes = document.querySelectorAll(`[data-sentence-id="${sentenceId}"]`);
    pairNodes.forEach(n => {
      if (isHovered) {
        n.classList.add('hovered');
      } else {
        n.classList.remove('hovered');
      }
    });
  }

  // Resolves a sentence id to its object in the loaded document.
  findSentence(sentenceId) {
    if (!this.currentDoc || !this.currentDoc.paragraphs) return null;
    for (const p of this.currentDoc.paragraphs) {
      const found = p.sentences.find(s => s.sentence_id === sentenceId);
      if (found) return found;
    }
    return null;
  }

  selectSentence(sentenceId) {
    if (this.activeSentenceId === sentenceId) {
      // Re-trigger the inspector for an already-selected sentence (a second
      // click, or the re-select after its paragraph was re-analysed). The
      // inspector must be handed the sentence *object*: it reads
      // `.sentence_id` off whatever it receives, and passing the raw id made
      // that `undefined`, so the invoke dropped the key and every such click
      // died with "missing required key sentenceId".
      const active = this.findSentence(sentenceId);
      if (this.onSentenceSelected && active) {
        this.onSentenceSelected(active);
      }
      return;
    }

    // Remove previous active state
    if (this.activeSentenceId) {
      document.querySelectorAll(`[data-sentence-id="${this.activeSentenceId}"]`).forEach(n => {
        n.classList.remove('active');
      });
    }

    this.activeSentenceId = sentenceId;

    // Apply active class to both original and translated sentence
    const activePair = document.querySelectorAll(`[data-sentence-id="${sentenceId}"]`);
    activePair.forEach(n => {
      n.classList.add('active');
    });

    // Find the corresponding sentence object
    const targetSentence = this.findSentence(sentenceId);

    if (this.onSentenceSelected && targetSentence) {
      this.onSentenceSelected(targetSentence);
    }
  }

  async handleAnalyzeParagraph(paragraphId, btnNode) {
    const originalText = btnNode.innerHTML;
    btnNode.innerHTML = '⏳ 正在拆解分析...';
    btnNode.disabled = true;

    try {
      const res = await api.analyzeParagraph(paragraphId);

      // `engine` tells a demo echo apart from a live call. Without it the
      // button always claimed success while the right pane kept showing the
      // original: offline-demo echoes the source as 【译文】原文, and
      // offline-fallback means the live call failed and the demo stood in.
      if (res.engine === 'offline-demo') {
        this.showToast('离线演示模式：当前显示的是占位译文（原文回显）。在「⚙️ 设置」里配置 API Key 并保存后，重新点击本段即可生成真实译文。', 'info');
      } else if (res.engine === 'offline-fallback') {
        this.showToast(`模型调用失败，已回退离线演示引擎：${res.fallback_reason || '未知原因'}`, 'error');
      } else {
        this.showToast('段落结构化解析完成！', 'success');
      }

      // Update local state
      const targetP = this.currentDoc.paragraphs.find(p => p.paragraph_id === paragraphId);
      if (targetP && res.sentences) {
        targetP.sentences = res.sentences;
      }

      // Re-render
      this.render();

      // If active sentence belongs to this paragraph, re-select
      if (this.activeSentenceId && this.activeSentenceId.includes(paragraphId)) {
        this.selectSentence(this.activeSentenceId);
      }
    } catch (err) {
      console.error(err);
      this.showToast(`段落解析失败: ${err.message}`, 'error');
      btnNode.innerHTML = originalText;
      btnNode.disabled = false;
    }
  }

  updateSentenceData(sentenceId, updatedAnalysis) {
    if (!this.currentDoc || !this.currentDoc.paragraphs) return;
    for (const p of this.currentDoc.paragraphs) {
      const s = p.sentences.find(item => item.sentence_id === sentenceId);
      if (s) {
        s.translation = updatedAnalysis.translation || s.translation;
        s.has_deep_analysis = true;
        s.deep_analysis = updatedAnalysis;
        break;
      }
    }

    // Update translated text in DOM immediately
    const transNode = document.querySelector(`.trans-sentence[data-sentence-id="${sentenceId}"]`);
    if (transNode && updatedAnalysis.translation) {
      transNode.textContent = updatedAnalysis.translation + ' ';
      transNode.removeAttribute('style');
    }

    // Mark original node as having deep analysis
    const srcNode = document.querySelector(`.source-sentence[data-sentence-id="${sentenceId}"]`);
    if (srcNode) {
      srcNode.classList.add('has-analysis');
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

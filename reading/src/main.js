import { api } from './api.js';
import { DualReader } from './dual_reader.js';
import { InspectorDrawer } from './inspector.js';
import { VocabularyManager } from './vocabulary.js';
import { SettingsManager } from './settings.js';

class ReadyApp {
  constructor() {
    this.currentDocId = null;
    this.batchTimer = null;
    this.batchModal = document.getElementById('batch_modal');

    // Toast notification container
    this.toastContainer = document.getElementById('toast_container');

    // Init sub-managers
    this.inspector = new InspectorDrawer(
      document.getElementById('inspector_drawer'),
      document.querySelector('.reader-container'),
      (msg, type) => this.showToast(msg, type),
      (sentId, data) => this.handleSentenceUpdated(sentId, data)
    );

    this.reader = new DualReader(
      document.getElementById('source_pane_content'),
      document.getElementById('trans_pane_content'),
      (sentenceObj) => this.inspector.inspectSentence(sentenceObj),
      (msg, type) => this.showToast(msg, type)
    );

    this.vocabManager = new VocabularyManager(
      document.getElementById('vocab_modal'),
      (msg, type) => this.showToast(msg, type)
    );

    this.settingsManager = new SettingsManager(
      document.getElementById('settings_modal'),
      (msg, type) => this.showToast(msg, type)
    );

    this.uploadModal = document.getElementById('upload_modal');

    this.bindDOM();
    this.init();
  }

  showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = 'toast';
    const icon = type === 'success' ? '✓' : type === 'error' ? '✕' : 'ℹ';
    // The message is assembled from model output (a vocabulary token), the
    // uploaded file name and backend error strings, so it is inserted as text
    // rather than markup. Every other renderer in the app escapes for the same
    // reason; this one used to be the exception.
    const iconEl = document.createElement('span');
    iconEl.style.fontWeight = 'bold';
    iconEl.textContent = icon;
    const textEl = document.createElement('span');
    textEl.textContent = message;
    toast.append(iconEl, document.createTextNode(' '), textEl);
    this.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transition = 'opacity 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  handleSentenceUpdated(sentenceId, analysisData) {
    this.reader.updateSentenceData(sentenceId, analysisData);
  }

  bindDOM() {
    // 1. Doc select dropdown
    const docSelect = document.getElementById('doc_select');
    docSelect.addEventListener('change', (e) => {
      const docId = e.target.value;
      if (docId) {
        this.loadDocById(docId);
      }
    });

    // 2. Upload button & modal
    const btnUpload = document.getElementById('btn_open_upload');
    const btnCloseUpload = document.querySelector('.btn-close-upload');
    btnUpload.addEventListener('click', () => {
      this.uploadModal.classList.add('open');
    });
    btnCloseUpload.addEventListener('click', () => {
      this.uploadModal.classList.remove('open');
    });
    this.uploadModal.addEventListener('click', (e) => {
      if (e.target === this.uploadModal) {
        this.uploadModal.classList.remove('open');
      }
    });

    // File input & Dropzone
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('file_input');
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });
    dropzone.addEventListener('dragleave', () => dropzone.classList.remove('dragover'));
    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length > 0) {
        this.handleFileUpload(e.dataTransfer.files[0]);
      }
    });

    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        this.handleFileUpload(e.target.files[0]);
      }
    });

    // 3. Built-in Samples Quick Loader
    document.getElementById('btn_load_sample_moby').addEventListener('click', async () => {
      await this.loadSampleBook('moby_dick');
    });
    document.getElementById('btn_load_sample_gatsby').addEventListener('click', async () => {
      await this.loadSampleBook('the_great_gatsby');
    });

    // 4. Open Vocab modal
    document.getElementById('btn_open_vocab').addEventListener('click', () => {
      this.vocabManager.open();
    });

    // 5. Whole-document analysis
    document.getElementById('btn_batch_run').addEventListener('click', () => {
      this.runWholeDocument();
    });
    document.getElementById('btn_batch_cancel').addEventListener('click', async () => {
      try {
        await api.cancelBatchAnalysis();
        this.showToast('已请求停止，正在收尾当前任务…', 'info');
      } catch (err) {
        this.showToast(`停止失败: ${err.message}`, 'error');
      }
    });
    document.getElementById('btn_batch_done').addEventListener('click', () => {
      this.batchModal.classList.remove('open');
      this.batchTimer = null;
    });

    // 6. Export the current document as Markdown
    document.getElementById('btn_export_markdown').addEventListener('click', () => {
      this.exportMarkdown();
    });

    // 7. Open Settings modal
    document.getElementById('btn_open_settings').addEventListener('click', () => {
      this.settingsManager.open();
    });

    // 8. Dark mode toggle
    const btnTheme = document.getElementById('btn_toggle_theme');
    btnTheme.addEventListener('click', () => {
      const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
      document.documentElement.setAttribute('data-theme', isDark ? 'light' : 'dark');
      btnTheme.innerHTML = isDark ? '🌙' : '☀️';
      localStorage.setItem('ready_theme', isDark ? 'light' : 'dark');
    });

    const savedTheme = localStorage.getItem('ready_theme');
    if (savedTheme) {
      document.documentElement.setAttribute('data-theme', savedTheme);
      btnTheme.innerHTML = savedTheme === 'dark' ? '☀️' : '🌙';
    }
  }

  async init() {
    await this.refreshDocList();
    // If no documents exist, load Moby Dick sample by default
    const docSelect = document.getElementById('doc_select');
    if (docSelect.options.length <= 1) {
      await this.loadSampleBook('moby_dick');
    } else {
      // Pick first doc
      const firstDocId = docSelect.options[1].value;
      docSelect.value = firstDocId;
      await this.loadDocById(firstDocId);
    }
  }

  async refreshDocList() {
    try {
      const docs = await api.getDocuments();
      const select = document.getElementById('doc_select');
      select.innerHTML = '<option value="">-- 选择或切换原著 --</option>';

      docs.forEach(d => {
        const opt = document.createElement('option');
        opt.value = d.id;
        opt.textContent = `${d.title} (${d.total_paragraphs} 段落)`;
        select.appendChild(opt);
      });
    } catch (e) {
      console.error(e);
    }
  }

  async loadDocById(docId) {
    this.currentDocId = docId;
    document.getElementById('doc_select').value = docId;

    try {
      const docData = await api.getDocument(docId);
      this.reader.loadDocument(docData);
      // The tag drives TTS voice picking in both the reader panes and the
      // inspector drawer.
      this.inspector.language = docData.language || 'en-US';
      document.getElementById('current_doc_title').textContent = docData.title;
      document.getElementById('current_doc_author').textContent = `[${docData.file_type.toUpperCase()}] ${docData.author}`;
    } catch (err) {
      this.showToast(`加载文档失败: ${err.message}`, 'error');
    }
  }

  async loadSampleBook(sampleName) {
    try {
      this.showToast('正在加载经典文学原著样本...', 'info');
      const res = await api.loadSample(sampleName);
      await this.refreshDocList();
      await this.loadDocById(res.doc_id);
      this.showToast(`《${res.title}》已准备就绪，点击句子即可语法透视！`, 'success');
    } catch (err) {
      this.showToast(`加载样本失败: ${err.message}`, 'error');
    }
  }

  async handleFileUpload(file) {
    // The language pick drives TTS voice selection; it must be read before the
    // modal closes, because closing is what hides the select.
    const language = document.getElementById('upload_language')?.value || '';
    this.uploadModal.classList.remove('open');
    this.showToast(`正在解析上传的 ${file.name}...`, 'info');

    try {
      const res = await api.uploadDocument(file, language);
      this.showToast(`文档《${res.title}》解析完成，共 ${res.total_paragraphs} 段！`, 'success');
      await this.refreshDocList();
      await this.loadDocById(res.doc_id);
    } catch (err) {
      this.showToast(`上传失败: ${err.message}`, 'error');
    }
  }

  // Runs the whole book in one go: paragraph translations first, then a deep
  // analysis for every sentence. Rust owns the queue; this only starts it and
  // polls for counters, because the app has no event channel to push on.
  async runWholeDocument() {
    if (!this.currentDocId) {
      this.showToast('请先选择一本原著', 'error');
      return;
    }
    if (!window.confirm(
      `将为《${document.getElementById('current_doc_title').textContent.trim()}》执行全文翻译与逐句深度解析。\n\n` +
      '这会连续调用模型 API 并消耗额度，已解析的内容会自动跳过（可随时中断，稍后可继续）。\n\n确定开始吗？'
    )) return;

    try {
      const res = await api.startBatchAnalysis(this.currentDocId, 3);
      if (!res.started) {
        this.showToast('这本书已经全部解析过了，无需重复运行', 'info');
        return;
      }
      this.showBatchModal(res);
      this.pollBatch();
    } catch (err) {
      // The Rust side refuses to start in offline demo mode; that message is
      // the actionable one, so show it verbatim.
      this.showToast(err.message || `启动失败: ${err.message}`, 'error');
    }
  }

  showBatchModal(res) {
    const set = (id, text) => { document.getElementById(id).textContent = text; };
    set('batch_summary',
      `待翻译段落 ${res.paragraphs} 段 · 待深度解析句子 ${res.sentences} 句` +
      `（已跳过 ${res.paragraphs_already_done} 段 / ${res.sentences_already_done} 句）`);
    set('batch_phase', '正在翻译段落…');
    set('batch_numbers', `0 / ${res.total}`);
    document.getElementById('batch_bar').style.width = '0%';
    document.getElementById('batch_bar').classList.remove('failed');
    document.getElementById('batch_error').style.display = 'none';
    document.getElementById('btn_batch_cancel').style.display = '';
    document.getElementById('btn_batch_done').style.display = 'none';
    this.batchModal.classList.add('open');
  }

  async pollBatch() {
    if (this.batchTimer) clearInterval(this.batchTimer);
    this.batchTimer = setInterval(async () => {
      try {
        const p = await api.batchProgress();
        if (!p.running) {
          clearInterval(this.batchTimer);
          this.batchTimer = null;
          document.getElementById('btn_batch_cancel').style.display = 'none';
          document.getElementById('btn_batch_done').style.display = '';
          document.getElementById('batch_phase').textContent =
            p.cancelling ? '已停止' : (p.failed ? '完成（有失败项）' : '全部完成');
          if (p.failed) {
            const bar = document.getElementById('batch_bar');
            bar.classList.add('failed');
            document.getElementById('batch_error').style.display = '';
            document.getElementById('batch_error').textContent =
              `${p.failed} 项失败，最后一次：${p.last_error || '未知原因'}`;
          }
          this.showToast(
            `全文处理结束：成功 ${p.done - p.failed}，失败 ${p.failed}。现在可以导出 Markdown。`,
            p.failed ? 'error' : 'success');
          await this.loadDocById(this.currentDocId); // refresh the reading panes
          return;
        }

        const pct = p.total ? Math.min(100, Math.round((p.done / p.total) * 100)) : 0;
        document.getElementById('batch_bar').style.width = `${pct}%`;
        document.getElementById('batch_numbers').textContent = `${p.done} / ${p.total}`;
        document.getElementById('batch_phase').textContent = p.cancelling
          ? '正在停止…'
          : (p.phase === 'sentences'
              ? `逐句深度解析${p.current ? ' · ' + p.current : ''}`
              : `翻译段落${p.current ? ' · ' + p.current : ''}`);
        if (p.failed) {
          document.getElementById('batch_bar').classList.add('failed');
        }
      } catch (err) {
        clearInterval(this.batchTimer);
        this.batchTimer = null;
        this.showToast(`读取进度失败: ${err.message}`, 'error');
      }
    }, 800);
  }

  // Exports the current book as Markdown: bilingual paragraphs plus whatever
  // sentence analyses are already cached. Rust does the rendering, so this
  // never waits on a model call.
  async exportMarkdown() {
    if (!this.currentDocId) {
      this.showToast('请先选择一本原著', 'error');
      return;
    }
    try {
      const title = document.getElementById('current_doc_title').textContent.trim() || 'book';
      const { save } = window.__TAURI__.dialog;
      const path = await save({
        defaultPath: `${title.replace(/[\/\\:*?"<>|]/g, '_')}.md`,
        filters: [{ name: 'Markdown', extensions: ['md'] }]
      });
      if (!path) return; // user cancelled

      const res = await api.exportMarkdownToFile(this.currentDocId, path);
      if (!res.sentences) {
        this.showToast('这本书还没有已解析的段落，先点「⚡ 一键解析本段」再导出', 'info');
        return;
      }
      this.showToast(`已导出 ${res.sentences} 句译文与解析 → ${res.path}`, 'success');
    } catch (err) {
      this.showToast(`导出失败: ${err.message}`, 'error');
    }
  }
}

// Bootstrap on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  window.app = new ReadyApp();
});

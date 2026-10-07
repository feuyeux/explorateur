// API client for the Ready Reader backend (Tauri IPC — no HTTP server).
const { invoke } = window.__TAURI__.core;

async function call(cmd, args = {}) {
  try {
    return await invoke(cmd, args);
  } catch (err) {
    // Tauri commands reject with a plain String error.
    throw new Error(typeof err === 'string' ? err : (err?.message || JSON.stringify(err)));
  }
}

export const api = {
  async getDocuments() {
    return call('list_documents');
  },

  async getDocument(docId) {
    return call('get_document', { docId });
  },

  async uploadDocument(file) {
    // The webview reads the file as text; Rust receives the decoded string, so
    // there is no multipart encoding anywhere in the app. The extension goes
    // along too: the picker's filter and `accept=` are cosmetic, and a
    // drag-and-drop honours neither, so the backend is the only place that can
    // actually reject a .pdf or .epub.
    const text = await file.text();
    const stem = file.name.replace(/\.[^.]+$/, '');
    const fileExt = (file.name.match(/\.([^.]+)$/)?.[1] || '').toLowerCase();
    return call('upload_document', { title: stem, content: text, fileExt });
  },

  async loadSample(sampleName = 'moby_dick') {
    return call('load_sample', { sampleName });
  },

  async deleteDocument(docId) {
    return call('delete_document', { docId });
  },

  async analyzeParagraph(paragraphId) {
    return call('analyze_paragraph', { paragraphId });
  },

  async getSentenceAnalysis(sentenceId) {
    return call('get_sentence_analysis', { sentenceId });
  },

  async getVocabulary() {
    return call('get_vocabulary');
  },

  async addVocabulary(payload) {
    return call('add_vocabulary', {
      word: payload.word,
      translation: payload.translation,
      pos: payload.pos ?? '',
      sentenceContext: payload.sentence_context ?? '',
      sentenceId: payload.sentence_id ?? '',
      culturalBackground: payload.cultural_background ?? ''
    });
  },

  async deleteVocabulary(vocabId) {
    return call('delete_vocabulary', { vocabId });
  },

  async exportAnkiToFile(path) {
    // Rust renders the deck and writes it; the path comes from the native save
    // dialog the user just confirmed.
    return call('export_anki_to', { path });
  },

  async exportMarkdownToFile(docId, path) {
    // Same split as the Anki deck: the dialog lives here, the Markdown is
    // rendered and written by Rust from the cached rows.
    return call('export_markdown_to', { docId, path });
  },

  async startBatchAnalysis(docId, concurrency) {
    return call('start_batch_analysis', { docId, concurrency });
  },

  async batchProgress() {
    return call('batch_progress');
  },

  async cancelBatchAnalysis() {
    return call('cancel_batch_analysis');
  },

  async getSettings() {
    return call('get_settings');
  },

  async updateSettings(payload) {
    return call('update_settings', {
      provider: payload.provider,
      apiKey: payload.api_key ?? '',
      baseUrl: payload.base_url ?? '',
      modelName: payload.model_name ?? '',
      temperature: payload.temperature,
      mockMode: !!payload.mock_mode
    });
  }
};

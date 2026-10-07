import { api } from './api.js';

export class VocabularyManager {
  constructor(modalElement, showToast) {
    this.modal = modalElement;
    this.showToast = showToast;
    this.itemsContainer = this.modal.querySelector('#vocab_list_container');
    this.countEl = this.modal.querySelector('#vocab_count');
    this.exportBtn = this.modal.querySelector('#btn_export_anki');
    this.closeBtn = this.modal.querySelector('.btn-close-vocab');

    this.bindEvents();
  }

  bindEvents() {
    this.closeBtn.addEventListener('click', () => this.close());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.close();
    });

    this.exportBtn.addEventListener('click', () => {
      this.exportAnki();
    });
  }

  open() {
    this.modal.classList.add('open');
    this.loadVocabulary();
  }

  close() {
    this.modal.classList.remove('open');
  }

  async loadVocabulary() {
    try {
      const items = await api.getVocabulary();
      this.countEl.textContent = `${items.length} 个`;

      if (items.length === 0) {
        this.itemsContainer.innerHTML = `
          <div style="text-align: center; padding: 40px 0; color: var(--text-muted); font-size: 14px;">
            生词本暂无内容。在阅读点击句子时，可在右侧“语法透视镜”中一键收藏词汇。
          </div>
        `;
        return;
      }

      const rows = items.map(item => `
        <tr>
          <td>
            <div style="font-weight: 700; font-family: var(--font-serif); font-size: 15px;">${this.escapeHtml(item.word)}</div>
            <span style="font-size: 11px; color: var(--text-light);">${this.escapeHtml(item.created_at || '')}</span>
          </td>
          <td><span class="vocab-pos">${this.escapeHtml(item.pos || '词汇')}</span></td>
          <td>${this.escapeHtml(item.translation)}</td>
          <td style="max-width: 220px; font-size: 12px; color: var(--text-muted); font-style: italic;">
            ${this.escapeHtml(item.sentence_context || '-')}
          </td>
          <td>
            <button class="btn-mini btn-del-vocab" data-id="${item.id}" style="color: #ef4444; border-color: #fee2e2;">
              删除
            </button>
          </td>
        </tr>
      `).join('');

      this.itemsContainer.innerHTML = `
        <table class="vocab-table">
          <thead>
            <tr>
              <th>词汇</th>
              <th>词性</th>
              <th>语境释义</th>
              <th>出处语境</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
          </tbody>
        </table>
      `;

      // Attach delete listeners
      const delBtns = this.itemsContainer.querySelectorAll('.btn-del-vocab');
      delBtns.forEach(btn => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.id;
          try {
            await api.deleteVocabulary(id);
            this.showToast('已从生词本移除', 'success');
            this.loadVocabulary();
          } catch (e) {
            this.showToast(`删除失败: ${e.message}`, 'error');
          }
        });
      });

    } catch (err) {
      this.showToast(`加载生词本失败: ${err.message}`, 'error');
    }
  }

  async exportAnki() {
    try {
      const { save } = window.__TAURI__.dialog;
      const path = await save({
        defaultPath: 'ready_reader_anki_cards.txt',
        filters: [{ name: 'Anki TSV', extensions: ['txt'] }]
      });
      if (!path) return; // user cancelled
      await api.exportAnkiToFile(path);
      this.showToast('Anki 牌组导出文件已保存', 'success');
    } catch (e) {
      this.showToast(`导出失败: ${e.message}`, 'error');
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

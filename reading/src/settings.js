import { api } from './api.js';

export class SettingsManager {
  constructor(modalElement, showToast) {
    this.modal = modalElement;
    this.showToast = showToast;

    this.providerSelect = this.modal.querySelector('#settings_provider');
    this.apiKeyInput = this.modal.querySelector('#settings_api_key');
    this.baseUrlInput = this.modal.querySelector('#settings_base_url');
    this.modelNameInput = this.modal.querySelector('#settings_model_name');
    this.temperatureInput = this.modal.querySelector('#settings_temperature');
    this.mockModeCheckbox = this.modal.querySelector('#settings_mock_mode');
    this.saveBtn = this.modal.querySelector('#btn_save_settings');
    this.closeBtn = this.modal.querySelector('.btn-close-settings');

    this.bindEvents();
  }

  bindEvents() {
    this.closeBtn.addEventListener('click', () => this.close());
    this.modal.addEventListener('click', (e) => {
      if (e.target === this.modal) this.close();
    });

    this.saveBtn.addEventListener('click', () => this.save());

    this.providerSelect.addEventListener('change', () => {
      const p = this.providerSelect.value;
      if (p === 'deepseek') {
        this.baseUrlInput.placeholder = 'https://api.deepseek.com/v1';
        this.modelNameInput.value = 'deepseek-chat';
      } else if (p === 'gemini') {
        this.baseUrlInput.placeholder = 'https://generativelanguage.googleapis.com/v1beta/openai';
        this.modelNameInput.value = 'gemini-1.5-flash';
      } else if (p === 'claude') {
        this.baseUrlInput.placeholder = 'https://api.anthropic.com/v1';
        this.modelNameInput.value = 'claude-3-5-sonnet';
      } else if (p === 'minimax') {
        this.baseUrlInput.placeholder = 'https://api.minimaxi.com/anthropic/v1';
        this.modelNameInput.value = 'MiniMax-M3';
      } else if (p === 'openai') {
        this.baseUrlInput.placeholder = 'https://api.openai.com/v1';
        this.modelNameInput.value = 'gpt-4o-mini';
      } else if (p === 'mock') {
        this.mockModeCheckbox.checked = true;
      }
    });
  }

  async open() {
    this.modal.classList.add('open');
    try {
      const s = await api.getSettings();
      this.providerSelect.value = s.provider || 'mock';
      this.apiKeyInput.value = s.api_key || '';
      this.baseUrlInput.value = s.base_url || '';
      this.modelNameInput.value = s.model_name || 'gpt-4o-mini';
      this.temperatureInput.value = s.temperature !== undefined ? s.temperature : 0.2;
      this.mockModeCheckbox.checked = !!s.mock_mode;
    } catch (e) {
      this.showToast('读取配置失败', 'error');
    }
  }

  close() {
    this.modal.classList.remove('open');
  }

  async save() {
    const payload = {
      provider: this.providerSelect.value,
      api_key: this.apiKeyInput.value.trim(),
      base_url: this.baseUrlInput.value.trim(),
      model_name: this.modelNameInput.value.trim(),
      temperature: parseFloat(this.temperatureInput.value) || 0.2,
      mock_mode: this.mockModeCheckbox.checked
    };

    try {
      await api.updateSettings(payload);
      this.showToast('配置已保存！', 'success');
      this.close();
    } catch (err) {
      this.showToast(`保存失败: ${err.message}`, 'error');
    }
  }
}

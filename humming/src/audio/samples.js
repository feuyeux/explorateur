/**
 * 内置测试人声哼唱音频样本生成器 (Humming Audio Samples Generator)
 * 使用人声共振峰滤波 (Vocal Formants) + 轻微自然微颤音 (Vibrato) 合成逼真的人声哼唱音频
 * 支持《小星星》、《两只老虎》、《欢乐颂》、《生日快乐》，供用户无需麦克风秒级体验全流程
 */

export class SampleAudioFactory {
  static getPresetList() {
    return [
      { id: 'twinkle', title: '小星星 (Twinkle Twinkle)', desc: '1 1 5 5 6 6 5 - 4 4 3 3 2 2 1 -', bpm: 100, key: 'C Major' },
      { id: 'two_tigers', title: '两只老虎 (Two Tigers)', desc: '1 2 3 1 1 2 3 1 3 4 5 - 3 4 5 -', bpm: 108, key: 'C Major' },
      { id: 'ode_to_joy', title: '欢乐颂 (Ode to Joy)', desc: '3 3 4 5 5 4 3 2 1 1 2 3 3. 2 2 -', bpm: 104, key: 'C Major' },
      { id: 'happy_birthday', title: '生日快乐 (Happy Birthday)', desc: '5. 5 6 5 1* 7 - 5. 5 6 5 2* 1* -', bpm: 95, key: 'C Major' }
    ];
  }

  /**
   * 生成预置歌曲的 PCM Float32Array 音频（包含人声共振峰、微弱气息声、滑音过渡）
   * @param {string} presetId
   * @param {number} [sampleRate=16000]
   * @returns {Object} { samples: Float32Array, sampleRate, title, expectedNotes }
   */
  static generateHummingAudio(presetId, sampleRate = 16000) {
    let melody = [];
    let bpm = 100;
    let title = '小星星';

    if (presetId === 'two_tigers') {
      title = '两只老虎';
      bpm = 108;
      // 1 2 3 1 | 1 2 3 1 | 3 4 5 - | 3 4 5 -
      melody = [
        { midi: 60, beats: 1 }, { midi: 62, beats: 1 }, { midi: 64, beats: 1 }, { midi: 60, beats: 1 },
        { midi: 60, beats: 1 }, { midi: 62, beats: 1 }, { midi: 64, beats: 1 }, { midi: 60, beats: 1 },
        { midi: 64, beats: 1 }, { midi: 65, beats: 1 }, { midi: 67, beats: 2 },
        { midi: 64, beats: 1 }, { midi: 65, beats: 1 }, { midi: 67, beats: 2 }
      ];
    } else if (presetId === 'ode_to_joy') {
      title = '欢乐颂';
      bpm = 104;
      // 3 3 4 5 | 5 4 3 2 | 1 1 2 3 | 3. 2 2 -
      melody = [
        { midi: 64, beats: 1 }, { midi: 64, beats: 1 }, { midi: 65, beats: 1 }, { midi: 67, beats: 1 },
        { midi: 67, beats: 1 }, { midi: 65, beats: 1 }, { midi: 64, beats: 1 }, { midi: 62, beats: 1 },
        { midi: 60, beats: 1 }, { midi: 60, beats: 1 }, { midi: 62, beats: 1 }, { midi: 64, beats: 1 },
        { midi: 64, beats: 1.5 }, { midi: 62, beats: 0.5 }, { midi: 62, beats: 2 }
      ];
    } else if (presetId === 'happy_birthday') {
      title = '生日快乐';
      bpm = 95;
      // 5. 5 6 5 | 1* 7 - - | 5. 5 6 5 | 2* 1* - -
      melody = [
        { midi: 55, beats: 0.75 }, { midi: 55, beats: 0.25 }, { midi: 57, beats: 1 }, { midi: 55, beats: 1 },
        { midi: 60, beats: 1 }, { midi: 59, beats: 2 },
        { midi: 55, beats: 0.75 }, { midi: 55, beats: 0.25 }, { midi: 57, beats: 1 }, { midi: 55, beats: 1 },
        { midi: 62, beats: 1 }, { midi: 60, beats: 2 }
      ];
    } else {
      // 默认小星星
      title = '小星星';
      bpm = 100;
      // 1 1 5 5 | 6 6 5 - | 4 4 3 3 | 2 2 1 -
      melody = [
        { midi: 60, beats: 1 }, { midi: 60, beats: 1 }, { midi: 67, beats: 1 }, { midi: 67, beats: 1 },
        { midi: 69, beats: 1 }, { midi: 69, beats: 1 }, { midi: 67, beats: 2 },
        { midi: 65, beats: 1 }, { midi: 65, beats: 1 }, { midi: 64, beats: 1 }, { midi: 64, beats: 1 },
        { midi: 62, beats: 1 }, { midi: 62, beats: 1 }, { midi: 60, beats: 2 }
      ];
    }

    const secondsPerBeat = 60 / bpm;
    // 计算总时长 + 前后留白 0.3s
    let totalSeconds = 0.4;
    melody.forEach(n => { totalSeconds += n.beats * secondsPerBeat; });
    totalSeconds += 0.4;

    const totalSamples = Math.floor(totalSeconds * sampleRate);
    const buffer = new Float32Array(totalSamples);

    let currentSec = 0.3;
    let prevFreq = 440 * Math.pow(2, (melody[0].midi - 69) / 12);

    for (let noteIdx = 0; noteIdx < melody.length; noteIdx++) {
      const item = melody[noteIdx];
      const targetFreq = 440 * Math.pow(2, (item.midi - 69) / 12);
      const noteDuration = item.beats * secondsPerBeat;
      // 发声时长 (85% 发声, 15% 换气停顿)
      const voiceDuration = noteDuration * 0.88;
      const restDuration = noteDuration * 0.12;

      const startSample = Math.floor(currentSec * sampleRate);
      const voiceSamples = Math.floor(voiceDuration * sampleRate);

      let phase = 0;

      for (let s = 0; s < voiceSamples; s++) {
        const t = s / sampleRate;
        const progress = s / voiceSamples;

        // 1. 滑音平滑 (Glissando from previous note, 前 40ms)
        let noteFreq = targetFreq;
        if (s < 0.04 * sampleRate && noteIdx > 0) {
          const glideRatio = s / (0.04 * sampleRate);
          noteFreq = prevFreq + (targetFreq - prevFreq) * glideRatio;
        }

        // 2. 人声微颤音 (Vibrato 5.5Hz, 深度约 25 音分)
        const vibrato = Math.sin(2 * Math.PI * 5.5 * t) * (targetFreq * 0.015);
        const actualFreq = noteFreq + vibrato;

        // 3. 产生基频与前3个泛音
        phase += (2 * Math.PI * actualFreq) / sampleRate;
        // 人声闭合哼鸣 (/m/ 或 /u/) 特征：基频极强，二次泛音中等，高次泛音急剧衰减
        const fundamental = Math.sin(phase);
        const h2 = 0.35 * Math.sin(phase * 2);
        const h3 = 0.12 * Math.sin(phase * 3);
        const rawWave = fundamental + h2 + h3;

        // 4. 人声音量包络 (柔和 Attack 25ms, 自然衰减 Decay, 结尾 Release 30ms)
        let env = 1.0;
        if (t < 0.03) {
          env = t / 0.03;
        } else if (progress > 0.85) {
          env = (1.0 - progress) / 0.15;
        }

        // 5. 微弱人声气息底噪 (Breath noise)
        const breathNoise = (Math.random() * 2 - 1) * 0.018;

        const sampleVal = (rawWave * 0.75 + breathNoise) * env;
        if (startSample + s < totalSamples) {
          buffer[startSample + s] = Math.max(-0.95, Math.min(0.95, sampleVal));
        }
      }

      prevFreq = targetFreq;
      currentSec += noteDuration;
    }

    return {
      samples: buffer,
      sampleRate: sampleRate,
      bpm: bpm,
      title: title,
      expectedNotes: melody
    };
  }
}

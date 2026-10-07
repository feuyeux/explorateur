/**
 * Basic Pitch vendor bundle 入口 (built by scripts/build_vendor.mjs → js/vendor/basic-pitch.bundle.js)
 * 暴露 window.BasicPitchLib，供 basic_pitch_engine.js 以 <script> 方式懒加载。
 */
import * as tf from '@tensorflow/tfjs';
import { BasicPitch, addPitchBendsToNoteEvents, noteFramesToTime, outputToNotesPoly } from '@spotify/basic-pitch';

window.BasicPitchLib = {
  BasicPitch,
  addPitchBendsToNoteEvents,
  noteFramesToTime,
  outputToNotesPoly,
  tf
};

const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createUI } = require('./test_app_render.js');

function voiceUI(enabled, options = {}) {
  const created = [];
  const revoked = [];
  const tracks = [];
  class Recorder {
    static isTypeSupported(type) { return type === 'audio/mp4'; }
    constructor() { this.state = 'inactive'; }
    start() {
      this.state = 'recording';
      if (options.failStart) throw new Error('start failed');
    }
    stop() {
      this.state = 'inactive';
      this.ondataavailable({ data: new Blob(['recorded fixture'], { type: 'audio/mp4' }) });
      this.onstop();
    }
  }
  class Form {
    constructor() { this.fields = new Map(); }
    append(name, value) { this.fields.set(name, value); }
  }
  const MediaRecorderImpl = options.Recorder || Recorder;
  const ui = createUI({
    Blob,
    FormData: Form,
    MediaRecorder: MediaRecorderImpl,
    navigator: { mediaDevices: { getUserMedia: options.getUserMedia || (async () => {
      const track = { stopped: false, stopCount: 0, stop() { this.stopped = true; this.stopCount += 1; } };
      tracks.push(track);
      return { getTracks: () => [track] };
    }) } },
    window: { location: { protocol: 'https:', host: 'example.test', search: enabled ? '?debug_audio=1' : '' }, MediaRecorder: MediaRecorderImpl },
    URL: {
      createObjectURL(blob) { created.push(blob); return `blob:fixture-${created.length}`; },
      revokeObjectURL(url) { revoked.push(url); }
    }
  });
  async function record() {
    const mic = ui.elements.get('mic-button');
    mic.fire('pointerdown'); mic.fire('pointerup'); await ui.flush();
    mic.fire('pointerdown'); mic.fire('pointerup'); await ui.flush();
    return ui.pendingRequests.filter(request => request.url === '/api/v1/command/voice').at(-1);
  }
  return { ...ui, created, revoked, tracks, record, Recorder: MediaRecorderImpl };
}

test('debug preview uses the exact uploaded blob and releases it on replacement or session change', async () => {
  const ui = voiceUI(true);
  await ui.flush();
  ui.sendState({});
  const request = await ui.record();
  const get = id => ui.elements.get(id);
  assert.equal(ui.created[0], request.init.body.fields.get('audio'));
  assert.equal(ui.created[0].type, 'audio/mp4');
  assert.equal(get('voice-audio-player').src, get('voice-audio-download').href);
  assert.equal(get('voice-audio-debug').hidden, false);
  assert.match(get('voice-audio-download').download, /\.m4a$/);
  await ui.record();
  assert.deepEqual(ui.revoked, ['blob:fixture-1']);
  ui.sendState({ active_session_id: 'another-visitor' });
  assert.equal(get('voice-audio-debug').hidden, true);
  assert.deepEqual(ui.revoked, ['blob:fixture-1', 'blob:fixture-2']);
});

test('normal recording does not retain a debug audio URL', async () => {
  const ui = voiceUI(false);
  await ui.flush();
  await ui.record();
  assert.equal(ui.created.length, 0);
  assert.equal(ui.revoked.length, 0);
  assert.notEqual(ui.elements.get('voice-audio-debug').hidden, false);
});

test('voice 422 and 503 responses finish transcription with controlled guidance', async () => {
  const emptyVoice = voiceUI(false);
  await emptyVoice.flush();
  emptyVoice.sendState({});
  const emptyRequest = await emptyVoice.record();
  emptyRequest.resolve({ ok: false, status: 422, json: async () => ({ detail: 'ไม่พบข้อความจากเสียง' }) });
  await emptyVoice.flush();
  assert.equal(
    emptyVoice.elements.get('transcript-preview').textContent,
    'ไม่พบเสียงพูดที่แปลงเป็นข้อความได้ กรุณาพูดใกล้ไมค์แล้วลองใหม่'
  );

  const unavailableVoice = voiceUI(false);
  await unavailableVoice.flush();
  unavailableVoice.sendState({});
  const unavailableRequest = await unavailableVoice.record();
  unavailableRequest.resolve({ ok: false, status: 503, json: async () => ({ detail: 'secret provider exception' }) });
  await unavailableVoice.flush();
  assert.equal(
    unavailableVoice.elements.get('transcript-preview').textContent,
    'บริการรับหรือแปลงคำสั่งยังไม่พร้อม กรุณาลองใหม่ภายหลัง'
  );
  assert.notEqual(unavailableVoice.elements.get('transcript-preview').textContent, 'secret provider exception');

  const offlineVoice = voiceUI(false);
  await offlineVoice.flush();
  offlineVoice.sendState({});
  const offlineRequest = await offlineVoice.record();
  offlineRequest.reject(new Error('offline'));
  await offlineVoice.flush();
  assert.equal(
    offlineVoice.elements.get('transcript-preview').textContent,
    'ส่งเสียงไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ'
  );
});

test('tap and hold gestures stop once, support keyboard, and capture release outside the button', async () => {
  const tap = voiceUI(false);
  await tap.flush();
  tap.sendState({});
  const mic = tap.elements.get('mic-button');
  mic.fire('pointerdown', { pointerId: 7 });
  mic.fire('pointerup', { pointerId: 7 });
  await tap.flush();
  assert.equal(mic.attributes.get('aria-pressed'), 'true');
  mic.fire('click', { detail: 1 });
  assert.equal(mic.attributes.get('aria-pressed'), 'true');
  mic.fire('pointerdown', { pointerId: 8 });
  mic.fire('pointerup', { pointerId: 8 });
  await tap.flush();
  assert.deepEqual(mic.pointerCaptures, [7, 8]);
  assert.equal(tap.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 1);

  const hold = voiceUI(false);
  await hold.flush();
  hold.sendState({});
  const holdMic = hold.elements.get('mic-button');
  holdMic.fire('pointerdown', { pointerId: 3 });
  hold.scheduled.at(-1)();
  await hold.flush();
  assert.equal(holdMic.attributes.get('aria-pressed'), 'true');
  holdMic.fire('pointerup', { pointerId: 3 });
  await hold.flush();
  assert.equal(hold.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 1);

  const keyboard = voiceUI(false);
  await keyboard.flush();
  keyboard.sendState({});
  const keyboardMic = keyboard.elements.get('mic-button');
  keyboardMic.fire('click', { detail: 0 });
  await keyboard.flush();
  assert.equal(keyboardMic.attributes.get('aria-pressed'), 'true');
  keyboardMic.fire('click', { detail: 0 });
  await keyboard.flush();
  assert.equal(keyboard.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 1);
});

test('permission races, pointer cancel, and ownership loss discard audio and stop tracks', async () => {
  let resolvePermission;
  const track = { stopped: false, stopCount: 0, stop() { this.stopped = true; this.stopCount += 1; } };
  const pending = voiceUI(false, {
    getUserMedia: () => new Promise(resolve => { resolvePermission = resolve; })
  });
  await pending.flush();
  pending.sendState({});
  const mic = pending.elements.get('mic-button');
  mic.fire('pointerdown'); mic.fire('pointerup');
  await pending.flush();
  assert.match(mic.getAttribute?.('aria-label') || mic.attributes.get('aria-label'), /กำลังรอสิทธิ์/);
  mic.fire('pointerdown'); mic.fire('pointerup');
  assert.equal(mic.attributes.get('aria-pressed'), 'false');
  resolvePermission({ getTracks: () => [track] });
  await pending.flush();
  assert.equal(track.stopped, true);
  assert.equal(track.stopCount, 1);
  assert.equal(pending.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 0);

  const recording = voiceUI(false);
  await recording.flush();
  recording.sendState({});
  const recordingMic = recording.elements.get('mic-button');
  recordingMic.fire('pointerdown'); recordingMic.fire('pointerup');
  await recording.flush();
  const recordingTrack = recording.tracks[0];
  recordingMic.fire('pointercancel');
  await recording.flush();
  assert.equal(recordingTrack.stopped, true);
  assert.equal(recording.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 0);

  let resolveOwnerPermission;
  const ownerTrack = { stopped: false, stopCount: 0, stop() { this.stopped = true; this.stopCount += 1; } };
  const ownerChange = voiceUI(false, {
    getUserMedia: () => new Promise(resolve => { resolveOwnerPermission = resolve; })
  });
  await ownerChange.flush();
  ownerChange.sendState({});
  const ownerMic = ownerChange.elements.get('mic-button');
  ownerMic.fire('pointerdown'); ownerMic.fire('pointerup');
  await ownerChange.flush();
  ownerChange.sendState({ active_session_id: 'visitor-2', lock_status: 'LOCKED' });
  resolveOwnerPermission({ getTracks: () => [ownerTrack] });
  await ownerChange.flush();
  assert.equal(ownerTrack.stopped, true);
  assert.equal(ownerTrack.stopCount, 1);
  assert.equal(ownerChange.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 0);

  let resolveHoldPermission;
  const holdTrack = { stopped: false, stopCount: 0, stop() { this.stopped = true; this.stopCount += 1; } };
  const holdCancel = voiceUI(false, {
    getUserMedia: () => new Promise(resolve => { resolveHoldPermission = resolve; })
  });
  await holdCancel.flush();
  holdCancel.sendState({});
  const holdMic = holdCancel.elements.get('mic-button');
  holdMic.fire('pointerdown', { pointerId: 9 });
  holdCancel.scheduled.at(-1)();
  await holdCancel.flush();
  holdMic.fire('pointerup', { pointerId: 9 });
  resolveHoldPermission({ getTracks: () => [holdTrack] });
  await holdCancel.flush();
  assert.equal(holdTrack.stopped, true);
  assert.equal(holdTrack.stopCount, 1);
  assert.equal(holdCancel.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 0);

  const ownerRecording = voiceUI(false);
  await ownerRecording.flush();
  ownerRecording.sendState({});
  const ownerRecordingMic = ownerRecording.elements.get('mic-button');
  ownerRecordingMic.fire('pointerdown'); ownerRecordingMic.fire('pointerup');
  await ownerRecording.flush();
  const activeTrack = ownerRecording.tracks[0];
  ownerRecording.sendState({ active_session_id: 'visitor-2', lock_status: 'LOCKED' });
  await ownerRecording.flush();
  assert.equal(activeTrack.stopped, true);
  assert.equal(ownerRecording.pendingRequests.filter(request => request.url === '/api/v1/command/voice').length, 0);
});

test('permission denial and recorder construction failures leave no active mic or stream', async () => {
  const denied = voiceUI(false, { getUserMedia: async () => { throw new Error('denied'); } });
  await denied.flush();
  denied.sendState({});
  const deniedMic = denied.elements.get('mic-button');
  deniedMic.fire('click', { detail: 0 });
  await denied.flush();
  assert.equal(deniedMic.attributes.get('aria-pressed'), 'false');
  assert.match(denied.elements.get('transcript-preview').textContent, /เปิดไมโครโฟนไม่สำเร็จ/);

  class BrokenRecorder {
    static isTypeSupported() { return false; }
    constructor() { throw new Error('constructor failed'); }
  }
  const brokenTrack = { stopped: false, stop() { this.stopped = true; } };
  const broken = voiceUI(false, {
    Recorder: BrokenRecorder,
    getUserMedia: async () => ({ getTracks: () => [brokenTrack] })
  });
  await broken.flush();
  broken.sendState({});
  broken.elements.get('mic-button').fire('click', { detail: 0 });
  await broken.flush();
  assert.equal(brokenTrack.stopped, true);
  assert.equal(broken.elements.get('mic-button').attributes.get('aria-pressed'), 'false');

  const startTrack = { stopped: false, stop() { this.stopped = true; } };
  const startFailure = voiceUI(false, {
    failStart: true,
    getUserMedia: async () => ({ getTracks: () => [startTrack] })
  });
  await startFailure.flush();
  startFailure.sendState({});
  startFailure.elements.get('mic-button').fire('click', { detail: 0 });
  await startFailure.flush();
  assert.equal(startTrack.stopped, true);
  assert.equal(startFailure.elements.get('mic-button').attributes.get('aria-pressed'), 'false');
});

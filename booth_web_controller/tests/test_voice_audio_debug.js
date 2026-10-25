const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createUI } = require('./test_app_render.js');

function voiceUI(enabled) {
  const created = [];
  const revoked = [];
  class Recorder {
    static isTypeSupported(type) { return type === 'audio/mp4'; }
    start() {}
    stop() {
      this.ondataavailable({ data: new Blob(['recorded fixture'], { type: 'audio/mp4' }) });
      this.onstop();
    }
  }
  class Form {
    constructor() { this.fields = new Map(); }
    append(name, value) { this.fields.set(name, value); }
  }
  const ui = createUI({
    Blob,
    FormData: Form,
    MediaRecorder: Recorder,
    navigator: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } },
    window: { location: { protocol: 'https:', host: 'example.test', search: enabled ? '?debug_audio=1' : '' }, MediaRecorder: Recorder },
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
  return { ...ui, created, revoked, record };
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

const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

class Element {
  constructor(dataset = {}) { Object.assign(this, { dataset, textContent: '', disabled: false, scrollTop: 0, clientHeight: 0, scrollHeight: 0, listeners: {}, children: [] }); }
  addEventListener(type, callback) { this.listeners[type] = callback; }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  click() { if (!this.disabled) return this.listeners.click?.(); }
}
const settle = () => new Promise(resolve => setImmediate(resolve));
function state(mode = 'automatic') {
  const node = { status: 'running', pid: 123, external_pids: [], started_at: 100, restart_count: 0, exit_code: null, last_error: '', logs: [] };
  return { checked_at: 100, mock: false, processes: { enabled: true, mode, problem: '', nodes: {
    intent: { ...node }, subtitle: { ...node, pid: 124 }
  } }, ros: { intent: 'responding', subtitle: 'timeout', robot_fresh: false }, tailscale: { status: 'unknown' }, vr: { connections: 0 },
  audio: { enabled: false, ffmpeg_available: true } };
}
function ui() {
  const elements = new Map(), buttons = [], calls = [], intervals = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  for (const name of ['intent', 'subtitle']) for (const action of ['start', 'stop', 'restart', 'kill']) buttons.push(new Element({ node: name, nodeAction: action }));
  for (const mode of ['automatic', 'manual']) buttons.push(new Element({ agentMode: mode }));
  const refresh = get('staff-system-refresh'); refresh.id = 'staff-system-refresh'; buttons.push(refresh);
  let response = state(), queue = [], unauthorized = 0, subtitleChanges = 0, sequence = 0;
  const context = { window: {}, document: { getElementById: get, createTextNode: text => ({ textContent: text }), createElement: () => new Element(), querySelectorAll: () => buttons },
    navigator: { clipboard: { writeText: async () => {} } },
    AbortController, setTimeout, clearTimeout, Date,
    setInterval(callback) { const id = ++sequence; intervals.set(id, callback); return id; },
    clearInterval(id) { intervals.delete(id); },
    async fetch(url, options) {
      calls.push({ url, options });
      if (queue.length) return queue.shift();
      return { ok: true, status: 200, json: async () => response };
    }
  };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/staff_system.js'), 'utf8'), context);
  const panel = context.window.StaffSystem.create({ onUnauthorized() { unauthorized++; panel.stop(); }, onSubtitleChange() { subtitleChanges++; } });
  return { panel, get, calls, buttons, intervals,
    button: (name, action) => buttons.find(b => b.dataset.node === name && b.dataset.nodeAction === action),
    setState(value) { response = value; }, queue(value) { queue.push(value); },
    get unauthorized() { return unauthorized; }, get subtitleChanges() { return subtitleChanges; }
  };
}

test('system inspection waits for PIN and keeps process alive distinct from ROS response', async () => {
  const view = ui();
  assert.equal(view.calls.length, 0);
  view.panel.start('staff-pin'); await settle();
  assert.equal(view.calls[0].options.headers['X-Staff-Pin'], 'staff-pin');
  assert.match(view.get('staff-subtitle-process').textContent, /Process ทำงานอยู่/);
  assert.match(view.get('staff-subtitle-rpc').textContent, /ไม่ตอบภายในเวลา/);
  assert.match(view.get('staff-health-vr').textContent, /0 การเชื่อมต่อ/);
  assert.match(view.get('staff-health-robot').textContent, /ยังไม่มีสถานะสด/);
  view.panel.stop();
});

test('audio controls work in Mock without enabling ROS process management', async () => {
  const view = ui(), mock = state();
  mock.mock = true; mock.processes.enabled = false;
  view.setState(mock);
  assert.equal(view.get('staff-audio-enable').disabled, true);
  view.panel.start('pin'); await settle();
  assert.equal(view.get('staff-audio-enable').disabled, false);
  assert.equal(view.get('staff-audio-disable').disabled, true);
  assert.match(view.get('staff-audio-ready').textContent, /พร้อมใช้งาน/);
  mock.audio.enabled = true; view.setState(mock);
  view.get('staff-audio-enable').click(); view.get('staff-audio-enable').click();
  await settle();
  const posts = view.calls.filter(c => c.options.method === 'POST');
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, '/api/v1/staff/system/audio');
  assert.deepEqual(JSON.parse(posts[0].options.body), { enabled: true });
  assert.match(view.get('staff-audio-current').textContent, /เปิด/);
  view.panel.stop();
  assert.equal(view.get('staff-audio-disable').disabled, true);
});

test('missing ffmpeg prevents enabling and a failed write keeps the confirmed mode', async () => {
  const view = ui(), data = state();
  data.audio.ffmpeg_available = false; view.setState(data);
  view.panel.start('pin'); await settle();
  assert.equal(view.get('staff-audio-enable').disabled, true);
  data.audio.ffmpeg_available = true; view.setState(data);
  await [...view.intervals.values()][0]();
  view.queue({ ok: false, status: 409, json: async () => ({ detail: 'ไม่พบ ffmpeg' }) });
  view.get('staff-audio-enable').click(); await settle();
  assert.match(view.get('staff-audio-feedback').textContent, /ไม่พบ ffmpeg/);
  assert.match(view.get('staff-audio-current').textContent, /ปิด/);
  assert.equal(view.get('staff-audio-enable').disabled, false);
  view.panel.stop();
});

test('one click produces one control request while pending; failures re-enable controls', async () => {
  const view = ui(); view.panel.start('pin'); await settle();
  let resolve;
  view.queue(new Promise(done => { resolve = done; }));
  view.button('intent', 'restart').click();
  view.button('intent', 'restart').click();
  assert.equal(view.calls.filter(c => c.options.method === 'POST').length, 1);
  assert.equal(view.button('subtitle', 'kill').disabled, true);
  resolve({ ok: false, status: 409, json: async () => ({ detail: 'Manual mode is active' }) });
  await settle();
  assert.match(view.get('staff-system-feedback').textContent, /Manual mode is active/);
  assert.equal(view.button('intent', 'restart').disabled, false);
  view.panel.stop();
});

test('Manual and external nodes cannot be started or killed through disabled controls', async () => {
  const view = ui(), manual = state('manual');
  manual.processes.nodes.intent.status = 'stopped'; manual.processes.nodes.intent.pid = null;
  manual.processes.nodes.subtitle.status = 'external'; manual.processes.nodes.subtitle.external_pids = [999];
  view.setState(manual); view.panel.start('pin'); await settle();
  assert.equal(view.button('intent', 'start').disabled, true);
  assert.equal(view.button('subtitle', 'kill').disabled, true);
  assert.match(view.get('staff-subtitle-detail').textContent, /999/);
  view.panel.stop();
});

test('a late GET does not overwrite a newer restart response', async () => {
  const view = ui(); view.panel.start('pin'); await settle();
  let resolve;
  view.queue(new Promise(done => { resolve = done; }));
  const poll = [...view.intervals.values()][0]();
  const newer = state(); newer.processes.nodes.intent.pid = 456;
  view.setState(newer);
  view.button('intent', 'restart').click(); await settle();
  resolve({ ok: true, status: 200, json: async () => state() });
  await poll;
  assert.match(view.get('staff-intent-process').textContent, /456/);
  view.panel.stop();
});

test('clearing authorization stops polling and ignores an old response', async () => {
  const view = ui(); view.panel.start('pin'); await settle();
  view.queue({ ok: false, status: 401, json: async () => ({ detail: 'Invalid PIN' }) });
  await [...view.intervals.values()][0]();
  assert.equal(view.unauthorized, 1);
  assert.equal(view.intervals.size, 0);
  let resolve;
  view.queue(new Promise(done => { resolve = done; }));
  view.panel.start('new-pin');
  view.panel.stop();
  const previous = view.get('staff-intent-process').textContent;
  const newer = state(); newer.processes.nodes.intent.pid = 555;
  resolve({ ok: true, status: 200, json: async () => newer });
  await settle();
  assert.equal(view.get('staff-intent-process').textContent, previous);
});

test('subtitle restart invalidates the old mode and log content stays literal text', async () => {
  const view = ui(), snapshot = state();
  snapshot.processes.nodes.subtitle.logs = [{ at: 100, text: '<img src=x onerror=bad()>' }];
  view.setState(snapshot); view.panel.start('pin'); await settle();
  assert.match(view.get('staff-subtitle-logs').textContent, /<img/);
  view.button('subtitle', 'restart').click(); await settle();
  assert.equal(view.subtitleChanges, 1);
  view.panel.stop();
});

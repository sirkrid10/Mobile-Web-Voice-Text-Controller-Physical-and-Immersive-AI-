const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag;
    this.textContent = '';
    this.innerHTML = '';
    this.className = '';
    this.value = '';
    this.children = [];
    this.style = {};
    this.listeners = new Map();
    this.attributes = new Map();
    this.pointerCaptures = [];
    this.classList = {
      add: name => { this.className += ` ${name}`; },
      remove: name => { this.className = this.className.replace(name, '').trim(); }
    };
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  setAttribute(name, value) { this.attributes.set(name, value); }
  setPointerCapture(pointerId) { this.pointerCaptures.push(pointerId); }

  appendChild(child) {
    this.children.push(child);
  }

  set innerHTML(value) {
    this._innerHTML = value;
    if (value === '') this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  fire(type, event = {}) {
    return this.listeners.get(type)?.({ preventDefault() {}, ...event });
  }
}

function createUI(overrides = {}) {
  const initialStateFetch = overrides.initialStateFetch;
  const elements = new Map();
  const sockets = [];
  const pendingRequests = [];
  const scheduled = [];
  const storageWrites = [];
  const storageRemovals = [];
  const initialState = {
    robot_state: 'IDLE', heard_text: '', current_goal: 'start', llm_reason: 'พร้อมนำทาง',
    is_busy: false, lock_status: 'LOCKED', active_session_id: 'visitor-1',
    inactivity_remaining_sec: 50, timer_paused_for_navigation: false,
    show_timeout_warning: false, auto_return_enabled: true, auto_return_delay_sec: 5,
    obstacle_detected: false, latest_intent: null, latest_action: null,
    locations: [
      { id: 'A', label: 'จุด A', prompt: 'ไปจุด A' },
      { id: 'B', label: 'จุด B', prompt: 'ไปจุด B' },
      { id: 'C', label: 'จุด C', prompt: 'ไปจุด C' },
      { id: 'start', label: 'กลับจุดเริ่มต้น (จุด A)', prompt: 'กลับจุดเริ่มต้น' },
      { id: 'wait', label: 'ส่งคำขอรอ (ยังไม่รองรับ)', prompt: 'หยุดรอตรงนี้ก่อน' }
    ]
  };

  const context = {
    document: {
      getElementById(id) {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
      },
      createElement(tag) { return new Element(tag); }
    },
    localStorage: { getItem: () => 'visitor-1', setItem() {} },
    sessionStorage: {
      getItem: () => 'test-token',
      setItem(key, value) { storageWrites.push([key, value]); },
      removeItem(key) { storageRemovals.push(key); }
    },
    crypto: { randomUUID: () => 'visitor-1' },
    window: { location: { protocol: 'http:', host: 'localhost' }, MediaRecorder: null },
    navigator: { mediaDevices: {} },
    WebSocket: class {
      constructor(url) { this.url = url; sockets.push(this); }
      close() {}
    },
    FormData: class { append() {} },
    fetch(url, init = {}) {
      if (url === '/api/v1/state') {
        if (initialStateFetch) return initialStateFetch();
        return Promise.resolve({ ok: true, json: async () => initialState });
      }
      return new Promise((resolve, reject) => pendingRequests.push({ url, init, resolve, reject }));
    },
    setTimeout(callback) { scheduled.push(callback); return scheduled.length; },
    clearTimeout() {},
    alert() {},
    confirm: () => true,
    console: { log() {}, warn() {}, error() {} }
  };

  Object.assign(context, Object.fromEntries(
    Object.entries(overrides).filter(([key]) => key !== 'initialStateFetch')
  ));

  const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.js'), 'utf8');
  vm.runInNewContext(script, context, { filename: 'static/app.js' });

  function sendState(state, socket = sockets.at(-1)) {
    socket.onmessage({ data: JSON.stringify({ ...initialState, ...state }) });
  }

  function flush() {
    return new Promise(resolve => setImmediate(resolve));
  }

  return { elements, sockets, pendingRequests, scheduled, storageWrites, storageRemovals, initialState, sendState, flush };
}

async function main() {
  const ui = createUI();
  const get = id => ui.elements.get(id);
  const socket = ui.sockets[0];
  const locations = ui.initialState.locations;
  assert.equal(get('view-loading').style.display, undefined);
  await ui.flush();
  ui.sendState({});
  assert.equal(get('view-loading').style.display, 'none');
  assert.equal(get('robot-status-card').style.display, 'flex');
  assert.equal(get('view-active').style.display, 'flex');

  for (const robot_state of ['IDLE', 'UNKNOWN', 'NOT_READY', 'NAVIGATING', 'FAILED']) {
    ui.sendState({
      active_session_id: null,
      lock_status: 'AVAILABLE',
      robot_state
    });
    assert.equal(get('view-available').style.display, 'flex');
    assert.equal(get('view-active').style.display, 'none');
    assert.equal(get('robot-status-card').style.display, 'flex');
    assert.equal(get('robot-state-text').textContent, ({
      IDLE: 'พร้อมรับคำสั่ง (Idle)',
      UNKNOWN: 'ยังไม่ทราบสถานะ (Unknown)',
      NOT_READY: 'ยังไม่พร้อม (Not ready)',
      NAVIGATING: 'กำลังนำทาง (Navigating)',
      FAILED: 'เกิดข้อผิดพลาด (Failed)'
    })[robot_state]);
  }

  ui.sendState({ active_session_id: 'visitor-2', lock_status: 'LOCKED', robot_state: 'NAVIGATING' });
  assert.equal(get('view-queue').style.display, 'flex');
  assert.equal(get('view-active').style.display, 'none');
  assert.equal(get('robot-status-card').style.display, 'flex');
  ui.sendState({ active_session_id: 'visitor-1', lock_status: 'LOCKED', robot_state: 'IDLE' });
  assert.equal(get('view-active').style.display, 'flex');
  assert.equal(get('view-queue').style.display, 'none');

  assert.deepEqual(get('chips-container').children.map(button => button.textContent), locations.map(item => item.label));
  assert.ok(get('chips-container').children[3].className.includes('full-width'));
  assert.ok(get('chips-container').children[4].className.includes('full-width'));

  const rejections = [
    ['request_busy', 'กำลังประมวลผลคำสั่งก่อนหน้า'],
    ['robot_busy', 'หุ่นยังไม่ว่าง'],
    ['request_uncertain', 'ยังยืนยันผลคำสั่งก่อนหน้าไม่ได้'],
    ['robot_state_unknown', 'ยังยืนยันสถานะหุ่นไม่ได้'],
    ['robot_not_ready', 'หุ่นยังไม่พร้อมรับคำสั่ง'],
    ['navigation_unavailable', 'ระบบนำทางยังไม่พร้อม']
  ];
  for (const [error_code, label] of rejections) {
    const hostileMessage = '<img src=x onerror=alert(1)>';
    ui.sendState({ latest_intent: {
      status: 'FAILED', request_id: error_code, session_id: 'visitor-1', error_code,
      message: hostileMessage
    } });
    assert.equal(get('intent-result-status').textContent, label);
    assert.equal(get('intent-result-message').textContent, hostileMessage);
    assert.equal(get('intent-result-message').innerHTML, '');
  }

  ui.sendState({ latest_intent: {
    status: 'FAILED', request_id: 'unknown-failure', session_id: 'visitor-1',
    error_code: 'new_code', message: 'รายละเอียดความล้มเหลว'
  } });
  assert.equal(get('intent-result-status').textContent, 'แปลงคำสั่งไม่สำเร็จ');
  assert.equal(get('intent-result-message').textContent, 'รายละเอียดความล้มเหลว');

  for (const [status, label, message] of [
    ['CLARIFY', 'ขอข้อมูลเพิ่มเติม', 'ต้องการไปจุดไหน'],
    ['UNSUPPORTED', 'คำสั่งนี้ยังไม่รองรับ', 'คำขอนี้ยังไม่รองรับ']
  ]) {
    ui.sendState({ latest_intent: { status, request_id: status, session_id: 'visitor-1', message } });
    assert.equal(get('intent-result-status').textContent, label);
    assert.equal(get('intent-result-message').textContent, message);
  }

  ui.sendState({ robot_state: 'IDLE', current_goal: 'start', latest_intent: {
    status: 'NAVIGATE', request_id: 'navigate-only', session_id: 'visitor-1', destination_id: 'B'
  } });
  assert.equal(get('intent-result-status').textContent, 'แปลงคำสั่งเป็นการนำทาง');
  assert.match(get('intent-result-detail').textContent, /ยังไม่ยืนยันว่า Robot รับงาน/);
  assert.equal(get('robot-goal-tag').textContent, '📍 start');

  ui.sendState({ robot_state: 'NOT_READY', latest_intent: null });
  assert.equal(get('robot-state-text').textContent, 'ยังไม่พร้อม (Not ready)');
  ui.sendState({ robot_state: 'UNKNOWN', latest_intent: null });
  assert.equal(get('robot-state-text').textContent, 'ยังไม่ทราบสถานะ (Unknown)');
  ui.sendState({ robot_state: 'STOPPED', latest_intent: null });
  assert.equal(get('robot-state-text').textContent, 'หยุด/ยกเลิกการนำทาง (Stopped)');

  ui.sendState({ latest_intent: {
    status: 'FAILED', request_id: 'thought-separate', session_id: 'visitor-1',
    error_code: 'robot_busy', message: 'หุ่นยังไม่ว่าง'
  }, llm_reason: 'หุ่นยังไม่ว่าง กำลังทำงานเดิม' });
  assert.equal(get('intent-result-status').textContent, 'หุ่นยังไม่ว่าง');
  ui.sendState({ llm_reason: '', latest_intent: {
    status: 'FAILED', request_id: 'thought-separate', session_id: 'visitor-1',
    error_code: 'robot_busy', message: 'หุ่นยังไม่ว่าง'
  } });
  assert.equal(get('robot-reason-text').textContent, '');
  assert.equal(get('intent-result-status').textContent, 'หุ่นยังไม่ว่าง');

  ui.sendState({ latest_intent: {
    status: 'NAVIGATE', request_id: 'wrong-owner', session_id: 'another-visitor', destination_id: 'A'
  } });
  assert.equal(get('intent-result-status').textContent, 'ยังไม่มีผลแปลงคำสั่ง');

  // Chips keep their intended route and ID; Wait remains a text request.
  get('chips-container').children[1].fire('click');
  await ui.flush();
  const chipRequest = ui.pendingRequests.at(-1);
  assert.equal(chipRequest.url, '/api/v1/command/text');
  assert.deepEqual(JSON.parse(chipRequest.init.body), { text: 'ไปจุด B', input_mode: 'chip' });
  chipRequest.resolve({ ok: true, status: 200, json: async () => ({ request_id: 'chip-1', session_id: 'visitor-1' }) });
  await ui.flush();
  assert.equal(get('transcript-preview').textContent, 'ส่งคำสั่งแล้ว: "ไปจุด B"');
  assert.equal(get('intent-result-status').textContent, 'ส่งแล้ว รอผลแปลงคำสั่ง');
  for (const [index, expectedText] of [[3, 'กลับจุดเริ่มต้น'], [4, 'หยุดรอตรงนี้ก่อน']]) {
    get('chips-container').children[index].fire('click');
    await ui.flush();
    const request = ui.pendingRequests.at(-1);
    assert.deepEqual(JSON.parse(request.init.body), { text: expectedText, input_mode: 'chip' });
    request.resolve({ ok: true, status: 200, json: async () => ({
      request_id: `chip-${index}`, session_id: 'visitor-1'
    }) });
    await ui.flush();
  }

  // Rapid requests reconcile a result received before HTTP and ignore the older HTTP response.
  get('text-input-field').value = 'first request';
  get('text-input-form').fire('submit');
  get('text-input-field').value = 'second request';
  get('text-input-form').fire('submit');
  await ui.flush();
  const first = ui.pendingRequests.at(-2);
  const second = ui.pendingRequests.at(-1);
  assert.equal(JSON.parse(first.init.body).text, 'first request');
  assert.equal(JSON.parse(second.init.body).text, 'second request');
  ui.sendState({ latest_intent: {
    status: 'CLARIFY', request_id: 'rapid-2', session_id: 'visitor-1', message: 'ผลคำขอที่สอง'
  } });
  second.resolve({ ok: true, status: 200, json: async () => ({ request_id: 'rapid-2', session_id: 'visitor-1' }) });
  await ui.flush();
  assert.equal(get('intent-result-message').textContent, 'ผลคำขอที่สอง');
  first.resolve({ ok: true, status: 200, json: async () => ({ request_id: 'rapid-1', session_id: 'visitor-1' }) });
  await ui.flush();
  assert.equal(get('intent-result-message').textContent, 'ผลคำขอที่สอง');

  socket.onclose();
  assert.match(get('connection-status').textContent, /ข้อมูลล่าสุดยังไม่ยืนยัน/);
  assert.equal(get('session-countdown').textContent, 'ข้อมูลเวลาล่าสุดยังไม่ยืนยัน');
  assert.equal(get('btn-send-text').disabled, true);
  const reconnect = ui.scheduled.at(-1);
  reconnect();
  assert.equal(ui.sockets.length, 2);
  ui.sockets[1].onopen();
  assert.match(get('connection-status').textContent, /รอสถานะล่าสุด/);
  assert.equal(get('btn-send-text').disabled, true);
  ui.sendState({ robot_state: 'NAVIGATING', latest_intent: {
    status: 'CLARIFY', request_id: 'rapid-2', session_id: 'visitor-1', message: 'ผลหลัง reconnect'
  } });
  assert.equal(get('intent-result-message').textContent, 'ผลหลัง reconnect');
  assert.equal(get('btn-send-text').disabled, false);

  const failedInitialFetch = createUI({ initialStateFetch: () => Promise.reject(new Error('offline')) });
  await failedInitialFetch.flush();
  assert.match(failedInitialFetch.elements.get('connection-status').textContent, /ข้อมูลล่าสุดยังไม่ยืนยัน/);
  assert.equal(failedInitialFetch.elements.get('btn-send-text').disabled, true);

  get('text-input-field').value = 'bad request';
  get('text-input-form').fire('submit');
  await ui.flush();
  const rejectedText = ui.pendingRequests.at(-1);
  rejectedText.resolve({ ok: false, status: 422, json: async () => ({
    detail: [{ loc: ['body', 'text'], msg: '<script>private detail</script>' }]
  }) });
  await ui.flush();
  assert.equal(get('transcript-preview').textContent, 'กรุณาตรวจข้อความคำสั่งแล้วลองใหม่');
  assert.equal(get('intent-result-status').textContent, 'ส่งคำสั่งไม่สำเร็จ');
  assert.notEqual(get('intent-result-message').textContent, '<script>private detail</script>');

  get('btn-claim-session').fire('click');
  await ui.flush();
  ui.pendingRequests.at(-1).resolve({ ok: false, status: 409, json: async () => ({}) });
  await ui.flush();
  assert.match(get('session-feedback').textContent, /มีผู้ถือสิทธิ์/);
  assert.deepEqual(ui.storageWrites, []);

  const disconnect = get('btn-disconnect').fire('click');
  await ui.flush();
  ui.pendingRequests.at(-1).resolve({ ok: false, status: 503, json: async () => ({}) });
  await disconnect;
  assert.match(get('session-feedback').textContent, /จบการใช้งานไม่สำเร็จ/);
  assert.deepEqual(ui.storageRemovals, []);

  get('warning-banner').style.display = 'flex';
  const heartbeat = get('btn-extend-time').fire('click');
  await ui.flush();
  ui.pendingRequests.at(-1).resolve({ ok: false, status: 503, json: async () => ({}) });
  await heartbeat;
  assert.equal(get('warning-banner').style.display, 'flex');
  assert.match(get('session-feedback').textContent, /ต่อเวลาไม่สำเร็จ/);

  get('text-input-field').value = 'offline command';
  get('text-input-form').fire('submit');
  await ui.flush();
  ui.pendingRequests.at(-1).reject(new Error('offline'));
  await ui.flush();
  assert.equal(get('transcript-preview').textContent, 'ส่งคำสั่งไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ');

  get('text-input-field').value = 'late response';
  get('text-input-form').fire('submit');
  await ui.flush();
  const lateResponse = ui.pendingRequests.at(-1);
  ui.sendState({ active_session_id: 'visitor-2', lock_status: 'LOCKED' });
  lateResponse.resolve({ ok: true, status: 200, json: async () => ({ request_id: 'late', session_id: 'visitor-1' }) });
  await ui.flush();
  assert.equal(get('transcript-preview').textContent, 'แตะหนึ่งครั้งเพื่อเริ่มพูด หรือกดค้างไว้ขณะพูด');
  assert.equal(get('session-feedback').textContent, '');

  process.stdout.write('app render fixture passed\n');
}

module.exports = { createUI };

if (require.main === module) {
  main().catch(error => {
    process.stderr.write(`${error.stack || error}\n`);
    process.exitCode = 1;
  });
}

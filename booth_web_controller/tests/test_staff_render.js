const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

class Element {
  constructor() {
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this.style = {};
    this.listeners = new Map();
  }

  addEventListener(type, listener) { this.listeners.set(type, listener); }
  fire(type, event = {}) { return this.listeners.get(type)?.({ preventDefault() {}, ...event }); }
}

function createStaffUI({ storedPin = 'test-pin', authStatus = 200 } = {}) {
  const elements = new Map();
  const intervals = [];
  const alerts = [];
  const requests = [];
  let failStateFetch = false;
  let currentPin = storedPin;
  let currentAuthStatus = authStatus;
  const authResponses = [];
  const configResponses = [];
  const config = { auto_return_enabled: true, inactivity_timeout_sec: 180, auto_return_delay_sec: 12 };
  const state = {
    auto_return_enabled: true,
    auto_return_delay_sec: 5,
    latest_action: null,
    locations: [
      { id: 'A', label: 'จุด A' }, { id: 'B', label: 'จุด B' },
      { id: 'C', label: 'จุด C' }, { id: 'start', label: 'กลับจุดเริ่มต้น (จุด A)' }
    ]
  };
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'staff.html'), 'utf8');
  const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
  const context = {
    document: { getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    } },
    sessionStorage: {
      getItem: () => currentPin,
      setItem(_key, value) { currentPin = value; },
      removeItem() { currentPin = ''; }
    },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      if (url === '/api/v1/state') {
        return failStateFetch
          ? { ok: false, status: 503 }
          : { ok: true, json: async () => state };
      }
      if (url === '/api/v1/staff/config' && options.method === 'GET') {
        const next = authResponses.shift();
        const status = next ? next.status : currentAuthStatus;
        return status === 200
          ? { ok: true, status, json: async () => ({ ...config, ...(next?.body || {}) }) }
          : { ok: false, status };
      }
      if (url === '/api/v1/staff/config' && options.method === 'POST') {
        const next = configResponses.shift();
        const status = next && next.status !== undefined ? next.status : 200;
        return status === 200
          ? { ok: true, status, json: async () => ({ status: 'updated', ...config, ...(next?.body || {}) }) }
          : { ok: false, status };
      }
      return { ok: true, json: async () => ({ status: 'ok' }) };
    },
    setInterval(callback) { intervals.push(callback); },
    alert(message) { alerts.push(message); },
    console: { error() {} }
  };
  vm.runInNewContext(script, context, { filename: 'static/staff.html' });
  return {
    elements, intervals, alerts, requests,
    setFailStateFetch(value) { failStateFetch = value; },
    updateState(value) { Object.assign(state, value); },
    setAuthStatus(value) { currentAuthStatus = value; },
    queueAuthResponse(value) { authResponses.push(value); },
    queueConfigResponse(value) { configResponses.push(value); },
    getStoredPin() { return currentPin; }
  };
}

test('staff dashboard labels a failed state poll as stale without disabling emergency stop', async () => {
  const ui = createStaffUI();
  await new Promise(resolve => setImmediate(resolve));
  const status = ui.elements.get('staff-data-status');
  const stop = ui.elements.get('btn-emergency-stop');
  assert.equal(status.textContent, 'เชื่อมต่อแล้ว · ได้รับสถานะล่าสุด');
  ui.setFailStateFetch(true);
  await ui.intervals[0]();
  await new Promise(resolve => setImmediate(resolve));
  assert.match(status.textContent, /ข้อมูลที่แสดงอาจค้าง/);
  assert.notEqual(stop.disabled, true);
});

test('staff direct Action distinguishes system start and mocks use a real destination', async () => {
  const ui = createStaffUI();
  await new Promise(resolve => setImmediate(resolve));
  ui.updateState({ latest_action: {
    request_id: 'staff-home', source: 'staff_override', destination_id: 'start', outcome: 'accepted'
  } });
  await ui.intervals[0]();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements.get('staff-action-destination').textContent, 'ปลายทาง: จุดเริ่มต้นระบบ (start)');

  for (const [button, expectedState] of [
    ['btn-mock-nav', 'NAVIGATING'],
    ['btn-mock-obstacle', 'REPLANNING'],
    ['btn-mock-reached', 'REACHED']
  ]) {
    await ui.elements.get(button).fire('click');
    const request = ui.requests.findLast(item => item.url === '/api/v1/staff/mock-event');
    assert.deepEqual(JSON.parse(request.options.body), {
      state: expectedState,
      goal: 'B',
      ...(expectedState === 'REPLANNING' ? { obstacle_detected: true } : {})
    });
  }
});

test('staff PIN gates dashboard and settings drafts survive polling and failed saves', async () => {
  const ui = createStaffUI();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements.get('staff-dashboard').style.display, 'flex');
  assert.equal(ui.elements.get('cfg-timeout').value, 180);
  assert.equal(ui.elements.get('cfg-delay').value, 12);

  const toggle = ui.elements.get('cfg-auto-return');
  const timeout = ui.elements.get('cfg-timeout');
  const delay = ui.elements.get('cfg-delay');
  toggle.checked = false;
  timeout.value = '420';
  delay.value = '44';
  await ui.intervals[0]();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(toggle.checked, false);
  assert.equal(timeout.value, '420');
  assert.equal(delay.value, '44');

  const requestsBeforeInvalid = ui.requests.length;
  timeout.value = '';
  await ui.elements.get('staff-config-form').fire('submit');
  assert.equal(ui.requests.length, requestsBeforeInvalid);
  assert.match(ui.elements.get('staff-feedback').textContent, /timeout ต้องเป็นจำนวนเต็ม/);

  timeout.value = '420';
  ui.queueConfigResponse({ status: 422 });
  await ui.elements.get('staff-config-form').fire('submit');
  assert.equal(timeout.value, '420');
  assert.equal(delay.value, '44');
  assert.match(ui.elements.get('staff-feedback').textContent, /HTTP 422/);

  ui.queueConfigResponse({ body: {
    auto_return_enabled: true, inactivity_timeout_sec: 300, auto_return_delay_sec: 30
  } });
  await ui.elements.get('staff-config-form').fire('submit');
  assert.equal(toggle.checked, true);
  assert.equal(timeout.value, 300);
  assert.equal(delay.value, 30);
  assert.equal(ui.elements.get('staff-feedback').textContent, 'บันทึกการตั้งค่าแล้ว');
});

test('invalid cached and typed PINs do not reveal the Staff dashboard', async () => {
  const cached = createStaffUI({ authStatus: 401 });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(cached.elements.get('staff-dashboard').style.display, 'none');
  assert.equal(cached.elements.get('pin-section').style.display, 'flex');
  assert.equal(cached.getStoredPin(), '');

  const typed = createStaffUI({ storedPin: '', authStatus: 401 });
  const input = typed.elements.get('staff-pin-input');
  input.value = 'wrong';
  await typed.elements.get('staff-pin-form').fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(typed.elements.get('staff-dashboard').style.display, 'none');
  assert.equal(typed.getStoredPin(), '');
  assert.match(typed.elements.get('staff-auth-feedback').textContent, /PIN ไม่ถูกต้อง/);
  assert.equal(typed.requests[0].url, '/api/v1/staff/config');
  assert.equal(typed.requests[0].options.method, 'GET');

  const unavailable = createStaffUI({ storedPin: '', authStatus: 503 });
  unavailable.elements.get('staff-pin-input').value = 'candidate';
  await unavailable.elements.get('staff-pin-form').fire('submit');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(unavailable.elements.get('staff-dashboard').style.display, 'none');
  assert.match(unavailable.elements.get('staff-auth-feedback').textContent, /HTTP 503/);
  assert.equal(unavailable.getStoredPin(), '');
});

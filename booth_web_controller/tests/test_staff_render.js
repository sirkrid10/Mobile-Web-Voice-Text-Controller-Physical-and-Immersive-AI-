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

function createStaffUI() {
  const elements = new Map();
  const intervals = [];
  const alerts = [];
  const requests = [];
  let failStateFetch = false;
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
    sessionStorage: { getItem: () => 'test-pin', setItem() {}, removeItem() {} },
    fetch: async (url, options = {}) => {
      requests.push({ url, options });
      return url === '/api/v1/state' && failStateFetch
        ? { ok: false, status: 503 }
        : { ok: true, json: async () => state };
    },
    setInterval(callback) { intervals.push(callback); },
    alert(message) { alerts.push(message); },
    console: { error() {} }
  };
  vm.runInNewContext(script, context, { filename: 'static/staff.html' });
  return {
    elements, intervals, alerts, requests,
    setFailStateFetch(value) { failStateFetch = value; },
    updateState(value) { Object.assign(state, value); }
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

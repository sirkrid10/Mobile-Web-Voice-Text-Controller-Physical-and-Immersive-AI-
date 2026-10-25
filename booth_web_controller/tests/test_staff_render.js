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
  let failStateFetch = false;
  const state = {
    auto_return_enabled: true,
    auto_return_delay_sec: 5,
    latest_action: null,
    locations: []
  };
  const html = fs.readFileSync(path.join(__dirname, '..', 'static', 'staff.html'), 'utf8');
  const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1];
  const context = {
    document: { getElementById(id) {
      if (!elements.has(id)) elements.set(id, new Element());
      return elements.get(id);
    } },
    sessionStorage: { getItem: () => 'test-pin', setItem() {}, removeItem() {} },
    fetch: async () => failStateFetch
      ? { ok: false, status: 503 }
      : { ok: true, json: async () => state },
    setInterval(callback) { intervals.push(callback); },
    alert(message) { alerts.push(message); },
    console: { error() {} }
  };
  vm.runInNewContext(script, context, { filename: 'static/staff.html' });
  return { elements, intervals, alerts, setFailStateFetch(value) { failStateFetch = value; } };
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

const assert = require('node:assert/strict');
const { test } = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const settle = () => new Promise(resolve => setImmediate(resolve));

function ui() {
  const elements = new Map(), calls = [], intervals = new Map();
  const get = id => {
    if (!elements.has(id)) elements.set(id, { textContent: '', disabled: false, scrollTop: 0, clientHeight: 0,
      scrollHeight: 0, addEventListener(_type, callback) { this.click = callback; } });
    return elements.get(id);
  };
  let response = { ok: true, status: 200, json: async () => ({ available: true, capacity: 2000,
    events: [{ received_at: 1, kind: 'subtitle', text: '<script>not HTML</script>', request_id: 'req-1' }] }) };
  const context = { window: {}, document: { getElementById: get }, AbortController, Date, setTimeout, clearTimeout,
    setInterval(fn) { intervals.set(1, fn); return 1; }, clearInterval(id) { intervals.delete(id); },
    async fetch(url, options) { calls.push({ url, options }); return response; } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/staff_history.js'), 'utf8'), context);
  let unauthorized = 0;
  const panel = context.window.StaffHistory.create({ onUnauthorized() { unauthorized++; panel.stop(); } });
  return { panel, calls, get, intervals, setResponse(value) { response = value; }, get unauthorized() { return unauthorized; } };
}

test('history reads only after PIN and renders untrusted text literally', async () => {
  const view = ui(); assert.equal(view.calls.length, 0);
  view.panel.start('staff-pin'); await settle();
  assert.equal(view.calls[0].options.headers['X-Staff-Pin'], 'staff-pin');
  assert.match(view.get('staff-dialogue-history').textContent, /<script>not HTML<\/script>/);
  assert.match(view.get('staff-dialogue-history').textContent, /req-1/);
  view.panel.stop(); assert.equal(view.intervals.size, 0);
  assert.equal(view.get('staff-history-refresh').disabled, true);
});

test('expired PIN clears history and late responses cannot restore it', async () => {
  const view = ui(); view.setResponse({ ok: false, status: 401 });
  view.panel.start('expired'); await settle();
  assert.equal(view.unauthorized, 1);
  assert.equal(view.get('staff-dialogue-history').textContent, 'ยืนยัน PIN เพื่อดูประวัติ');
  let resolve;
  view.setResponse(new Promise(done => { resolve = done; }));
  view.panel.start('pin'); view.panel.stop();
  resolve({ ok: true, status: 200, json: async () => ({ events: [{ text: 'late private text' }] }) });
  await settle();
  assert.doesNotMatch(view.get('staff-dialogue-history').textContent, /late private text/);
});

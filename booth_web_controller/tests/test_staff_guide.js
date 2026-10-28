const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { test } = require('node:test');

class Element {
  constructor(attributes = {}) { Object.assign(this, { attributes, textContent: '', dataset: {}, hidden: false, listeners: {}, focused: false }); }
  getAttribute(name) { return this.attributes[name]; }
  setAttribute(name, value) { this.attributes[name] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  focus() { this.focused = true; }
  click() { return this.listeners.click?.(); }
}
function fixture({ clipboardFails = false } = {}) {
  const elements = new Map(), copied = [];
  const get = id => { if (!elements.has(id)) elements.set(id, new Element()); return elements.get(id); };
  const tabs = ['control', 'guide'].map(name => new Element({ 'aria-controls': `staff-${name}-panel` }));
  const copy = new Element(); copy.dataset.copyCommand = 'guide-command-kill';
  const context = { window: {}, document: { getElementById: get, querySelectorAll: selector => selector.includes('role=') ? tabs : [copy] },
    navigator: { clipboard: { async writeText(text) { if (clipboardFails) throw new Error('not permitted'); copied.push(text); } } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../static/staff_guide.js'), 'utf8'), context);
  return { guide: context.window.StaffGuide, tabs, get, copy, copied };
}

test('guide tabs support click, arrows and resetting after logout', () => {
  const view = fixture();
  view.tabs[1].click();
  assert.equal(view.get('staff-guide-panel').hidden, false);
  assert.equal(view.get('staff-control-panel').hidden, true);
  assert.equal(view.tabs[1].getAttribute('aria-selected'), 'true');
  let prevented = false;
  view.tabs[1].listeners.keydown({ key: 'ArrowLeft', preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(view.tabs[0].focused, true);
  assert.equal(view.tabs[0].tabIndex, 0);
  assert.equal(view.tabs[1].tabIndex, -1);
  view.tabs[1].click(); view.guide.reset();
  assert.equal(view.get('staff-guide-panel').hidden, true);
});

test('commands use the actual workspace, checkout and VM with shell quoting', () => {
  const view = fixture();
  view.guide.setPaths({ processes: { workspace: "/home/user/llm's workspace" }, backend_directory: '/tmp/current checkout', ros: { discovery_server: '100.100.1.2:11811' } });
  assert.equal(view.get('guide-command-startup').textContent,
    "cd '/tmp/current checkout'\nAGENT_WORKSPACE='/home/user/llm'\\''s workspace' bash booth_web_controller/run_tailscale.sh '100.100.1.2'");
  assert.match(view.get('guide-command-kill').textContent, /kill-all --workspace/);
  assert.match(view.get('guide-command-manual-backend').textContent, /MANAGE_AGENT_NODES=false AGENT_WORKSPACE=/);
  assert.match(view.get('guide-command-subtitle').textContent, /subtitle '100.100.1.2'/);
  assert.match(view.get('guide-command-network').textContent, /tailscale ping '100.100.1.2'/);
});

test('guide remains useful without health API paths, and copying does not call an API', async () => {
  const view = fixture();
  view.guide.setPaths({});
  assert.match(view.get('guide-command-startup').textContent, /~\/ros2_ws\//);
  await view.copy.click();
  assert.equal(view.copied.length, 1);
  assert.match(view.copied[0], /kill-all/);
  assert.match(view.get('staff-guide-feedback').textContent, /ยังไม่มีการรันคำสั่ง/);
});

test('clipboard denial gives a manual-copy instruction', async () => {
  const view = fixture({ clipboardFails: true });
  await view.copy.click();
  assert.match(view.get('staff-guide-feedback').textContent, /เลือกข้อความในกรอบ/);
});

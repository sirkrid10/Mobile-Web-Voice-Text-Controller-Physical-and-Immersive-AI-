const assert = require('node:assert/strict');
const { test } = require('node:test');
const { createUI } = require('./test_app_render');

test('successful command saves the returned token for disconnect', async () => {
  const ui = createUI();
  await ui.flush();
  ui.elements.get('text-input-field').value = 'ไปจุด B';
  ui.elements.get('text-input-form').fire('submit');
  await ui.flush();
  ui.pendingRequests.at(-1).resolve({
    ok: true, status: 200,
    json: async () => ({ request_id: 'new-request', session_id: 'visitor-1', session_token: 'new-token' })
  });
  await ui.flush();
  assert.deepEqual(ui.storageWrites, [['booth_visitor_session_token', 'new-token']]);
  ui.elements.get('btn-disconnect').fire('click');
  await ui.flush();
  const request = ui.pendingRequests.at(-1);
  assert.equal(request.url, '/api/v1/session/disconnect');
  assert.equal(request.init.headers['X-Session-Token'], 'new-token');
  request.resolve({ ok: true, status: 200 });
  await ui.flush();
});

test('late command response cannot restore a token after session ownership changes', async () => {
  const ui = createUI();
  await ui.flush();
  ui.elements.get('text-input-field').value = 'ไปจุด B';
  ui.elements.get('text-input-form').fire('submit');
  await ui.flush();
  const request = ui.pendingRequests.at(-1);
  ui.sendState({ active_session_id: 'visitor-2', lock_status: 'LOCKED' });
  request.resolve({
    ok: true, status: 200,
    json: async () => ({ request_id: 'old-request', session_id: 'visitor-1', session_token: 'old-token' })
  });
  await ui.flush();
  assert.deepEqual(ui.storageWrites, []);
});

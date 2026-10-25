const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const staticDir = path.join(__dirname, '..', 'static');
const visitor = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const staff = fs.readFileSync(path.join(staticDir, 'staff.html'), 'utf8');
const styles = fs.readFileSync(path.join(staticDir, 'styles.css'), 'utf8');

function elementById(markup, id) {
  const element = markup.match(new RegExp(`<[^>]+\\bid="${id}"[^>]*>`));
  assert.ok(element, `missing #${id}`);
  return element[0];
}

function run() {
  const viewport = visitor.match(/<meta name="viewport" content="([^"]+)"/)[1];
  assert.doesNotMatch(viewport, /user-scalable=no|maximum-scale=1/);
  assert.match(visitor, /<label class="visually-hidden" for="text-input-field">/);
  assert.match(elementById(visitor, 'mic-button'), /aria-label="[^"]+"/);
  assert.match(elementById(visitor, 'mic-button'), /aria-pressed="false"/);
  assert.match(elementById(visitor, 'btn-staff-link'), /aria-label="[^"]+"/);
  const availableView = visitor.slice(visitor.indexOf('<section id="view-available"'), visitor.indexOf('<section id="view-queue"'));
  assert.match(availableView, /view-state-icon icon-available">✨/);
  assert.ok(availableView.includes('<h2 class="view-state-title">เริ่มสั่งงานหุ่นยนต์</h2>'));
  assert.match(availableView, /แตะขอสิทธิ์ควบคุมก่อน เมื่อได้รับสิทธิ์แล้วจึงสั่งงานด้วยเสียงหรือข้อความได้/);
  assert.match(availableView, /<button[^>]+id="btn-claim-session"[^>]*>\s*ขอสิทธิ์ควบคุม\s*<\/button>/);
  assert.doesNotMatch(availableView, /robot-card|mic-button|chips-container|text-input-form/);
  const observerView = visitor.slice(visitor.indexOf('<section id="view-queue"'), visitor.indexOf('<!-- Live Robot-Mind status'));
  assert.match(observerView, /มีผู้ใช้งานอยู่ กรุณารอสักครู่/);
  assert.doesNotMatch(observerView, /view-state-icon|view-state-title|robot-card|mic-button|chips-container|text-input-form/);
  assert.match(elementById(visitor, 'robot-status-card'), /style="display: none;"/);
  assert.match(elementById(visitor, 'connection-status'), /style="display: none;"/);
  assert.match(elementById(staff, 'staff-pin-input'), /autocomplete="current-password"/);
  assert.match(staff, /<label for="cfg-auto-return"/);
  assert.match(elementById(staff, 'cfg-auto-return'), /aria-label="[^"]+"/);
  assert.doesNotMatch(staff, /placeholder="Default: 1234"/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /env\(safe-area-inset-bottom\)/);
  assert.match(styles, /prefers-reduced-motion:\s*reduce/);
  assert.match(styles, /\.disconnect-btn\s*\{[^}]*min-height:\s*44px/s);
  assert.match(styles, /\.staff-link-btn\s*\{[^}]*width:\s*44px/s);
  process.stdout.write('accessibility markup checks passed\n');
}

run();

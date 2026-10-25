const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const staticDir = path.join(__dirname, '..', 'static');
const visitor = fs.readFileSync(path.join(staticDir, 'index.html'), 'utf8');
const staff = fs.readFileSync(path.join(staticDir, 'staff.html'), 'utf8');
const styles = fs.readFileSync(path.join(staticDir, 'styles.css'), 'utf8');
const app = fs.readFileSync(path.join(staticDir, 'app.js'), 'utf8');

function elementById(markup, id) {
  const element = markup.match(new RegExp(`<[^>]+\\bid="${id}"[^>]*>`));
  assert.ok(element, `missing #${id}`);
  return element[0];
}

function relativeLuminance(hex) {
  const channels = hex.match(/[0-9a-f]{2}/gi).map(channel => parseInt(channel, 16) / 255);
  const linear = channels.map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrastRatio(foreground, background) {
  const first = relativeLuminance(foreground);
  const second = relativeLuminance(background);
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

function colorToken(name) {
  const token = styles.match(new RegExp(`${name}:\\s*(#[0-9a-f]{6})`, 'i'));
  assert.ok(token, `missing visitor color token ${name}`);
  return token[1];
}

function run() {
  const viewport = visitor.match(/<meta name="viewport" content="([^"]+)"/)[1];
  assert.doesNotMatch(viewport, /user-scalable=no|maximum-scale=1/);
  assert.match(visitor, /<body class="visitor-page">/);
  assert.doesNotMatch(staff, /class="visitor-page"/);
  assert.match(visitor, /<label class="visually-hidden" for="text-input-field">/);
  assert.match(elementById(visitor, 'mic-button'), /aria-label="[^"]+"/);
  assert.match(elementById(visitor, 'mic-button'), /aria-pressed="false"/);
  assert.match(elementById(visitor, 'btn-staff-link'), /aria-label="[^"]+"/);
  const appIds = [...app.matchAll(/getElementById\('([^']+)'\)/g)].map((match) => match[1]);
  for (const id of appIds) assert.ok(elementById(visitor, id), `missing JavaScript target #${id}`);
  const availableView = visitor.slice(visitor.indexOf('<section id="view-available"'), visitor.indexOf('<section id="view-queue"'));
  assert.match(availableView, /class="view-state-icon icon-available" aria-hidden="true">\s*<svg/);
  assert.ok(availableView.includes('<h2 class="view-state-title">เริ่มสั่งงานหุ่นยนต์</h2>'));
  assert.match(availableView, /แตะขอสิทธิ์ควบคุมก่อน เมื่อได้รับสิทธิ์แล้วจึงสั่งงานด้วยเสียงหรือข้อความได้/);
  assert.match(availableView, /<button[^>]+id="btn-claim-session"[^>]*>\s*ขอสิทธิ์ควบคุม\s*<\/button>/);
  assert.doesNotMatch(availableView, /robot-card|mic-button|chips-container|text-input-form/);
  const activeView = visitor.slice(visitor.indexOf('<div id="view-active"'), visitor.indexOf('</body>'));
  assert.match(activeView, /<span class="title">หุ่นยนต์ได้ยินว่า:<\/span>/);
  assert.ok(activeView.indexOf('id="robot-status-card"') < activeView.indexOf('id="command-panel-title"'));
  assert.ok(activeView.indexOf('id="command-panel-title"') < activeView.indexOf('id="intent-result-card"'));
  const micButton = activeView.match(/<button[^>]*id="mic-button"[^>]*>[\s\S]*?<\/button>/);
  assert.ok(micButton, 'missing microphone button markup');
  assert.match(micButton[0], /<svg class="mic-icon" aria-hidden="true"/);
  const observerView = visitor.slice(visitor.indexOf('<section id="view-queue"'), visitor.indexOf('<div id="view-active"'));
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
  assert.match(styles, /\.mic-button\s*\{[^}]*-webkit-user-select:\s*none;[^}]*user-select:\s*none;[^}]*-webkit-touch-callout:\s*none;/s);
  assert.match(styles, /\.mic-button \*[\s\S]*?-webkit-touch-callout:\s*none;/);
  assert.match(styles, /\.text-input-field\s*\{[^}]*font-size:\s*16px/s);
  assert.doesNotMatch(app, /addEventListener\(['"]contextmenu['"]/);
  assert.match(styles, /\.visitor-page \.active-layout\s*\{/);
  assert.match(styles, /grid-template-areas:[\s\S]*\"robot commands\"[\s\S]*\"robot result\"/);
  assert.match(styles, /\.visitor-page \.robot-card\s*\{/);
  assert.match(styles, /\.visitor-page \.disconnect-btn\s*\{[^}]*min-height:\s*44px/s);
  assert.match(styles, /\.visitor-page \.start-session-btn\s*\{[^}]*min-height:\s*52px/s);
  assert.match(styles, /--visitor-teal:\s*#00675f/);
  assert.match(styles, /--visitor-muted:\s*#24332d/);
  assert.ok(contrastRatio(colorToken('--visitor-ink'), '#ffffff') >= 7, 'main text must meet enhanced text contrast');
  assert.ok(contrastRatio(colorToken('--visitor-muted'), '#ffffff') >= 7, 'secondary text must meet enhanced text contrast');
  assert.ok(contrastRatio(colorToken('--visitor-teal'), '#ffffff') >= 4.5, 'primary button text must meet AA contrast');
  assert.ok(contrastRatio('#34443e', '#ffffff') >= 7, 'placeholder must remain easy to read');
  assert.ok(contrastRatio(colorToken('--visitor-line'), '#ffffff') >= 3, 'card boundaries must be visible');
  assert.match(styles, /\.visitor-page \.status-label-group \.status-kicker[^}]*font-size:\s*0\.92rem/);
  assert.match(styles, /\.visitor-page \.goal-label[^}]*font-size:\s*0\.86rem/);
  assert.match(styles, /\.visitor-page \.text-input-field::placeholder[^}]*color:\s*#34443e;\s*opacity:\s*1/);
  assert.match(styles, /\.visitor-page \.chip-btn:disabled,\s*\.visitor-page \.text-input-field:disabled \{[^}]*color:\s*#24332d;[^}]*opacity:\s*1/);
  assert.doesNotMatch(styles.slice(styles.indexOf('/* --------------------------------------------------------------------------\n   Visitor page')), /radial-gradient|backdrop-filter:\s*blur/);
  assert.match(styles, /\.staff-link-btn\s*\{[^}]*width:\s*44px/s);
  process.stdout.write('accessibility markup checks passed\n');
}

run();

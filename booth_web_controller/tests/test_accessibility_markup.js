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

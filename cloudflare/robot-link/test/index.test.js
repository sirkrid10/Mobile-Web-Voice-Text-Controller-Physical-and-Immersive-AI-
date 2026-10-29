import { test, describe } from 'node:test';
import assert from 'node:assert/strict';
import worker, { validateTargetUrl } from '../src/index.js';

describe('validateTargetUrl', () => {
  test('accepts valid https trycloudflare.com subdomains', () => {
    const validCases = [
      'https://smooth-coffee-beans.trycloudflare.com/',
      'https://quick-tunnel-alpha.trycloudflare.com/',
      'https://a-b-c-123.trycloudflare.com/',
      'https://turtlebot-booth.trycloudflare.com', // parser resolves path to '/'
      'https://node-1.tunnel.trycloudflare.com/',
      'https://valid-target.trycloudflare.com:443/', // default https port 443
    ];

    for (const urlStr of validCases) {
      const parsed = validateTargetUrl(urlStr);
      assert.ok(parsed, `Expected "${urlStr}" to be valid`);
      assert.strictEqual(parsed.protocol, 'https:');
      assert.strictEqual(parsed.pathname, '/');
      assert.strictEqual(parsed.search, '');
      assert.strictEqual(parsed.hash, '');
    }
  });

  test('rejects non-https protocols', () => {
    const invalidProtocols = [
      'http://smooth-coffee-beans.trycloudflare.com/',
      'ws://smooth-coffee-beans.trycloudflare.com/',
      'wss://smooth-coffee-beans.trycloudflare.com/',
      'ftp://smooth-coffee-beans.trycloudflare.com/',
      'javascript:alert(1)',
    ];

    for (const urlStr of invalidProtocols) {
      assert.strictEqual(validateTargetUrl(urlStr), null, `Expected "${urlStr}" to be rejected`);
    }
  });

  test('rejects domain spoofing, apex domain, and suffix tricks', () => {
    const spoofedDomains = [
      'https://trycloudflare.com/', // base domain without subdomain
      'https://trycloudflare.com.evil.test/', // suffix attack
      'https://apple.trycloudflare.com.attacker.com/',
      'https://not-trycloudflare.com/',
      'https://fake-trycloudflare.com.net/',
      'https://trycloudflare.com:8000/',
      'https://sub.trycloudflare.com.attacker.org/',
    ];

    for (const urlStr of spoofedDomains) {
      assert.strictEqual(validateTargetUrl(urlStr), null, `Expected spoofed "${urlStr}" to be rejected`);
    }
  });

  test('rejects hostnames with invalid DNS label formats', () => {
    const invalidHosts = [
      'https://-leading-hyphen.trycloudflare.com/',
      'https://trailing-hyphen-.trycloudflare.com/',
      'https://invalid_underscore.trycloudflare.com/',
      'https://..trycloudflare.com/',
    ];

    for (const urlStr of invalidHosts) {
      assert.strictEqual(validateTargetUrl(urlStr), null, `Expected "${urlStr}" to be rejected`);
    }
  });

  test('rejects userinfo and non-standard ports', () => {
    const cases = [
      'https://user:pass@test.trycloudflare.com/',
      'https://user@test.trycloudflare.com/',
      'https://test.trycloudflare.com:8080/',
      'https://test.trycloudflare.com:80/',
      'https://test.trycloudflare.com:3000/',
    ];

    for (const urlStr of cases) {
      assert.strictEqual(validateTargetUrl(urlStr), null, `Expected "${urlStr}" to be rejected`);
    }
  });

  test('rejects non-root path, queries, and fragments', () => {
    const cases = [
      'https://test.trycloudflare.com/staff',
      'https://test.trycloudflare.com/api/status',
      'https://test.trycloudflare.com/?ref=qrcode',
      'https://test.trycloudflare.com/?param=1',
      'https://test.trycloudflare.com/#section',
      'https://test.trycloudflare.com/index.html',
    ];

    for (const urlStr of cases) {
      assert.strictEqual(validateTargetUrl(urlStr), null, `Expected "${urlStr}" to be rejected`);
    }
  });

  test('rejects null, empty, or non-string inputs', () => {
    assert.strictEqual(validateTargetUrl(''), null);
    assert.strictEqual(validateTargetUrl('   '), null);
    assert.strictEqual(validateTargetUrl(null), null);
    assert.strictEqual(validateTargetUrl(undefined), null);
    assert.strictEqual(validateTargetUrl(12345), null);
    assert.strictEqual(validateTargetUrl({}), null);
  });
});

describe('Worker fetch handler', () => {
  function createMockEnv(initialUrl) {
    let current = initialUrl;
    return {
      ROBOT_LINKS: {
        async get(key) {
          if (key === 'robot_url') {
            return current;
          }
          return null;
        },
        setUrl(newUrl) {
          current = newUrl;
        },
      },
    };
  }

  test('GET / with valid KV target returns 302 redirect with no-store', async () => {
    const target = 'https://valid-tunnel-123.trycloudflare.com/';
    const env = createMockEnv(target);
    const request = new Request('https://robot-link.example.workers.dev/', { method: 'GET' });

    const response = await worker.fetch(request, env);
    assert.strictEqual(response.status, 302);
    assert.strictEqual(response.headers.get('Location'), target);
    assert.ok(response.headers.get('Cache-Control')?.includes('no-store'));
    assert.ok(response.headers.get('Cache-Control')?.includes('no-cache'));

    const text = await response.text();
    assert.ok(text.includes(target));
  });

  test('HEAD / with valid KV target returns 302 redirect with null body', async () => {
    const target = 'https://valid-tunnel-123.trycloudflare.com/';
    const env = createMockEnv(target);
    const request = new Request('https://robot-link.example.workers.dev/', { method: 'HEAD' });

    const response = await worker.fetch(request, env);
    assert.strictEqual(response.status, 302);
    assert.strictEqual(response.headers.get('Location'), target);
    assert.ok(response.headers.get('Cache-Control')?.includes('no-store'));

    const text = await response.text();
    assert.strictEqual(text, '');
  });

  test('Updating KV changes redirect destination (Tunnel A -> Tunnel B)', async () => {
    const tunnelA = 'https://tunnel-a.trycloudflare.com/';
    const tunnelB = 'https://tunnel-b.trycloudflare.com/';
    const env = createMockEnv(tunnelA);

    // Initial request -> tunnel A
    const resA = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), env);
    assert.strictEqual(resA.status, 302);
    assert.strictEqual(resA.headers.get('Location'), tunnelA);

    // KV update
    env.ROBOT_LINKS.setUrl(tunnelB);

    // Subsequent request -> tunnel B
    const resB = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), env);
    assert.strictEqual(resB.status, 302);
    assert.strictEqual(resB.headers.get('Location'), tunnelB);
  });

  test('GET / returns 503 when KV target is missing or null', async () => {
    const env = createMockEnv(null);
    const request = new Request('https://robot-link.example.workers.dev/', { method: 'GET' });

    const response = await worker.fetch(request, env);
    assert.strictEqual(response.status, 503);
    assert.strictEqual(response.headers.get('Location'), null);
    assert.ok(response.headers.get('Cache-Control')?.includes('no-store'));

    const body = await response.text();
    assert.ok(body.includes('ระบบยังไม่พร้อมให้บริการ'));
  });

  test('HEAD / returns 503 with null body when KV target is missing', async () => {
    const env = createMockEnv(null);
    const request = new Request('https://robot-link.example.workers.dev/', { method: 'HEAD' });

    const response = await worker.fetch(request, env);
    assert.strictEqual(response.status, 503);
    assert.strictEqual(response.headers.get('Location'), null);

    const body = await response.text();
    assert.strictEqual(body, '');
  });

  test('GET / returns 503 when KV target is invalid or spoofed', async () => {
    const invalidTargets = [
      '',
      'invalid-string',
      'http://insecure.trycloudflare.com/',
      'https://trycloudflare.com/',
      'https://trycloudflare.com.evil.test/',
      'https://test.trycloudflare.com/staff',
    ];

    for (const invalid of invalidTargets) {
      const env = createMockEnv(invalid);
      const res = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), env);
      assert.strictEqual(res.status, 503, `Expected 503 for invalid target "${invalid}"`);
      assert.strictEqual(res.headers.get('Location'), null);
    }
  });

  test('GET / returns 503 gracefully when KV throws exception', async () => {
    const faultyEnv = {
      ROBOT_LINKS: {
        async get() {
          throw new Error('KV service unavailable');
        },
      },
    };

    const res = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), faultyEnv);
    assert.strictEqual(res.status, 503);
    assert.strictEqual(res.headers.get('Location'), null);
    const text = await res.text();
    assert.ok(!text.includes('KV service unavailable'), 'Internal error must not leak');
  });

  test('GET / without env or ROBOT_LINKS binding returns 503 gracefully', async () => {
    const resEmptyEnv = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), {});
    assert.strictEqual(resEmptyEnv.status, 503);

    const resNullEnv = await worker.fetch(new Request('https://robot-link.example.workers.dev/'), null);
    assert.strictEqual(resNullEnv.status, 503);
  });

  test('Non-root paths return 404 Not Found', async () => {
    const env = createMockEnv('https://tunnel.trycloudflare.com/');
    const paths = ['/staff', '/api/status', '/index.html', '/ws/status', '/test'];

    for (const path of paths) {
      const res = await worker.fetch(new Request(`https://robot-link.example.workers.dev${path}`), env);
      assert.strictEqual(res.status, 404, `Expected 404 for path "${path}"`);
      assert.strictEqual(res.headers.get('Location'), null);
      assert.ok(res.headers.get('Cache-Control')?.includes('no-store'));
    }
  });

  test('Unsupported HTTP methods return 405 Method Not Allowed with Allow header', async () => {
    const env = createMockEnv('https://tunnel.trycloudflare.com/');
    const disallowedMethods = ['POST', 'PUT', 'DELETE', 'PATCH', 'OPTIONS'];

    for (const method of disallowedMethods) {
      const res = await worker.fetch(
        new Request('https://robot-link.example.workers.dev/', { method }),
        env
      );
      assert.strictEqual(res.status, 405, `Expected 405 for method "${method}"`);
      assert.strictEqual(res.headers.get('Allow'), 'GET, HEAD');
      assert.strictEqual(res.headers.get('Location'), null);
      assert.ok(res.headers.get('Cache-Control')?.includes('no-store'));
    }
  });
});

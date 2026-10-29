/**
 * Cloudflare Worker: Static QR Redirect Service for TurtleBot3 Mobile Web Controller.
 * Redirects visitors scanning a static QR code to the active Quick Tunnel URL.
 */

/**
 * Validates whether a given URL string is a safe, valid trycloudflare target.
 * Requirements:
 * - Valid URL parseable by URL constructor
 * - Protocol MUST be 'https:'
 * - Hostname MUST be a valid subdomain of trycloudflare.com
 *   (e.g., <subdomain>.trycloudflare.com where subdomain is a valid DNS label)
 * - Hostname must NOT be 'trycloudflare.com' itself
 * - Must reject spoofed hostnames/suffixes (e.g., trycloudflare.com.evil.test)
 * - Username and password (userinfo) MUST be empty
 * - Port MUST be empty or default '443'
 * - Pathname MUST be exactly '/'
 * - Query (search) MUST be empty
 * - Fragment (hash) MUST be empty
 *
 * @param {unknown} urlStr
 * @returns {URL | null} Parsed URL object if valid, null otherwise
 */
export function validateTargetUrl(urlStr) {
  if (typeof urlStr !== 'string') {
    return null;
  }

  const trimmed = urlStr.trim();
  if (!trimmed) {
    return null;
  }

  let parsed;
  try {
    parsed = new URL(trimmed);
  } catch {
    return null;
  }

  // 1. Protocol must be https:
  if (parsed.protocol !== 'https:') {
    return null;
  }

  // 2. Reject userinfo
  if (parsed.username || parsed.password) {
    return null;
  }

  // 3. Reject custom port (allow only default 443 or empty)
  if (parsed.port && parsed.port !== '443') {
    return null;
  }

  // 4. Reject query and fragment
  if (parsed.search || parsed.hash) {
    return null;
  }

  // 5. Path must be exactly '/'
  if (parsed.pathname !== '/') {
    return null;
  }

  // 6. Hostname validation:
  // Must be a valid single or multi-part subdomain under trycloudflare.com
  // Format of quick tunnel: e.g. "random-words.trycloudflare.com"
  const hostname = parsed.hostname.toLowerCase();
  if (hostname === 'trycloudflare.com') {
    return null;
  }

  // Strict regex: subdomain label(s) followed strictly by .trycloudflare.com
  // Disallows leading/trailing hyphens in labels and suffix tricks like .trycloudflare.com.evil.com
  const trycloudflareRegex = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.trycloudflare\.com$/;
  if (!trycloudflareRegex.test(hostname)) {
    return null;
  }

  return parsed;
}

/**
 * Generates an HTML response body for 503 Service Unavailable in Thai.
 * @returns {string}
 */
export function renderUnavailableHtml() {
  return `<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ระบบยังไม่พร้อมให้บริการ</title>
  <style>
    :root {
      --bg: #f8fafc;
      --card-bg: #ffffff;
      --text-main: #0f172a;
      --text-muted: #475569;
      --primary: #2563eb;
      --border: #e2e8f0;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans Thai", sans-serif;
      background-color: var(--bg);
      color: var(--text-main);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 1.25rem;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 1rem;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -4px rgba(0, 0, 0, 0.05);
      padding: 2rem;
      max-width: 28rem;
      width: 100%;
      text-align: center;
    }
    .icon {
      font-size: 2.5rem;
      margin-bottom: 1rem;
      line-height: 1;
    }
    h1 {
      font-size: 1.25rem;
      font-weight: 700;
      color: var(--text-main);
      margin-bottom: 0.75rem;
    }
    p {
      font-size: 0.95rem;
      line-height: 1.6;
      color: var(--text-muted);
      margin-bottom: 1.5rem;
    }
    .btn {
      display: inline-block;
      width: 100%;
      background-color: var(--primary);
      color: #ffffff;
      padding: 0.75rem 1.25rem;
      border-radius: 0.5rem;
      font-size: 0.95rem;
      font-weight: 600;
      text-decoration: none;
      transition: background-color 0.15s ease;
      cursor: pointer;
      border: none;
    }
    .btn:hover { background-color: #1d4ed8; }
  </style>
</head>
<body>
  <main class="card">
    <div class="icon" aria-hidden="true">🤖</div>
    <h1>ระบบยังไม่พร้อมให้บริการ</h1>
    <p>ระบบควบคุมหุ่นยนต์กำลังเตรียมการหรืออยู่นอกช่วงเวลาสาธิต กรุณารอสักครู่แล้วลองใหม่อีกครั้ง หรือติดต่อเจ้าหน้าที่ประจำบูธ</p>
    <button class="btn" onclick="location.reload();">ลองเชื่อมต่อใหม่</button>
  </main>
</body>
</html>`;
}

export default {
  /**
   * Cloudflare Worker fetch handler.
   *
   * @param {Request} request
   * @param {{ ROBOT_LINKS?: { get: (key: string) => Promise<string | null> } }} env
   * @param {unknown} ctx
   * @returns {Promise<Response>}
   */
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    // 1. Only root path '/' is supported
    if (url.pathname !== '/') {
      return new Response('Not Found', {
        status: 404,
        headers: {
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store, no-cache, must-revalidate',
          'Pragma': 'no-cache',
        },
      });
    }

    // 2. Only GET and HEAD methods are supported
    const method = request.method.toUpperCase();
    if (method !== 'GET' && method !== 'HEAD') {
      return new Response('Method Not Allowed', {
        status: 405,
        headers: {
          'Allow': 'GET, HEAD',
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store, no-cache, must-revalidate',
          'Pragma': 'no-cache',
        },
      });
    }

    // 3. Retrieve target URL from KV binding ROBOT_LINKS, key 'robot_url'
    let rawTarget = null;
    try {
      if (env && env.ROBOT_LINKS && typeof env.ROBOT_LINKS.get === 'function') {
        rawTarget = await env.ROBOT_LINKS.get('robot_url');
      }
    } catch {
      // Swallow error without leaking internal details
      rawTarget = null;
    }

    // 4. Validate target URL
    const validTarget = validateTargetUrl(rawTarget);
    if (!validTarget) {
      return new Response(method === 'HEAD' ? null : renderUnavailableHtml(), {
        status: 503,
        headers: {
          'Content-Type': 'text/html; charset=utf-8',
          'Cache-Control': 'no-store, no-cache, must-revalidate',
          'Pragma': 'no-cache',
        },
      });
    }

    // 5. Success: HTTP 302 Found redirect
    const redirectUrl = validTarget.toString();
    const redirectBody = `<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0;url=${redirectUrl}">
  <title>Redirecting...</title>
</head>
<body>
  <p>Redirecting to <a href="${redirectUrl}">${redirectUrl}</a>...</p>
</body>
</html>`;

    return new Response(method === 'HEAD' ? null : redirectBody, {
      status: 302,
      headers: {
        'Location': redirectUrl,
        'Cache-Control': 'no-store, no-cache, must-revalidate',
        'Pragma': 'no-cache',
        'Content-Type': 'text/html; charset=utf-8',
      },
    });
  },
};

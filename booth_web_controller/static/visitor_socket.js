'use strict';

globalThis.createVisitorSocket = function ({ isValidStateSnapshot, renderState,
    setConnectionStatus, onSnapshot }) {
  let ws = null;
  let wsReconnectTimer = null;

  function initWebSocket() {
    let socketReceivedSnapshot = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/status`;

    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      console.log('[WebSocket] Connected to /ws/status');
      if (!socketReceivedSnapshot) setConnectionStatus('connecting');
      if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
      }
    };

    ws.onmessage = function (event) {
      try {
        const state = JSON.parse(event.data);
        if (!isValidStateSnapshot(state)) return;
        socketReceivedSnapshot = true;
        onSnapshot();
        renderState(state);
        setConnectionStatus('connected');
      } catch (e) {
        console.error('[WebSocket] Error parsing state JSON:', e);
      }
    };

    ws.onclose = function () {
      console.warn('[WebSocket] Closed. Attempting reconnect in 2s...');
      setConnectionStatus('disconnected');
      wsReconnectTimer = setTimeout(initWebSocket, 2000);
    };

    ws.onerror = function (err) {
      console.error('[WebSocket] Error:', err);
      ws.close();
    };
  }

  return { connect: initWebSocket };
};

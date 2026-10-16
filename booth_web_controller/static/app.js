/**
 * Mobile Web Voice & Text Controller - Frontend Engine
 * Physical and Immersive AI (TurtleBot3 + ROS 2 Nav2 + LLM + VR View)
 */

(function () {
  'use strict';

  // --------------------------------------------------------------------------
  // Client Identity & Session Token Management
  // --------------------------------------------------------------------------
  function getOrCreateSessionId() {
    let id = localStorage.getItem('booth_visitor_session_id');
    if (!id) {
      if (crypto.randomUUID) {
        id = crypto.randomUUID();
      } else {
        id = 'visitor-' + Math.random().toString(36).substring(2, 11) + Date.now().toString(36);
      }
      localStorage.setItem('booth_visitor_session_id', id);
    }
    return id;
  }

  const mySessionId = getOrCreateSessionId();
  let mySessionToken = sessionStorage.getItem('booth_visitor_session_token') || null;
  let currentState = null;

  // Audio Recording State
  let mediaRecorder = null;
  let audioChunks = [];
  let audioStream = null;
  let isRecording = false;

  // DOM Elements - Visitor UI
  const viewAvailable = document.getElementById('view-available');
  const viewActive = document.getElementById('view-active');
  const viewQueue = document.getElementById('view-queue');

  const btnClaim = document.getElementById('btn-claim-session');
  const btnDisconnect = document.getElementById('btn-disconnect');
  const btnExtend = document.getElementById('btn-extend-time');
  const warningBanner = document.getElementById('warning-banner');

  const sessionCountdown = document.getElementById('session-countdown');
  const sessionStatusBadge = document.getElementById('session-status-badge');

  const robotDot = document.getElementById('robot-dot');
  const robotStateText = document.getElementById('robot-state-text');
  const robotGoalTag = document.getElementById('robot-goal-tag');
  const robotHeardText = document.getElementById('robot-heard-text');
  const robotReasonText = document.getElementById('robot-reason-text');

  const micButton = document.getElementById('mic-button');
  const micLabel = document.getElementById('mic-label');
  const waveform = document.getElementById('waveform');
  const transcriptPreview = document.getElementById('transcript-preview');

  const chipsContainer = document.getElementById('chips-container');
  const textInputForm = document.getElementById('text-input-form');
  const textInputField = document.getElementById('text-input-field');
  const sendBtn = document.getElementById('btn-send-text');

  // --------------------------------------------------------------------------
  // Audio MIME Support Detection (iOS Safari & Android Chrome)
  // --------------------------------------------------------------------------
  function getSupportedMimeType() {
    const candidates = [
      'audio/webm;codecs=opus',
      'audio/webm',
      'audio/mp4',
      'audio/ogg'
    ];
    for (const mime of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(mime)) {
        return mime;
      }
    }
    return '';
  }

  // --------------------------------------------------------------------------
  // WebSocket Status Client
  // --------------------------------------------------------------------------
  let ws = null;
  let wsReconnectTimer = null;

  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/status`;

    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      console.log('[WebSocket] Connected to /ws/status');
      if (wsReconnectTimer) {
        clearTimeout(wsReconnectTimer);
        wsReconnectTimer = null;
      }
    };

    ws.onmessage = function (event) {
      try {
        const state = JSON.parse(event.data);
        renderState(state);
      } catch (e) {
        console.error('[WebSocket] Error parsing state JSON:', e);
      }
    };

    ws.onclose = function () {
      console.warn('[WebSocket] Closed. Attempting reconnect in 2s...');
      wsReconnectTimer = setTimeout(initWebSocket, 2000);
    };

    ws.onerror = function (err) {
      console.error('[WebSocket] Error:', err);
      ws.close();
    };
  }

  // --------------------------------------------------------------------------
  // State Rendering & View Switching
  // --------------------------------------------------------------------------
  function renderState(state) {
    currentState = state;

    // 1. Robot Mind Card Info
    renderRobotMind(state);

    // 2. View Switcher Logic
    const isMine = state.active_session_id === mySessionId;
    const isFree = state.lock_status === 'AVAILABLE' || !state.active_session_id;

    if (viewAvailable && viewActive && viewQueue) {
      if (isMine) {
        // Active Controller
        viewAvailable.style.display = 'none';
        viewQueue.style.display = 'none';
        viewActive.style.display = 'flex';
        renderActiveController(state);
      } else if (isFree) {
        // Available for anyone to claim
        viewActive.style.display = 'none';
        viewQueue.style.display = 'none';
        viewAvailable.style.display = 'flex';
      } else {
        // Locked by another visitor -> Observer mode
        viewAvailable.style.display = 'none';
        viewActive.style.display = 'none';
        viewQueue.style.display = 'flex';
      }
    }

    // 3. Dynamic Quick Chips
    if (state.locations && chipsContainer) {
      renderChips(state.locations);
    }
  }

  function renderRobotMind(state) {
    if (!robotStateText) return;

    // State classes and labels
    const stateLabels = {
      'IDLE': { label: 'พร้อมรับคำสั่ง (Idle)', class: 'state-idle' },
      'NAVIGATING': { label: 'กำลังนำทาง (Navigating)', class: 'state-navigating' },
      'REPLANNING': { label: 'พบสิ่งกีดขวาง กำลังคำนวณใหม่ (Replanning)', class: 'state-replanning' },
      'REACHED': { label: 'ถึงจุดหมายแล้ว (Reached)', class: 'state-reached' },
      'STOPPED': { label: 'หยุดฉุกเฉิน (Stopped)', class: 'state-stopped' },
      'FAILED': { label: 'เกิดข้อผิดพลาด (Failed)', class: 'state-stopped' }
    };

    const info = stateLabels[state.robot_state] || { label: state.robot_state, class: 'state-idle' };
    robotStateText.textContent = info.label;

    if (robotDot) {
      robotDot.className = 'status-dot-pulse ' + info.class;
    }

    if (robotGoalTag) {
      robotGoalTag.textContent = state.current_goal ? `📍 ${state.current_goal}` : '—';
    }

    if (robotHeardText) {
      robotHeardText.textContent = state.heard_text ? `"${state.heard_text}"` : '(ยังไม่มีคำสั่งเสียงล่าสุด)';
    }

    if (robotReasonText) {
      robotReasonText.textContent = state.llm_reason || 'กำลังรันการประมวลผลคำสั่ง';
    }
  }

  function renderActiveController(state) {
    // Timer display
    if (sessionCountdown && sessionStatusBadge) {
      if (state.timer_paused_for_navigation) {
        sessionStatusBadge.className = 'session-badge paused';
        sessionCountdown.textContent = 'กำลังเดินทาง (หยุดนับเวลาชั่วคราว)';
      } else {
        const rem = state.inactivity_remaining_sec;
        if (state.show_timeout_warning) {
          sessionStatusBadge.className = 'session-badge warning';
          sessionCountdown.textContent = `เหลือเวลา: ${rem}s (กดต่อเวลา)`;
        } else {
          sessionStatusBadge.className = 'session-badge active';
          sessionCountdown.textContent = `ถือสิทธิ์ควบคุม: ${rem}s`;
        }
      }
    }

    // Warning Banner (<= 15s)
    if (warningBanner) {
      if (state.show_timeout_warning && !state.timer_paused_for_navigation) {
        warningBanner.style.display = 'flex';
      } else {
        warningBanner.style.display = 'none';
      }
    }
  }

  let renderedChipsIds = '';

  function renderChips(locations) {
    if (!chipsContainer) return;
    const currentIds = locations.map(l => l.id).join(',');
    if (currentIds === renderedChipsIds) return;
    renderedChipsIds = currentIds;

    chipsContainer.innerHTML = '';
    locations.forEach(loc => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'chip-btn' + (loc.id === 'START_BOOTH' || loc.id === 'WAIT_HERE' ? ' full-width' : '');
      btn.textContent = loc.label;
      btn.addEventListener('click', () => sendTextCommand(loc.prompt, 'chip'));
      chipsContainer.appendChild(btn);
    });
  }

  // --------------------------------------------------------------------------
  // API Calls: Session Claim, Disconnect, Heartbeat
  // --------------------------------------------------------------------------
  async function claimSession() {
    try {
      const res = await fetch('/api/v1/session/claim', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: mySessionId })
      });
      if (res.ok) {
        const data = await res.json();
        mySessionToken = data.session_token;
        sessionStorage.setItem('booth_visitor_session_token', mySessionToken);
        console.log('[Session] Claimed successfully:', data);
      } else if (res.status === 409) {
        alert('ขณะนี้มีผู้ชมท่านอื่นกำลังใช้งานอยู่ กรุณารอสักครู่ครับ');
      }
    } catch (e) {
      console.error('[Session] Claim failed:', e);
    }
  }

  async function disconnectSession() {
    if (!confirm('ต้องการจบการใช้งานและส่งต่อคิวให้ผู้ชมท่านอื่นใช่หรือไม่?')) return;
    try {
      await fetch('/api/v1/session/disconnect', {
        method: 'POST',
        headers: {
          'X-Session-Token': mySessionToken || ''
        }
      });
      mySessionToken = null;
      sessionStorage.removeItem('booth_visitor_session_token');
    } catch (e) {
      console.error('[Session] Disconnect failed:', e);
    }
  }

  async function heartbeatSession() {
    try {
      await fetch('/api/v1/session/heartbeat', {
        method: 'POST',
        headers: {
          'X-Session-Token': mySessionToken || ''
        }
      });
      if (warningBanner) warningBanner.style.display = 'none';
    } catch (e) {
      console.error('[Session] Heartbeat failed:', e);
    }
  }

  // --------------------------------------------------------------------------
  // Push-to-Talk Voice Recording
  // --------------------------------------------------------------------------
  async function startRecording() {
    if (isRecording) return;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioStream = stream;
      audioChunks = [];

      const mimeType = getSupportedMimeType();
      const options = mimeType ? { mimeType } : {};
      mediaRecorder = new MediaRecorder(stream, options);

      mediaRecorder.ondataavailable = function (e) {
        if (e.data && e.data.size > 0) {
          audioChunks.push(e.data);
        }
      };

      mediaRecorder.onstop = async function () {
        const blobType = mimeType || 'audio/webm';
        const audioBlob = new Blob(audioChunks, { type: blobType });
        console.log(`[MediaRecorder] Audio recorded: ${audioBlob.size} bytes (${blobType})`);

        if (audioStream) {
          audioStream.getTracks().forEach(t => t.stop());
          audioStream = null;
        }

        await sendVoiceCommand(audioBlob);
      };

      mediaRecorder.start();
      isRecording = true;

      if (micButton) micButton.classList.add('recording');
      if (micLabel) micLabel.textContent = 'ปล่อยเพื่อส่ง';
      if (waveform) waveform.classList.add('active');
      if (transcriptPreview) transcriptPreview.textContent = 'กำลังฟังเสียงของคุณ...';
    } catch (err) {
      console.error('[Audio] getUserMedia error:', err);
      alert('ไม่สามารถเข้าถึงไมโครโฟนได้ กรุณาอนุญาตสิทธิ์ไมโครโฟนบนเบราว์เซอร์ หรือใช้ช่องพิมพ์ข้อความด้านล่างแทนครับ');
    }
  }

  function stopRecording() {
    if (!isRecording || !mediaRecorder) return;
    try {
      mediaRecorder.stop();
    } catch (e) {
      console.error('[Audio] Stop error:', e);
    }
    isRecording = false;

    if (micButton) micButton.classList.remove('recording');
    if (micLabel) micLabel.textContent = 'แตะเพื่อพูด';
    if (waveform) waveform.classList.remove('active');
  }

  async function sendVoiceCommand(blob) {
    if (transcriptPreview) transcriptPreview.textContent = 'กำลังถอดความและประมวลผล...';
    const formData = new FormData();
    const ext = blob.type.includes('mp4') ? 'mp4' : 'webm';
    formData.append('audio', blob, `voice_${Date.now()}.${ext}`);

    try {
      const headers = {
        'X-Session-Id': mySessionId
      };
      if (mySessionToken) {
        headers['X-Session-Token'] = mySessionToken;
      }

      const res = await fetch('/api/v1/command/voice', {
        method: 'POST',
        headers: headers,
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        if (transcriptPreview) {
          transcriptPreview.textContent = `ส่งคำสั่งแล้ว: "${data.transcript}"`;
        }
      } else if (res.status === 403) {
        alert('สิทธิ์การควบคุมหมดอายุ หรือมีผู้ชมท่านอื่นกำลังถือสิทธิ์');
      }
    } catch (e) {
      console.error('[Command] Send voice error:', e);
      if (transcriptPreview) transcriptPreview.textContent = 'เกิดข้อผิดพลาดในการส่งเสียง';
    }
  }

  // --------------------------------------------------------------------------
  // Text & Chip Command Submission
  // --------------------------------------------------------------------------
  async function sendTextCommand(text, mode = 'text') {
    if (!text || !text.trim()) return;
    const cleanText = text.trim();

    if (transcriptPreview) transcriptPreview.textContent = `ส่งคำสั่ง: "${cleanText}"`;

    try {
      const headers = {
        'Content-Type': 'application/json',
        'X-Session-Id': mySessionId
      };
      if (mySessionToken) {
        headers['X-Session-Token'] = mySessionToken;
      }

      const res = await fetch('/api/v1/command/text', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ text: cleanText, input_mode: mode })
      });

      if (res.ok) {
        const data = await res.json();
        if (textInputField) textInputField.value = '';
      } else if (res.status === 403) {
        alert('สิทธิ์การควบคุมหมดอายุ หรือมีผู้ชมท่านอื่นกำลังถือสิทธิ์');
      }
    } catch (e) {
      console.error('[Command] Send text error:', e);
    }
  }

  // --------------------------------------------------------------------------
  // Event Listeners Binding
  // --------------------------------------------------------------------------
  if (btnClaim) {
    btnClaim.addEventListener('click', claimSession);
  }

  if (btnDisconnect) {
    btnDisconnect.addEventListener('click', disconnectSession);
  }

  if (btnExtend) {
    btnExtend.addEventListener('click', heartbeatSession);
  }

  if (micButton) {
    let pressTimer = null;
    let isHoldMode = false;

    micButton.addEventListener('pointerdown', (e) => {
      e.preventDefault();
      pressTimer = setTimeout(() => {
        isHoldMode = true;
        startRecording();
      }, 250);
    });

    micButton.addEventListener('pointerup', (e) => {
      e.preventDefault();
      if (pressTimer) {
        clearTimeout(pressTimer);
        pressTimer = null;
      }
      if (isHoldMode) {
        stopRecording();
        isHoldMode = false;
      } else {
        if (isRecording) {
          stopRecording();
        } else {
          startRecording();
        }
      }
    });

    micButton.addEventListener('pointercancel', () => {
      if (pressTimer) clearTimeout(pressTimer);
      if (isRecording) stopRecording();
      isHoldMode = false;
    });
  }

  if (textInputForm) {
    textInputForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (textInputField) {
        sendTextCommand(textInputField.value, 'text');
      }
    });
  }

  initWebSocket();
  fetch('/api/v1/state')
    .then(r => r.json())
    .then(renderState)
    .catch(err => console.error('Initial state fetch error:', err));

})();

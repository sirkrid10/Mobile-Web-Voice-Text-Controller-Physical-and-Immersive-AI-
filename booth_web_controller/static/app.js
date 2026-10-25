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
  let previousSessionOwnership = null;
  let submissionGeneration = 0;
  let pendingSubmission = null;
  let currentSubmission = null;
  let submissionFeedback = '';

  // Audio Recording State
  let isRecording = false;
  let isAcquiringMicrophone = false;
  let isUploadingMicrophone = false;
  let recordingGeneration = 0;
  let activeRecording = null;

  // DOM Elements - Visitor UI
  const viewAvailable = document.getElementById('view-available');
  const viewActive = document.getElementById('view-active');
  const viewQueue = document.getElementById('view-queue');
  const viewLoading = document.getElementById('view-loading');
  const robotStatusCard = document.getElementById('robot-status-card');

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
  const intentResultStatus = document.getElementById('intent-result-status');
  const intentResultMessage = document.getElementById('intent-result-message');
  const intentResultDetail = document.getElementById('intent-result-detail');

  const micButton = document.getElementById('mic-button');
  const micLabel = document.getElementById('mic-label');
  const waveform = document.getElementById('waveform');
  const transcriptPreview = document.getElementById('transcript-preview');
  const audioDebugEnabled = /(?:\?|&)debug_audio=1(?:&|$)/.test(window.location.search || '');
  const audioDebugPanel = document.getElementById('voice-audio-debug');
  const audioDebugPlayer = document.getElementById('voice-audio-player');
  const audioDebugDownload = document.getElementById('voice-audio-download');
  const audioDebugDescription = document.getElementById('voice-audio-description');
  let audioDebugUrl = null;

  const chipsContainer = document.getElementById('chips-container');
  const textInputForm = document.getElementById('text-input-form');
  const textInputField = document.getElementById('text-input-field');
  const sendBtn = document.getElementById('btn-send-text');
  const connectionStatusText = document.getElementById('connection-status');
  const sessionFeedbackText = document.getElementById('session-feedback');
  let connectionStatus = 'connecting';

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
  let receivedWebSocketState = false;

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
        receivedWebSocketState = true;
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

  function isValidStateSnapshot(state) {
    return Boolean(state && typeof state === 'object' &&
      typeof state.robot_state === 'string' && 'active_session_id' in state &&
      Array.isArray(state.locations));
  }

  function setConnectionStatus(status) {
    connectionStatus = status;
    const copy = {
      connecting: 'กำลังเชื่อมต่อ รอสถานะล่าสุดก่อนส่งคำสั่ง',
      connected: 'เชื่อมต่อแล้ว · ได้รับสถานะล่าสุด',
      disconnected: 'ขาดการเชื่อมต่อ · ข้อมูลล่าสุดยังไม่ยืนยัน'
    };
    if (connectionStatusText) {
      connectionStatusText.textContent = copy[status];
      connectionStatusText.className = `connection-status ${status}`;
    }
    renderCommandAvailability();
    if (currentState && viewActive && viewActive.style.display !== 'none') {
      renderActiveController(currentState);
    }
  }

  function canSubmitVisitorCommand() {
    return connectionStatus === 'connected' && currentState &&
      currentState.active_session_id === mySessionId;
  }

  function renderCommandAvailability() {
    const unavailable = !canSubmitVisitorCommand();
    if (textInputField) textInputField.disabled = unavailable;
    if (sendBtn) sendBtn.disabled = unavailable;
    if (chipsContainer) {
      for (const button of chipsContainer.children) {
        button.disabled = unavailable;
      }
    }
    if (micButton) {
      micButton.disabled = isUploadingMicrophone ||
        (unavailable && !isRecording && !isAcquiringMicrophone);
    }
  }

  // --------------------------------------------------------------------------
  // State Rendering & View Switching
  // --------------------------------------------------------------------------
  function renderState(state) {
    currentState = state;
    const ownsSession = state.active_session_id === mySessionId;
    if (previousSessionOwnership !== null && previousSessionOwnership !== ownsSession) {
      resetSubmissionState();
    }
    previousSessionOwnership = ownsSession;

    // 1. Robot Mind Card Info
    renderRobotMind(state);
    renderIntentResult(state);
    if (viewLoading) viewLoading.style.display = 'none';
    if (robotStatusCard) robotStatusCard.style.display = 'flex';

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
    renderCommandAvailability();
  }

  function renderRobotMind(state) {
    if (!robotStateText) return;

    // State classes and labels
    const stateLabels = {
      'IDLE': { label: 'พร้อมรับคำสั่ง (Idle)', class: 'state-idle' },
      'NAVIGATING': { label: 'กำลังนำทาง (Navigating)', class: 'state-navigating' },
      'REPLANNING': { label: 'พบสิ่งกีดขวาง กำลังคำนวณใหม่ (Replanning)', class: 'state-replanning' },
      'REACHED': { label: 'ถึงจุดหมายแล้ว (Reached)', class: 'state-reached' },
      'STOPPED': { label: 'หยุด/ยกเลิกการนำทาง (Stopped)', class: 'state-stopped' },
      'NOT_READY': { label: 'ยังไม่พร้อม (Not ready)', class: 'state-stopped' },
      'UNKNOWN': { label: 'ยังไม่ทราบสถานะ (Unknown)', class: 'state-stopped' },
      'FAILED': { label: 'เกิดข้อผิดพลาด (Failed)', class: 'state-stopped' }
    };

    const info = stateLabels[state.robot_state] || { label: state.robot_state, class: 'state-idle' };
    robotStateText.textContent = info.label;

    if (robotDot) {
      robotDot.className = 'status-dot-pulse ' + info.class;
    }

    if (robotGoalTag) {
      robotGoalTag.textContent = `📍 ${formatGoalTarget(state.current_goal, state.locations)}`;
    }

    if (robotHeardText) {
      robotHeardText.textContent = state.heard_text ? `"${state.heard_text}"` : '(ยังไม่มีคำสั่งเสียงล่าสุด)';
    }

    if (robotReasonText) {
      robotReasonText.textContent = state.llm_reason || '';
    }
  }

  function formatGoalTarget(destinationId, locations) {
    if (!destinationId) return '—';
    if (destinationId === 'start') return 'จุดเริ่มต้นระบบ (start)';
    const location = Array.isArray(locations)
      ? locations.find(item => item && item.id === destinationId)
      : null;
    return location && typeof location.label === 'string' ? location.label : destinationId;
  }

  function setIntentResult(status, message = '', detail = '') {
    if (!intentResultStatus) return;
    if (intentResultStatus.textContent !== status) intentResultStatus.textContent = status;
    if (intentResultMessage && intentResultMessage.textContent !== message) {
      intentResultMessage.textContent = message;
    }
    if (intentResultDetail && intentResultDetail.textContent !== detail) {
      intentResultDetail.textContent = detail;
    }
  }

  function renderIntentResult(state) {
    const neutral = 'ยังไม่มีผลแปลงคำสั่ง';
    if (!state || state.active_session_id !== mySessionId) {
      setIntentResult(neutral);
      return;
    }

    if (submissionFeedback) {
      setIntentResult('ส่งคำสั่งไม่สำเร็จ', submissionFeedback);
      return;
    }
    if (pendingSubmission) {
      setIntentResult('กำลังส่งคำสั่ง');
      return;
    }

    const result = state.latest_intent;
    if (!result || result.session_id !== mySessionId) {
      if (currentSubmission) {
        setIntentResult('ส่งแล้ว รอผลแปลงคำสั่ง');
      } else {
        setIntentResult(neutral);
      }
      return;
    }

    if (currentSubmission && (
      result.request_id !== currentSubmission.requestId ||
      result.session_id !== currentSubmission.sessionId
    )) {
      setIntentResult('ส่งแล้ว รอผลแปลงคำสั่ง');
      return;
    }

    const messages = {
      NAVIGATE: 'แปลงคำสั่งเป็นการนำทาง',
      CLARIFY: 'ขอข้อมูลเพิ่มเติม',
      UNSUPPORTED: 'คำสั่งนี้ยังไม่รองรับ',
      FAILED: 'แปลงคำสั่งไม่สำเร็จ'
    };
    const rejectionMessages = {
      request_busy: 'กำลังประมวลผลคำสั่งก่อนหน้า',
      robot_busy: 'หุ่นยังไม่ว่าง',
      request_uncertain: 'ยังยืนยันผลคำสั่งก่อนหน้าไม่ได้',
      robot_state_unknown: 'ยังยืนยันสถานะหุ่นไม่ได้',
      robot_not_ready: 'หุ่นยังไม่พร้อมรับคำสั่ง',
      navigation_unavailable: 'ระบบนำทางยังไม่พร้อม'
    };
    const status = result.status === 'FAILED' && rejectionMessages[result.error_code]
      ? rejectionMessages[result.error_code]
      : (messages[result.status] || 'ไม่รู้จักสถานะผลแปลงคำสั่ง');
    let message = typeof result.message === 'string' ? result.message : '';
    let detail = '';

    if (result.status === 'NAVIGATE') {
      const location = Array.isArray(state.locations)
        ? state.locations.find(item => item.id === result.destination_id)
        : null;
      const destination = location && typeof location.label === 'string'
        ? location.label
        : (typeof result.destination_id === 'string' ? result.destination_id : '');
      message = destination ? `ปลายทาง: ${destination}` : '';
      detail = 'ผลนี้บอกว่าระบบแปลงคำสั่งแล้ว ยังไม่ยืนยันว่า Robot รับงานหรือเริ่มเคลื่อนที่';
    } else if (result.status === 'FAILED' && !message) {
      message = 'ลองส่งคำสั่งใหม่อีกครั้ง';
    }

    if (typeof result.error_code === 'string' && result.error_code) {
      detail = detail ? `${detail} · รหัสข้อผิดพลาด: ${result.error_code}` : `รหัสข้อผิดพลาด: ${result.error_code}`;
    }
    setIntentResult(status, message, detail);
  }

  function clearAudioDebug() {
    if (!audioDebugEnabled) return;
    audioDebugPlayer.pause?.();
    audioDebugPlayer.removeAttribute?.('src');
    audioDebugDownload.removeAttribute?.('href');
    if (audioDebugUrl) URL.revokeObjectURL(audioDebugUrl);
    audioDebugUrl = null;
    audioDebugPanel.hidden = true;
  }

  function showRecordedAudio(blob) {
    if (!audioDebugEnabled) return;
    clearAudioDebug();
    audioDebugUrl = URL.createObjectURL(blob);
    audioDebugPlayer.src = audioDebugUrl;
    audioDebugDownload.href = audioDebugUrl;
    const extension = blob.type.includes('mp4') ? 'm4a' : (blob.type.includes('ogg') ? 'ogg' : 'webm');
    audioDebugDownload.download = `voice-debug-${Date.now()}.${extension}`;
    audioDebugDescription.textContent = `${blob.size} bytes · ${blob.type}`;
    audioDebugPanel.hidden = false;
  }

  function resetSubmissionState() {
    cancelRecording();
    clearAudioDebug();
    submissionGeneration += 1;
    pendingSubmission = null;
    currentSubmission = null;
    submissionFeedback = '';
    if (transcriptPreview) transcriptPreview.textContent = 'แตะหนึ่งครั้งเพื่อเริ่มพูด หรือกดค้างไว้ขณะพูด';
    if (sessionFeedbackText) sessionFeedbackText.textContent = '';
  }

  function failSubmission(generation, message) {
    if (generation !== submissionGeneration) return;
    pendingSubmission = null;
    currentSubmission = null;
    submissionFeedback = message;
    if (transcriptPreview) transcriptPreview.textContent = message;
    renderIntentResult(currentState);
  }

  function beginSubmission() {
    submissionGeneration += 1;
    pendingSubmission = { generation: submissionGeneration };
    currentSubmission = null;
    submissionFeedback = '';
    renderIntentResult(currentState);
    return submissionGeneration;
  }

  async function finishSubmission(generation, response) {
    let data = null;
    try {
      data = await response.json();
    } catch (e) {
      data = null;
    }
    if (generation !== submissionGeneration) return data;

    pendingSubmission = null;
    if (!response.ok) {
      submissionFeedback = commandErrorMessage(response.status, data);
      if (response.status === 403) {
        alert('สิทธิ์การควบคุมหมดอายุ หรือมีผู้ชมท่านอื่นกำลังถือสิทธิ์');
      }
    } else if (
      data && typeof data.request_id === 'string' && data.request_id &&
      typeof data.session_id === 'string' && data.session_id === mySessionId
    ) {
      currentSubmission = { requestId: data.request_id, sessionId: data.session_id };
    } else {
      submissionFeedback = 'ส่งคำสั่งแล้ว แต่ยังไม่ได้รับรหัสสำหรับติดตามผล';
    }

    renderIntentResult(currentState);
    return data;
  }

  function commandErrorMessage(status, body) {
    if (status === 403) return 'สิทธิ์การควบคุมหมดอายุ กรุณาเริ่มรับสิทธิ์อีกครั้ง';
    if (status === 422) {
      if (body && typeof body.detail === 'string' && body.detail === 'ไม่พบข้อความจากเสียง') {
        return 'ไม่พบเสียงพูดที่แปลงเป็นข้อความได้ กรุณาพูดใกล้ไมค์แล้วลองใหม่';
      }
      if (body && Array.isArray(body.detail)) {
        const fields = body.detail.flatMap(item => Array.isArray(item.loc) ? item.loc.map(String) : []);
        if (fields.includes('audio')) return 'ไฟล์เสียงไม่ถูกต้อง กรุณาบันทึกเสียงใหม่';
        if (fields.includes('text')) return 'กรุณาตรวจข้อความคำสั่งแล้วลองใหม่';
        return 'ข้อมูลคำขอไม่ครบหรือไม่ถูกต้อง กรุณาลองใหม่';
      }
      return 'ไม่พบข้อความจากเสียง หรือข้อมูลคำขอไม่ถูกต้อง กรุณาลองใหม่';
    }
    if (status === 503) return 'บริการรับหรือแปลงคำสั่งยังไม่พร้อม กรุณาลองใหม่ภายหลัง';
    return `ส่งคำสั่งไม่สำเร็จ (HTTP ${status})`;
  }

  function renderActiveController(state) {
    // Timer display
    if (sessionCountdown && sessionStatusBadge) {
      if (connectionStatus !== 'connected') {
        sessionStatusBadge.className = 'session-badge warning';
        sessionCountdown.textContent = 'ข้อมูลเวลาล่าสุดยังไม่ยืนยัน';
      } else if (state.timer_paused_for_navigation) {
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
      if (connectionStatus === 'connected' && state.show_timeout_warning && !state.timer_paused_for_navigation) {
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
      btn.className = 'chip-btn' + (loc.id === 'start' || loc.id === 'wait' ? ' full-width' : '');
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
        resetSubmissionState();
        setSessionFeedback('ได้รับสิทธิ์ควบคุมแล้ว');
        renderIntentResult(currentState);
        console.log('[Session] Claimed successfully:', data);
      } else if (res.status === 409) {
        setSessionFeedback('มีผู้ถือสิทธิ์ควบคุมอยู่ กรุณารอแล้วลองเริ่มใหม่');
      } else {
        setSessionFeedback(`ขอสิทธิ์ควบคุมไม่สำเร็จ (HTTP ${res.status})`);
      }
    } catch (e) {
      console.error('[Session] Claim failed:', e);
      setSessionFeedback('ติดต่อระบบไม่ได้ จึงยังขอสิทธิ์ควบคุมไม่สำเร็จ');
    }
  }

  async function disconnectSession() {
    if (!confirm('ต้องการจบการใช้งานและส่งต่อคิวให้ผู้ชมท่านอื่นใช่หรือไม่?')) return;
    try {
      const res = await fetch('/api/v1/session/disconnect', {
        method: 'POST',
        headers: {
          'X-Session-Token': mySessionToken || ''
        }
      });
      if (!res.ok) {
        setSessionFeedback(`จบการใช้งานไม่สำเร็จ (HTTP ${res.status})`);
        return;
      }
      mySessionToken = null;
      sessionStorage.removeItem('booth_visitor_session_token');
      resetSubmissionState();
      setSessionFeedback('จบการใช้งานแล้ว');
      renderIntentResult(currentState);
    } catch (e) {
      console.error('[Session] Disconnect failed:', e);
      setSessionFeedback('ติดต่อระบบไม่ได้ จึงยังจบการใช้งานไม่สำเร็จ');
    }
  }

  async function heartbeatSession() {
    try {
      const res = await fetch('/api/v1/session/heartbeat', {
        method: 'POST',
        headers: {
          'X-Session-Token': mySessionToken || ''
        }
      });
      if (!res.ok) {
        setSessionFeedback(`ต่อเวลาไม่สำเร็จ (HTTP ${res.status})`);
        return;
      }
      setSessionFeedback('ต่อเวลาการใช้งานแล้ว');
      if (warningBanner) warningBanner.style.display = 'none';
    } catch (e) {
      console.error('[Session] Heartbeat failed:', e);
      setSessionFeedback('ติดต่อระบบไม่ได้ จึงยังต่อเวลาไม่สำเร็จ');
    }
  }

  function setSessionFeedback(message) {
    if (sessionFeedbackText) sessionFeedbackText.textContent = message;
  }

  // --------------------------------------------------------------------------
  // Push-to-Talk Voice Recording
  // --------------------------------------------------------------------------
  async function startRecording() {
    if (activeRecording) return;
    if (!canSubmitVisitorCommand()) {
      setSessionFeedback('ยังบันทึกเสียงไม่ได้ กรุณารอสถานะและสิทธิ์ควบคุมที่ยืนยันแล้ว');
      return;
    }
    if (audioDebugEnabled) audioDebugPlayer.pause?.();
    const attempt = {
      generation: ++recordingGeneration,
      chunks: [],
      stream: null,
      recorder: null,
      cancelled: false,
      mimeType: ''
    };
    activeRecording = attempt;
    isAcquiringMicrophone = true;
    updateMicControls('acquiring');
    if (transcriptPreview) transcriptPreview.textContent = 'กำลังรอสิทธิ์ใช้ไมโครโฟน...';
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (attempt.cancelled || activeRecording !== attempt ||
          attempt.generation !== recordingGeneration || !canSubmitVisitorCommand()) {
        stopTracks(stream);
        if (activeRecording === attempt) {
          activeRecording = null;
          isAcquiringMicrophone = false;
          updateMicControls('idle');
        }
        return;
      }
      attempt.stream = stream;

      const mimeType = getSupportedMimeType();
      attempt.mimeType = mimeType || 'audio/webm';
      const options = mimeType ? { mimeType } : {};
      const recorder = new MediaRecorder(stream, options);
      attempt.recorder = recorder;

      recorder.ondataavailable = function (e) {
        if (!attempt.cancelled && e.data && e.data.size > 0) {
          attempt.chunks.push(e.data);
        }
      };

      recorder.onstop = async function () {
        stopAttemptTracks(attempt);
        if (attempt.cancelled || activeRecording !== attempt) return;
        if (!canSubmitVisitorCommand()) {
          activeRecording = null;
          isUploadingMicrophone = false;
          updateMicControls('idle');
          const message = 'ข้อมูลหรือสิทธิ์ควบคุมยังไม่ยืนยัน จึงไม่ได้ส่งเสียง';
          if (transcriptPreview) transcriptPreview.textContent = message;
          setSessionFeedback(message);
          return;
        }
        const audioBlob = new Blob(attempt.chunks, { type: attempt.mimeType });
        showRecordedAudio(audioBlob);
        console.log(`[MediaRecorder] Audio recorded: ${audioBlob.size} bytes (${attempt.mimeType})`);
        activeRecording = null;
        isRecording = false;
        isAcquiringMicrophone = false;
        isUploadingMicrophone = true;
        updateMicControls('uploading');
        try {
          await sendVoiceCommand(audioBlob);
        } finally {
          isUploadingMicrophone = false;
          updateMicControls('idle');
        }
      };

      recorder.start();
      isAcquiringMicrophone = false;
      isRecording = true;
      updateMicControls('recording');
      if (transcriptPreview) transcriptPreview.textContent = 'กำลังฟังเสียงของคุณ...';
    } catch (err) {
      console.error('[Audio] Recording start failed:', err);
      attempt.cancelled = true;
      if (attempt.recorder && attempt.recorder.state !== 'inactive') {
        try { attempt.recorder.stop(); } catch (stopError) { console.error('[Audio] Cleanup stop failed:', stopError); }
      }
      stopAttemptTracks(attempt);
      if (activeRecording === attempt) {
        activeRecording = null;
        isAcquiringMicrophone = false;
        isRecording = false;
        updateMicControls('idle');
        const message = 'เปิดไมโครโฟนไม่สำเร็จ กรุณาอนุญาตสิทธิ์หรือใช้ช่องพิมพ์ข้อความ';
        if (transcriptPreview) transcriptPreview.textContent = message;
        setSessionFeedback(message);
      }
    }
  }

  function stopRecording() {
    const attempt = activeRecording;
    if (!attempt) return;
    if (isAcquiringMicrophone) {
      cancelRecording('ยกเลิกการบันทึกก่อนเปิดไมโครโฟน');
      return;
    }
    if (!isRecording || !attempt.recorder) return;
    isRecording = false;
    isUploadingMicrophone = true;
    updateMicControls('uploading');
    try {
      attempt.recorder.stop();
    } catch (e) {
      console.error('[Audio] Stop error:', e);
      cancelRecording('หยุดการบันทึกไม่สำเร็จ');
    }
  }

  function cancelRecording(message = '') {
    const attempt = activeRecording;
    if (!attempt) return;
    attempt.cancelled = true;
    recordingGeneration += 1;
    activeRecording = null;
    isRecording = false;
    isAcquiringMicrophone = false;
    isUploadingMicrophone = false;
    if (attempt.recorder && attempt.recorder.state !== 'inactive') {
      try { attempt.recorder.stop(); } catch (e) { console.error('[Audio] Cancel error:', e); }
    }
    stopAttemptTracks(attempt);
    updateMicControls('idle');
    if (message && transcriptPreview) transcriptPreview.textContent = message;
    if (message) setSessionFeedback(message);
  }

  function stopTracks(stream) {
    if (!stream) return;
    stream.getTracks().forEach(track => track.stop());
  }

  function stopAttemptTracks(attempt) {
    if (attempt.streamReleased) return;
    attempt.streamReleased = true;
    stopTracks(attempt.stream);
  }

  function updateMicControls(mode) {
    if (micButton) {
      micButton.classList.remove('recording');
      if (mode === 'recording') micButton.classList.add('recording');
      micButton.setAttribute('aria-pressed', mode === 'recording' ? 'true' : 'false');
      micButton.setAttribute('aria-label', ({
        idle: 'เริ่มบันทึกเสียง',
        acquiring: 'กำลังรอสิทธิ์ไมโครโฟน กดเพื่อยกเลิก',
        recording: 'กำลังบันทึกเสียง กดเพื่อหยุดและส่ง',
        uploading: 'กำลังส่งเสียง'
      })[mode]);
    }
    if (micLabel) micLabel.textContent = ({
      idle: 'แตะเพื่อพูด',
      acquiring: 'กำลังขอสิทธิ์ไมค์ · แตะเพื่อยกเลิก',
      recording: 'แตะเพื่อหยุดส่ง',
      uploading: 'กำลังส่งเสียง...'
    })[mode];
    if (waveform) {
      if (mode === 'recording') waveform.classList.add('active');
      else waveform.classList.remove('active');
    }
    renderCommandAvailability();
  }

  async function sendVoiceCommand(blob) {
    if (!canSubmitVisitorCommand()) {
      setSessionFeedback('ยังส่งคำสั่งไม่ได้ กรุณารอสถานะและสิทธิ์ควบคุมที่ยืนยันแล้ว');
      return;
    }
    if (transcriptPreview) transcriptPreview.textContent = 'กำลังถอดความและประมวลผล...';
    const generation = beginSubmission();
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

      const data = await finishSubmission(generation, res);
      if (generation === submissionGeneration) {
        if (res.ok && transcriptPreview) {
          transcriptPreview.textContent = data && data.transcript
            ? `ส่งคำสั่งแล้ว: "${data.transcript}"`
            : 'ส่งคำสั่งแล้ว';
        } else if (!res.ok && transcriptPreview) {
          transcriptPreview.textContent = submissionFeedback;
        }
      }
    } catch (e) {
      console.error('[Command] Send voice error:', e);
      failSubmission(generation, 'ส่งเสียงไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ');
    }
  }

  // --------------------------------------------------------------------------
  // Text & Chip Command Submission
  // --------------------------------------------------------------------------
  async function sendTextCommand(text, mode = 'text') {
    if (!text || !text.trim()) return;
    if (!canSubmitVisitorCommand()) {
      setSessionFeedback('ยังส่งคำสั่งไม่ได้ กรุณารอสถานะและสิทธิ์ควบคุมที่ยืนยันแล้ว');
      return;
    }
    const cleanText = text.trim();
    const generation = beginSubmission();

    if (transcriptPreview) transcriptPreview.textContent = `กำลังส่งคำสั่ง: "${cleanText}"`;

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

      const data = await finishSubmission(generation, res);
      if (generation === submissionGeneration) {
        if (res.ok) {
          if (transcriptPreview) transcriptPreview.textContent = `ส่งคำสั่งแล้ว: "${cleanText}"`;
          if (textInputField) textInputField.value = '';
        } else if (transcriptPreview) {
          transcriptPreview.textContent = submissionFeedback;
        }
      }
    } catch (e) {
      console.error('[Command] Send text error:', e);
      failSubmission(generation, 'ส่งคำสั่งไม่สำเร็จ กรุณาตรวจการเชื่อมต่อ');
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

    function toggleRecording() {
      if (activeRecording) stopRecording();
      else startRecording();
    }

    micButton.addEventListener('pointerdown', (e) => {
      if (micButton.disabled) return;
      e.preventDefault();
      if (micButton.setPointerCapture && Number.isInteger(e.pointerId)) {
        try { micButton.setPointerCapture(e.pointerId); } catch (err) { /* Pointer may already be released. */ }
      }
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
        toggleRecording();
      }
    });

    micButton.addEventListener('pointercancel', () => {
      if (pressTimer) clearTimeout(pressTimer);
      pressTimer = null;
      cancelRecording('การบันทึกเสียงถูกยกเลิก');
      isHoldMode = false;
    });

    micButton.addEventListener('click', (e) => {
      if (e.detail > 0) return;
      toggleRecording();
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
    .then(r => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(state => {
      if (!isValidStateSnapshot(state)) throw new Error('Invalid state snapshot');
      if (!receivedWebSocketState) renderState(state);
      if (!receivedWebSocketState && connectionStatus === 'connecting') setConnectionStatus('connected');
    })
    .catch(err => {
      console.error('Initial state fetch error:', err);
      if (!receivedWebSocketState) setConnectionStatus('disconnected');
    });

})();

'use strict';

globalThis.createVisitorRecording = function ({ canSubmitVisitorCommand, setSessionFeedback,
    audioDebugEnabled, audioDebugPlayer, transcriptPreview, updateMicControls,
    showRecordedAudio, sendVoiceCommand }) {
  // Audio Recording State
  let isRecording = false;
  let isAcquiringMicrophone = false;
  let isUploadingMicrophone = false;
  let recordingGeneration = 0;
  let activeRecording = null;

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

  async function startRecording(gesture = 'tap') {
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
      mimeType: '',
      gesture
    };
    activeRecording = attempt;
    isAcquiringMicrophone = true;
    updateMicControls('acquiring', attempt.gesture);
    if (transcriptPreview) transcriptPreview.textContent = 'กำลังรอสิทธิ์ใช้ไมโครโฟน…';
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
      updateMicControls('recording', attempt.gesture);
      if (transcriptPreview) transcriptPreview.textContent = 'กำลังฟัง…';
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

  return {
    startRecording, stopRecording, cancelRecording,
    get active() { return activeRecording !== null; },
    get isRecording() { return isRecording; },
    get isAcquiringMicrophone() { return isAcquiringMicrophone; },
    get isUploadingMicrophone() { return isUploadingMicrophone; }
  };
};

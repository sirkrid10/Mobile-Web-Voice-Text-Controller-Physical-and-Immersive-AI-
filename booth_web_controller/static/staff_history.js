(function () {
  window.StaffHistory = { create({ onUnauthorized }) {
    const log = document.getElementById('staff-dialogue-history');
    const feedback = document.getElementById('staff-history-feedback');
    const refreshButton = document.getElementById('staff-history-refresh');
    let pin = '', generation = 0, timer = null, pending = false, controller = null;
    const labels = { request: 'ผู้ใช้', intent: 'Intent', dispatch: 'ส่ง Action', subtitle: 'Subtitle' };

    async function refresh() {
      if (!pin || pending) return;
      const mine = generation;
      pending = true;
      refreshButton.disabled = true;
      const abort = new AbortController(); controller = abort;
      const timeout = setTimeout(() => abort.abort(), 8000);
      try {
        const response = await fetch('/api/v1/staff/history?limit=50', { headers: { 'X-Staff-Pin': pin }, signal: abort.signal });
        if (mine !== generation) return;
        if (response.status === 401) { onUnauthorized(); return; }
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        if (mine !== generation) return;
        if (!Array.isArray(data.events)) throw new Error('รูปแบบประวัติไม่ถูกต้อง');
        const text = data.events.map(event => {
          const heading = [new Date(event.received_at * 1000).toLocaleString('th-TH'), labels[event.kind] || event.kind,
            event.input_mode, event.status, event.request_id].filter(Boolean).join(' · ');
          return `${heading}\n${event.text || event.destination_id || '—'}${event.error_code ? `\nรหัส: ${event.error_code}` : ''}`;
        }).join('\n\n') || 'ยังไม่มีประวัติหลังเปิดระบบเก็บข้อมูล';
        if (log.textContent !== text) {
          const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
          log.textContent = text;
          if (atBottom) log.scrollTop = log.scrollHeight;
        }
        feedback.textContent = data.available ? `แสดง ${data.events.length} เหตุการณ์ล่าสุด · เก็บสูงสุด ${data.capacity} เหตุการณ์` : 'พื้นที่เก็บประวัติไม่พร้อม ข้อมูลอาจไม่ครบ';
      } catch (error) {
        if (mine === generation) feedback.textContent = `อ่านประวัติไม่ได้: ${error.message}`;
      } finally {
        clearTimeout(timeout);
        if (mine === generation) { pending = false; controller = null; refreshButton.disabled = !pin; }
      }
    }

    refreshButton.disabled = true;
    refreshButton.addEventListener('click', refresh);
    return {
      start(value) { this.stop(); pin = value; refresh(); timer = setInterval(refresh, 5000); },
      stop() {
        pin = ''; generation++; pending = false;
        if (timer) clearInterval(timer); timer = null;
        if (controller) controller.abort(); controller = null;
        refreshButton.disabled = true; log.textContent = 'ยืนยัน PIN เพื่อดูประวัติ'; feedback.textContent = '';
      }
    };
  } };
})();

/* Staff-only process controls and cached connectivity inspection. */
(function () {
  window.StaffSystem = { create({ onUnauthorized, onSubtitleChange }) {
    const get = id => document.getElementById(id);
    const buttons = [...document.querySelectorAll('[data-node-action], [data-agent-mode], #staff-system-refresh')];
    let pin = '', generation = 0, version = 0, busy = false, polling = false, timer = null, latest = null;
    const time = value => value ? new Date(value * 1000).toLocaleTimeString('th-TH') : 'ยังไม่มีข้อมูล';
    const yesNo = value => value === true ? 'ได้' : value === false ? 'ไม่ได้' : 'ยังยืนยันไม่ได้';
    const set = (id, value) => { if (get(id).textContent !== value) get(id).textContent = value; };
    const rpcLabels = { responding: 'ตอบกลับได้', not_observed: 'ยังไม่พบ service', timeout: 'ไม่ตอบภายในเวลา',
      failed: 'ติดต่อไม่สำเร็จ', invalid_response: 'คำตอบไม่ครบ', unavailable: 'ไม่ได้ตรวจใน Mock' };
    const states = { running: 'Process ทำงานอยู่', stopped: 'ปิดอยู่', failed: 'Process ล้มเหลว', external: 'เปิดจาก terminal ภายนอก', starting: 'กำลังเปิด', stopping: 'กำลังปิด', killing: 'กำลังบังคับปิด' };

    function render(data) {
      latest = data;
      window.StaffGuide?.setPaths(data);
      const manager = data.processes, ros = data.ros || {}, tail = data.tailscale || {}, vr = data.vr || {};
      set('staff-system-mode', `${data.mock ? 'Mock · ' : ''}${manager.mode === 'manual' ? 'Manual — เปิด node เองใน terminal' : 'Automatic — Backend ดูแล node'}`);
      set('staff-system-note', manager.problem || data.error || (manager.enabled
        ? 'Stop/Kill จะจำว่าให้ปิดไว้ ส่วน Restart ของ Subtitle จะกลับโหมดเริ่มต้น'
        : 'ตัวดูแล process ไม่ได้เปิดใช้งาน โหมด Mock จะไม่เปิด ROS node จริง'));
      set('staff-system-checked', `ตรวจล่าสุด: ${time(data.checked_at)}`);
      for (const node of ['intent', 'subtitle']) {
        const info = manager.nodes[node];
        set(`staff-${node}-process`, `${states[info.status] || info.status}${info.pid ? ` · PID ${info.pid}` : ''}`);
        get(`staff-${node}-process`).dataset.level = info.status === 'running' ? 'ok' : info.status === 'failed' ? 'error' : 'unknown';
        set(`staff-${node}-rpc`, `ROS: ${rpcLabels[ros[node]] || 'กำลังรอตรวจ'}`);
        set(`staff-${node}-detail`, info.last_error || (info.external_pids.length
          ? `PID ภายนอก: ${info.external_pids.join(', ')} · ระบบจะไม่ปิดหรือเปิดซ้อนตัวนี้`
          : `เริ่ม: ${time(info.started_at)} · Restart: ${info.restart_count} · Exit code: ${info.exit_code ?? '—'}`));
        const log = info.logs.map(line => `${time(line.at)} ${line.text}`).join('\n') || 'ยังไม่มี log จาก process ที่ Backend ดูแล';
        const element = get(`staff-${node}-logs`);
        if (element.textContent !== log) {
          const atBottom = element.scrollTop + element.clientHeight >= element.scrollHeight - 20;
          element.textContent = log;
          if (atBottom) element.scrollTop = element.scrollHeight;
        }
      }
      const labels = { connected: 'เชื่อม Tailscale แล้ว', disconnected: 'Tailscale ยังไม่เชื่อม', checking: 'กำลังตรวจ',
        unknown: 'ยังยืนยัน Tailscale ไม่ได้', mock: 'ไม่ได้ตรวจใน Mock' };
      set('staff-health-tailscale', labels[tail.status] || 'ยังไม่มีข้อมูล');
      set('staff-health-vm', tail.server
        ? `VM ${tail.server} · รายงาน Online: ${yesNo(tail.server_online)} · Ping: ${yesNo(tail.reachable)}`
        : tail.detail || 'ยังไม่มีข้อมูล VM');
      set('staff-health-ros', `ROS domain: ${ros.domain_id ?? '—'} · Discovery: ${ros.discovery_server || 'local / ไม่ได้ตั้งค่า'}`);
      set('staff-health-action', `พบ Action server: ${yesNo(ros.action_server_observed)} · การพบ server ยังไม่ยืนยันว่าหุ่นพร้อมเดิน`);
      set('staff-health-graph', `ROS graph: ${(ros.graph_nodes || []).join(', ') || 'ยังไม่พบข้อมูล'} (ใช้ประกอบการตรวจเท่านั้น)`);
      const age = ros.robot_source_age_sec;
      set('staff-health-robot', data.mock ? 'Robot: ข้อมูลจำลอง' : ros.robot_fresh
        ? `Robot: ได้รับสถานะสด · ${ros.robot_phase} · พร้อมรับ Goal: ${yesNo(ros.robot_ready_for_goal)}`
        : 'Robot: ยังไม่มีสถานะสดที่ยืนยันได้');
      set('staff-health-robot-age', `อายุข้อมูลต้นทาง: ${age == null ? '—' : `${age.toFixed(1)} วินาที`} · รับล่าสุด: ${time(ros.robot_received_at)}${age != null && age < -0.6 ? ' · นาฬิกาต้นทางเดินนำเกินช่วงที่รองรับ' : ''}`);
      set('staff-health-vr', `VR WebSocket: ${vr.connections || 0} การเชื่อมต่อ · ส่งล่าสุด: ${time(vr.last_sent_at)} · ลำดับ: ${vr.last_sent_sequence ?? '—'}`);
      buttons.forEach(button => {
        const action = button.dataset.nodeAction;
        const node = button.dataset.node;
        const info = node ? manager.nodes[node] : null;
        button.disabled = busy || !manager.enabled || (action && (
          ['external', 'starting', 'stopping', 'killing'].includes(info.status) || (['start', 'restart'].includes(action) && manager.mode === 'manual') ||
          (action === 'start' && info.status === 'running') ||
          (['stop', 'kill'].includes(action) && info.status !== 'running')
        ));
      });
      get('staff-system-refresh').disabled = busy;
    }

    async function request(path, body) {
      const mine = generation, key = pin;
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), body ? 20000 : 8000);
      try {
        const response = await fetch(path, { method: body ? 'POST' : 'GET', signal: controller.signal,
          headers: { 'X-Staff-Pin': key, ...(body ? { 'Content-Type': 'application/json' } : {}) },
          ...(body ? { body: JSON.stringify(body) } : {}) });
        if (mine !== generation || key !== pin) return null;
        if (response.status === 401) { onUnauthorized(); return null; }
        const data = await response.json();
        if (mine !== generation || key !== pin) return null;
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `HTTP ${response.status}`);
        return data;
      } finally { clearTimeout(timeout); }
    }

    async function refresh() {
      if (!pin || busy || polling) return;
      polling = true;
      const observed = version, mine = generation;
      try {
        const data = await request('/api/v1/staff/system');
        if (data && observed === version) {
          render(data);
          set('staff-system-feedback', '');
        }
      } catch (error) {
        if (mine === generation && observed === version) set('staff-system-feedback', `อ่านสถานะไม่ได้: ${error.message} · ข้อมูลที่แสดงอาจค้าง`);
      } finally { if (mine === generation) polling = false; }
    }

    async function operate(path, body, subtitleChanged = false) {
      if (!pin || busy || !latest) return;
      busy = true;
      version += 1;
      const mine = generation;
      render(latest);
      set('staff-system-feedback', 'กำลังดำเนินการ…');
      try {
        const data = await request(path, body);
        if (data) {
          render(data);
          set('staff-system-feedback', 'ดำเนินการแล้ว ตรวจสถานะ process และ ROS ด้านล่าง');
          if (subtitleChanged) onSubtitleChange();
        }
      } catch (error) {
        if (mine === generation) set('staff-system-feedback', `ดำเนินการไม่สำเร็จ: ${error.message}`);
      } finally {
        if (mine === generation) {
          busy = false;
          if (latest) render(latest);
        }
      }
    }

    buttons.forEach(button => {
      if (button.dataset.nodeAction) button.addEventListener('click', () => operate(
        `/api/v1/staff/system/nodes/${button.dataset.node}/${button.dataset.nodeAction}`, {}, button.dataset.node === 'subtitle'));
      if (button.dataset.agentMode) button.addEventListener('click', () => operate(
        '/api/v1/staff/system/mode', { mode: button.dataset.agentMode }, true));
    });
    get('staff-system-refresh').addEventListener('click', refresh);
    buttons.forEach(button => { button.disabled = button.id !== 'staff-system-refresh'; });
    return {
      start(value) { this.stop(); pin = value; refresh(); timer = setInterval(refresh, 5000); },
      stop() { pin = ''; generation += 1; version += 1; busy = false; polling = false; latest = null; if (timer) clearInterval(timer); timer = null; }
    };
  } };
})();

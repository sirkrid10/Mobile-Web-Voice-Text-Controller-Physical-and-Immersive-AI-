/* Read-only runbook: tab navigation and copying commands never execute them. */
(function () {
  const tabs = [...document.querySelectorAll('.staff-tabs [role="tab"]')];
  const get = id => document.getElementById(id);
  function select(index, focus = false) {
    tabs.forEach((tab, position) => {
      const selected = position === index;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
      get(tab.getAttribute('aria-controls')).hidden = !selected;
    });
    if (focus) tabs[index].focus();
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => select(index));
    tab.addEventListener('keydown', event => {
      const next = { ArrowRight: (index + 1) % tabs.length, ArrowLeft: (index + tabs.length - 1) % tabs.length,
        Home: 0, End: tabs.length - 1 }[event.key];
      if (next !== undefined) { event.preventDefault(); select(next, true); }
    });
  });

  const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
  function renderCommands(paths) {
    const llm = paths ? quote(paths.workspace) : '~/ros2_ws/turtlebot-llm';
    const backend = paths ? quote(paths.backend) : '~/ros2_ws/Mobile-Web-Voice-Text-Controller-Physical-and-Immersive-AI-';
    const cdBackend = `cd ${backend}\n`;
    const tool = 'python3 booth_web_controller/tools/agent_nodes.py';
    const server = paths?.server ? ` ${quote(paths.server)}` : '';
    const launcher = `AGENT_WORKSPACE=${llm} bash booth_web_controller/run_tailscale.sh${server}`;
    const commands = {
      startup: cdBackend + launcher,
      status: cdBackend + `${tool} status --workspace ${llm}`,
      stop: cdBackend + `${tool} stop-all --workspace ${llm}`,
      kill: cdBackend + `${tool} kill-all --workspace ${llm}`,
      intent: `cd ${llm}\nbash ./run_tailscale.sh intent${server}`,
      subtitle: `cd ${llm}\nbash ./run_tailscale.sh subtitle${server}`,
      'manual-backend': cdBackend + `MANAGE_AGENT_NODES=false ${launcher}`,
      automatic: cdBackend + `${tool} automatic --workspace ${llm}\n${launcher}`,
      network: 'tailscale status\ntailscale ip -4' + (server ? `\ntailscale ping${server}` : ''),
      profile: `cd ${llm}\nsource ./setup_tailscale_ros.sh${server}\nros2 node list --no-daemon`,
      build: `cd ${llm}\nsource /opt/ros/jazzy/setup.bash\nsource .venv/bin/activate\ncolcon --log-base log-colcon build --build-base build-colcon --install-base install-colcon --packages-select ai_interfaces agent_pkg`
      , 'kv-fallback': `cd ${backend}/cloudflare/robot-link\nnpx wrangler kv key put robot_url 'https://<quick-tunnel>.trycloudflare.com/' --namespace-id '<KV_NAMESPACE_ID>'`
    };
    Object.entries(commands).forEach(([name, command]) => { get(`guide-command-${name}`).textContent = command; });
  }
  renderCommands(null);
  document.querySelectorAll('[data-copy-command]').forEach(button => {
    button.addEventListener('click', async () => {
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(get(button.dataset.copyCommand).textContent);
        get('staff-guide-feedback').textContent = 'คัดลอกแล้ว นำไปวางใน Ubuntu WSL ได้ ยังไม่มีการรันคำสั่ง';
      } catch (_) {
        get('staff-guide-feedback').textContent = 'คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกข้อความในกรอบแล้วคัดลอกเอง';
      }
    });
  });
  let pathsKey = '';
  window.StaffGuide = {
    reset() { select(0); },
    setPaths(data) {
      const workspace = data.processes?.workspace, backend = data.backend_directory;
      if (typeof workspace !== 'string' || !workspace.startsWith('/') || typeof backend !== 'string' || !backend.startsWith('/')) return;
      const address = /^(100\.(\d{1,3})\.\d{1,3}\.\d{1,3}):11811$/.exec(data.ros?.discovery_server || '');
      const server = address && Number(address[2]) >= 64 && Number(address[2]) <= 127 ? address[1] : '';
      const key = JSON.stringify([workspace, backend, server]);
      if (key === pathsKey) return;
      pathsKey = key;
      renderCommands({ workspace, backend, server });
      get('staff-guide-path-note').textContent = `ใช้โฟลเดอร์ของ Backend ที่กำลังรัน: ${backend} · LLM: ${workspace} หากเปลี่ยนตำแหน่งติดตั้ง ให้ตรวจเส้นทางก่อนรัน`;
    }
  };
})();

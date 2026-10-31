"""PIN-protected controls drive actual disposable processes, without ROS or Robot."""
from app import runtime
import asyncio
import sys

from fastapi.testclient import TestClient

from app import main
from app.agent_processes import AgentProcesses
from app.config import settings
from app.session_manager import SessionManager


def test_system_endpoints_auth_whitelist_and_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    root = tmp_path / 'llm'
    root.mkdir()
    commands = {name: [sys.executable, '-u', '-c', 'import time; print("ready", flush=True); time.sleep(300)']
                for name in ('intent', 'subtitle')}
    monkeypatch.setattr(settings, 'USE_MOCK_ROS2', True)
    monkeypatch.setattr(settings, 'ENABLE_TUNNEL', False)
    monkeypatch.setattr(runtime, 'session_manager', SessionManager())
    monkeypatch.setattr(runtime, 'AgentProcesses', lambda *a, **kw: AgentProcesses(root, enabled=True, commands=commands))
    headers = {'X-Staff-Pin': settings.STAFF_PIN}
    with TestClient(main.app) as client:
        health = client.get('/api/v1/health')
        assert health.status_code == 200
        assert health.json()['service'] == 'mobile-web-voice-text-controller'
        first_instance_id = health.json()['instance_id']
        assert first_instance_id
        assert client.get('/api/v1/health').json()['instance_id'] == first_instance_id
        assert client.get('/api/v1/staff/system').status_code == 401
        assert client.post('/api/v1/staff/system/nodes/intent/kill', json={}).status_code == 401
        assert client.post('/api/v1/staff/system/mode', json={'mode': 'manual'}).status_code == 401
        session_before_health = client.get('/api/v1/state').json()
        assert client.get('/api/v1/health').status_code == 200
        assert client.get('/api/v1/state').json() == session_before_health
        state = client.get('/api/v1/staff/system', headers=headers).json()
        assert state['tunnel']['enabled'] is False
        assert 'CLOUDFLARE_API_TOKEN' not in str(state)
        assert client.get('/api/v1/health').json()['instance_id'] == first_instance_id
        original = state['processes']['nodes']['intent']['pid']
        assert original
        assert client.post('/api/v1/staff/system/nodes/backend/kill', headers=headers, json={}).status_code == 422
        assert client.post('/api/v1/staff/system/nodes/intent/shell', headers=headers, json={}).status_code == 422
        assert client.post('/api/v1/staff/system/mode', headers=headers, json={'mode': 'manual', 'command': 'bad'}).status_code == 422
        response = client.post('/api/v1/staff/system/nodes/intent/restart', headers=headers, json={})
        assert response.status_code == 200
        assert response.json()['processes']['nodes']['intent']['pid'] != original
        response = client.post('/api/v1/staff/system/nodes/intent/kill', headers=headers, json={})
        assert response.status_code == 200
        assert response.json()['processes']['nodes']['intent']['pid'] is None
        response = client.post('/api/v1/staff/system/mode', headers=headers, json={'mode': 'manual'})
        assert response.json()['processes']['mode'] == 'manual'
        assert client.post('/api/v1/staff/system/nodes/intent/start', headers=headers, json={}).status_code == 409
        assert client.post('/api/v1/staff/system/mode', headers=headers, json={'mode': 'automatic'}).status_code == 200
    assert runtime.agent_processes is None

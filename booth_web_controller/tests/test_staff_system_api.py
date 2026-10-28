"""PIN-protected controls drive actual disposable processes, without ROS or Robot."""
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
    monkeypatch.setattr(main, 'session_manager', SessionManager())
    monkeypatch.setattr(main, 'AgentProcesses', lambda *a, **kw: AgentProcesses(root, enabled=True, commands=commands))
    headers = {'X-Staff-Pin': settings.STAFF_PIN}
    with TestClient(main.app) as client:
        assert client.get('/api/v1/staff/system').status_code == 401
        assert client.post('/api/v1/staff/system/nodes/intent/kill', json={}).status_code == 401
        assert client.post('/api/v1/staff/system/mode', json={'mode': 'manual'}).status_code == 401
        state = client.get('/api/v1/staff/system', headers=headers).json()
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
    assert main.agent_processes is None

"""Real local child processes verify ownership, stop, restart and terminal recovery."""
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from app.agent_processes import AgentProcesses, ProcessControlError
from app.agent_runtime import RuntimeRegistry, identity, signal_owned


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    root = tmp_path / 'llm'
    root.mkdir()
    (root / '.env').write_text('GROQ_API_KEY=test-intent-private-key\nGROQ_SUBTITLE_API_KEY=test-subtitle-private-key\n')
    script = root / 'worker.py'
    script.write_text('import os,time\nprint("GROQ_API_KEY="+os.environ.get("GROQ_API_KEY", ""),flush=True)\nprint("ready",flush=True)\ntime.sleep(300)\n')
    return root, {name: [sys.executable, '-u', str(script)] for name in ('intent', 'subtitle')}


async def wait_for(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.03)
    raise AssertionError('Timed out waiting for child')


def test_lifecycle_duplicate_start_manual_persistence_and_redaction(workspace, monkeypatch):
    root, commands = workspace
    monkeypatch.setenv('GROQ_API_KEY', 'backend-stt-must-not-leak')

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            first = manager.snapshot()['nodes']['intent']['pid']
            assert first
            await manager.control('intent', 'start')
            assert manager.snapshot()['nodes']['intent']['pid'] == first
            await wait_for(lambda: any(line['text'] == 'ready' for line in manager.snapshot()['nodes']['intent']['logs']))
            text = json.dumps(manager.snapshot())
            assert 'test-intent-private-key' not in text
            assert 'backend-stt-must-not-leak' not in text
            assert '[REDACTED]' in text
            await manager.control('intent', 'restart')
            assert manager.snapshot()['nodes']['intent']['pid'] != first
            assert identity(first) is None
            assert manager.snapshot()['nodes']['intent']['restart_count'] == 1
            await manager.control('subtitle', 'kill')
            assert manager.snapshot()['nodes']['subtitle']['status'] == 'stopped'
            await manager.set_mode('manual')
            assert all(n['pid'] is None for n in manager.snapshot()['nodes'].values())
            with pytest.raises(ProcessControlError, match='Manual'):
                await manager.control('intent', 'start')
        finally:
            await manager.close()
        replacement = AgentProcesses(root, enabled=True, commands=commands)
        await replacement.open()
        try:
            assert replacement.snapshot()['mode'] == 'manual'
            assert replacement.snapshot()['nodes']['intent']['pid'] is None
            await replacement.set_mode('automatic')
            assert replacement.snapshot()['nodes']['intent']['pid']
        finally:
            await replacement.close()
    asyncio.run(run())


def test_single_owner_and_stop_preference_survive_backend_restart(workspace):
    root, commands = workspace

    async def run():
        first = AgentProcesses(root, enabled=True, commands=commands)
        second = AgentProcesses(root, enabled=True, commands=commands)
        await first.open()
        try:
            await second.open()
            assert not second.snapshot()['enabled']
            with pytest.raises(ProcessControlError):
                await second.control('intent', 'kill')
            pid = first.snapshot()['nodes']['intent']['pid']
            assert identity(pid)
            await first.control('intent', 'stop')
        finally:
            await second.close()
            await first.close()
        third = AgentProcesses(root, enabled=True, commands=commands)
        await third.open()
        try:
            assert third.snapshot()['nodes']['intent']['pid'] is None
            assert third.snapshot()['nodes']['subtitle']['pid']
        finally:
            await third.close()
    asyncio.run(run())


def test_external_process_is_never_adopted_killed_or_duplicated(workspace):
    root, commands = workspace
    foreign_script = root / 'intent_node'
    foreign_script.write_text('import time\ntime.sleep(300)\n')
    foreign = subprocess.Popen([sys.executable, str(foreign_script)], start_new_session=True)
    try:
        async def run():
            manager = AgentProcesses(root, enabled=True, commands=commands)
            await manager.open()
            try:
                info = manager.snapshot()['nodes']['intent']
                assert info['status'] == 'external'
                assert foreign.pid in info['external_pids']
                assert info['pid'] is None
                await manager.control('intent', 'kill')
                assert foreign.poll() is None
                await manager.set_mode('manual')
                assert foreign.poll() is None
            finally:
                await manager.close()
        asyncio.run(run())
    finally:
        os.killpg(foreign.pid, signal.SIGKILL)
        foreign.wait()


def test_terminal_kill_all_works_without_http_and_does_not_respawn(workspace):
    root, commands = workspace
    tool = Path(__file__).resolve().parents[1] / 'tools/agent_nodes.py'

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            pids = [n['pid'] for n in manager.snapshot()['nodes'].values()]
            result = await asyncio.to_thread(subprocess.run, [sys.executable, str(tool), 'kill-all', '--workspace', str(root)],
                                             capture_output=True, text=True, check=True)
            assert json.loads(result.stdout)['mode'] == 'manual'
            await wait_for(lambda: all(identity(pid) is None for pid in pids))
            assert manager.snapshot()['mode'] == 'manual'
            with pytest.raises(ProcessControlError):
                await manager.control('intent', 'restart')
            await asyncio.sleep(0.1)
            assert all(n['pid'] is None for n in manager.snapshot()['nodes'].values())
        finally:
            await manager.close()
    asyncio.run(run())


def test_registry_refuses_stale_identity(workspace):
    root, _ = workspace
    worker = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], start_new_session=True)
    try:
        assert not signal_owned({'pid': worker.pid, 'start_ticks': 'old-process'}, signal.SIGKILL)
        assert not signal_owned({'pid': worker.pid}, signal.SIGKILL)
        assert worker.poll() is None
    finally:
        worker.kill()
        worker.wait()


def test_process_crash_remains_failed_without_restart_loop(workspace):
    root, commands = workspace
    commands['intent'] = [sys.executable, '-c', 'raise SystemExit(7)']

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            await wait_for(lambda: manager.snapshot()['nodes']['intent']['exit_code'] == 7)
            assert manager.snapshot()['nodes']['intent']['status'] == 'failed'
            assert manager.snapshot()['nodes']['intent']['restart_count'] == 0
        finally:
            await manager.close()
    asyncio.run(run())


def test_reclaims_verified_orphan_before_starting_replacement(workspace):
    root, commands = workspace
    registry = RuntimeRegistry(root)
    orphan = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'], start_new_session=True)
    registry.write('processes.json', {'intent': {'pid': orphan.pid, 'start_ticks': identity(orphan.pid)}})
    try:
        async def run():
            manager = AgentProcesses(root, enabled=True, commands=commands)
            await manager.open()
            try:
                assert identity(orphan.pid) is None
                assert manager.snapshot()['nodes']['intent']['pid'] != orphan.pid
            finally:
                await manager.close()
        asyncio.run(run())
    finally:
        if orphan.poll() is None:
            orphan.kill()
        orphan.wait()


def test_terminal_with_different_runtime_env_still_finds_managed_processes(workspace):
    root, commands = workspace
    tool = Path(__file__).resolve().parents[1] / 'tools/agent_nodes.py'

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            result = await asyncio.to_thread(subprocess.run,
                [sys.executable, str(tool), 'kill-all', '--workspace', str(root)],
                env={**os.environ, 'XDG_RUNTIME_DIR': str(root / 'other-session')},
                capture_output=True, text=True, check=True)
            assert set(json.loads(result.stdout)['signaled']) == {'intent', 'subtitle'}
            await wait_for(lambda: all(n['pid'] is None for n in manager.snapshot()['nodes'].values()))
            assert manager.snapshot()['mode'] == 'manual'
        finally:
            await manager.close()
    asyncio.run(run())


def test_stop_all_escalates_when_child_ignores_sigterm(workspace):
    root, commands = workspace
    stubborn = root / 'stubborn.py'
    stubborn.write_text('import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nprint("ready",flush=True)\ntime.sleep(300)\n')
    commands['intent'] = [sys.executable, '-u', str(stubborn)]
    tool = Path(__file__).resolve().parents[1] / 'tools/agent_nodes.py'

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            await wait_for(lambda: any(line['text'] == 'ready' for line in manager.snapshot()['nodes']['intent']['logs']))
            pid = manager.snapshot()['nodes']['intent']['pid']
            await asyncio.to_thread(subprocess.run, [sys.executable, str(tool), 'stop-all', '--workspace', str(root)],
                                    capture_output=True, check=True)
            await wait_for(lambda: identity(pid) is None)
            assert manager.snapshot()['mode'] == 'manual'
        finally:
            await manager.close()
    asyncio.run(run())


def test_foreign_duplicate_does_not_hide_controls_for_owned_process(workspace):
    root, commands = workspace
    script = root / 'intent_node'
    script.write_text('import time\ntime.sleep(300)\n')

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        foreign = subprocess.Popen([sys.executable, str(script)], start_new_session=True)
        try:
            await manager.refresh_external()
            info = manager.snapshot()['nodes']['intent']
            assert info['status'] == 'running'
            assert info['pid'] is not None
            assert foreign.pid in info['external_pids']
            await manager.control('intent', 'kill')
            assert foreign.poll() is None
            assert manager.snapshot()['nodes']['intent']['status'] == 'external'
        finally:
            foreign.kill()
            foreign.wait()
            await manager.close()
    asyncio.run(run())


def test_canceling_a_command_waiting_for_cli_lock_releases_the_lock(workspace):
    root, commands = workspace

    async def run():
        manager = AgentProcesses(root, enabled=True, commands=commands)
        await manager.open()
        try:
            with manager.registry.transaction():
                pending = asyncio.create_task(manager.control('intent', 'stop'))
                await asyncio.sleep(0.05)
                pending.cancel()
                await asyncio.sleep(0)
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(pending, 2)
            await asyncio.wait_for(manager.control('intent', 'stop'), 2)
            assert manager.snapshot()['nodes']['intent']['pid'] is None
        finally:
            await manager.close()
    asyncio.run(run())

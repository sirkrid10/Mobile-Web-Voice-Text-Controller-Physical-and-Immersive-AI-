"""Own only Backend-started Intent/Subtitle processes and their bounded logs."""

import asyncio
from collections import deque
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import signal
import time

from dotenv import dotenv_values

from app.agent_runtime import NODES, RuntimeRegistry, external_nodes, identity, signal_owned


class ProcessControlError(RuntimeError):
    pass


class AgentProcesses:
    def __init__(self, workspace, *, enabled=False, clock_skew=0.6, commands=None, probe_external=None):
        self.workspace = Path(workspace).expanduser().resolve()
        self.enabled = enabled
        self.clock_skew = clock_skew
        self.registry = RuntimeRegistry(self.workspace) if enabled else None
        self.owns_lock = False
        self.problem = ''
        self._lock = asyncio.Lock()
        self._tasks = set()
        self._commands = commands
        self._probe_external = probe_external
        self._closing = False
        self._entries = {name: {
            'process': None, 'started_at': None, 'restart_count': 0,
            'logs': deque(maxlen=80), 'external_pids': [], 'last_error': '',
            'transition': None,
        } for name in NODES}
        self._secrets = []

    @asynccontextmanager
    async def _transaction(self):
        async with self._lock:
            transaction = self.registry.transaction()
            acquisition = asyncio.create_task(asyncio.to_thread(transaction.__enter__))
            try:
                await asyncio.shield(acquisition)
            except asyncio.CancelledError:
                await acquisition
                transaction.__exit__(None, None, None)
                raise
            try:
                yield
            finally:
                transaction.__exit__(None, None, None)

    def _log(self, name, text):
        if len(text) > 8192:
            text = '[oversized log line suppressed]'
        for secret in self._secrets:
            text = text.replace(secret, '[REDACTED]')
        if re.search(r'''(?i)(authorization|api[_-]?key|password|token|secret)["']?\s*[:=]''', text):
            text = '[REDACTED] sensitive log line'
        self._entries[name]['logs'].append({'at': time.time(), 'text': text[:2000]})

    def _environment(self):
        env = os.environ.copy()
        env.pop('STAFF_PIN', None)
        values = dotenv_values(self.workspace / '.env')
        # Backend's STT key must never become Intent's key.
        for key in ('GROQ_API_KEY', 'GROQ_SUBTITLE_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY'):
            env[key] = values.get(key) or ''
        for key, value in values.items():
            if value is not None and key.startswith(('GROQ_', 'GOOGLE_', 'SUBTITLE_', 'LLM_')):
                env[key] = value
        env['PYTHONUNBUFFERED'] = '1'
        self._secrets = [value for key, value in env.items() if value and len(value) >= 6
                         and any(word in key.upper() for word in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))]
        return env

    async def refresh_external(self):
        found = await asyncio.to_thread(external_nodes, os.environ.get('ROS_DOMAIN_ID', '0'))
        for name in NODES:
            proc = self._entries[name]['process']
            owned_pid = proc.pid if proc else None
            self._entries[name]['external_pids'] = [pid for pid in found[name] if pid != owned_pid]

    def _record_process(self, name, proc):
        records = self.registry.read('processes.json', {})
        records[name] = {'pid': proc.pid, 'start_ticks': identity(proc.pid), 'started_at': time.time()}
        self.registry.write('processes.json', records)

    async def open(self):
        if not self.enabled:
            return
        self.owns_lock = self.registry.acquire_owner()
        if not self.owns_lock:
            self.problem = 'Another Backend owns node control for this workspace'
            return
        try:
            async with self._transaction():
                # Recover only verified children of the previous Backend owner.
                for record in self.registry.read('processes.json', {}).values():
                    await self._stop_record(record, force=False)
                preferences = self.registry.preferences()
                if not preferences['manual']:
                    for name in NODES:
                        if name not in preferences['disabled']:
                            await self._start(name)
        except Exception:
            await self.close()
            raise

    async def _drain(self, name, proc):
        try:
            while True:
                try:
                    line = await proc.stdout.readline()
                except ValueError:
                    self._log(name, '[oversized log line suppressed]')
                    continue
                if not line:
                    break
                self._log(name, line.decode(errors='replace').rstrip())
        finally:
            await proc.wait()
            self._log(name, f'Process exited with code {proc.returncode}')

    async def _start(self, name):
        entry = self._entries[name]
        proc = entry['process']
        if proc and proc.returncode is None:
            return
        await self.refresh_external()
        if entry['external_pids']:
            entry['last_error'] = 'External terminal process found; use Manual mode or close it first'
            return
        if self._probe_external and await self._probe_external(name):
            entry['last_error'] = 'An existing ROS node responds; not starting a duplicate. Use Manual mode to inspect it'
            return
        executable = self.workspace / '.venv/bin/python'
        command = self._commands[name] if self._commands else [
            str(executable), '-u', '-m', f'agent_pkg.{name}_node',
        ]
        if not self._commands and name == 'intent':
            command += ['--ros-args', '-p', f'clock_skew_sec:={self.clock_skew}']
        entry['transition'] = 'starting'
        try:
            proc = await asyncio.create_subprocess_exec(
                *command, cwd=self.workspace, env=self._environment(),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            entry['last_error'] = f'Cannot start node ({type(exc).__name__}); check workspace, venv and build'
            self._log(name, entry['last_error'])
            return
        finally:
            entry['transition'] = None
        entry.update(process=proc, started_at=time.time(), last_error='')
        self._record_process(name, proc)
        task = asyncio.create_task(self._drain(name, proc))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        self._log(name, f'Started managed process PID {proc.pid}')

    async def _stop_record(self, record, *, force):
        if not signal_owned(record, signal.SIGKILL if force else signal.SIGTERM):
            return
        deadline = time.monotonic() + (1 if force else 4)
        while identity(record['pid']) == record.get('start_ticks') and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        signal_owned(record, signal.SIGKILL)

    async def _stop(self, name, *, force=False):
        entry = self._entries[name]
        entry['transition'] = 'killing' if force else 'stopping'
        try:
            record = self.registry.read('processes.json', {}).get(name, {})
            await self._stop_record(record, force=force)
            proc = entry['process']
            if proc:
                await asyncio.wait_for(proc.wait(), 2)
        finally:
            entry['transition'] = None

    async def control(self, name, action):
        if not self.enabled or not self.owns_lock or self._closing:
            raise ProcessControlError(self.problem or 'Node control is disabled (Mock or external/manual launcher)')
        if name not in NODES or action not in ('start', 'stop', 'restart', 'kill'):
            raise ProcessControlError('Unknown node or action')
        async with self._transaction():
            preferences = self.registry.preferences()
            if action in ('start', 'restart') and preferences['manual']:
                raise ProcessControlError('Manual mode is active; enable automatic management first')
            if action in ('stop', 'kill'):
                preferences['disabled'] = sorted(set(preferences['disabled']) | {name})
            else:
                preferences['disabled'] = [n for n in preferences['disabled'] if n != name]
            self.registry.write('preferences.json', preferences)
            if action in ('stop', 'restart', 'kill'):
                await self._stop(name, force=action == 'kill')
            if action in ('start', 'restart'):
                if action == 'restart':
                    self._entries[name]['restart_count'] += 1
                await self._start(name)
        return self.snapshot()

    async def set_mode(self, mode):
        if not self.enabled or not self.owns_lock:
            raise ProcessControlError(self.problem or 'Node control is disabled')
        async with self._transaction():
            self.registry.write('preferences.json', {'manual': mode == 'manual', 'disabled': list(NODES) if mode == 'manual' else []})
            for name in NODES:
                if mode == 'manual':
                    await self._stop(name)
                else:
                    await self._start(name)
        return self.snapshot()

    def snapshot(self):
        preferences = self.registry.preferences() if self.registry else {'manual': True, 'disabled': list(NODES)}
        nodes = {}
        for name, entry in self._entries.items():
            proc = entry['process']
            status = ('running' if proc.returncode is None else 'failed' if proc.returncode else 'stopped') if proc else 'stopped'
            if name in preferences['disabled'] and (not proc or proc.returncode is not None):
                status = 'stopped'
            if entry['external_pids'] and (not proc or proc.returncode is not None):
                status = 'external'
            if entry['last_error'] and status not in ('external', 'running'):
                status = 'failed'
            if entry['transition']:
                status = entry['transition']
            nodes[name] = {
                'status': status, 'pid': proc.pid if proc and proc.returncode is None else None,
                'external_pids': entry['external_pids'], 'started_at': entry['started_at'],
                'exit_code': proc.returncode if proc else None, 'restart_count': entry['restart_count'],
                'last_error': entry['last_error'], 'logs': list(entry['logs']),
            }
        return {'enabled': self.enabled and self.owns_lock, 'mode': 'manual' if preferences['manual'] else 'automatic',
                'problem': self.problem, 'workspace': str(self.workspace), 'nodes': nodes}

    async def close(self):
        self._closing = True
        if not self.owns_lock:
            return
        try:
            async with self._transaction():
                for name in NODES:
                    await self._stop(name)
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
        finally:
            self.registry.release_owner()
            self.owns_lock = False

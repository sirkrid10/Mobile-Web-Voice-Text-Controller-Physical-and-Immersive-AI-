"""Bounded, private observations of web requests and received dialogue events."""

import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time


class DialogueHistory:
    capacity = 2000
    fields = ('text', 'request_id', 'session_id', 'status', 'destination_id',
              'input_mode', 'observation_id', 'error_code')

    def __init__(self, path=None, *, scope='', secrets=()):
        digest = hashlib.sha256(os.fsencode(scope)).hexdigest()[:16]
        self.path = Path(path) if path else Path.home() / '.local/state/turtlebot-dialogue' / digest / 'history.sqlite3'
        self.connection = None
        self.lock = RLock()
        self.error = None
        self.secrets = tuple(value for value in secrets if isinstance(value, str) and len(value) >= 4)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
            self.path.chmod(0o600)
            self.connection = sqlite3.connect(self.path, timeout=0.05, check_same_thread=False)
            self.connection.execute('PRAGMA journal_mode=WAL')
            self.connection.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, received_at REAL NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL)')
            self.connection.commit()
        except (OSError, sqlite3.Error):
            self.error = 'history_storage_unavailable'

    def record(self, kind, **values):
        if self.connection is None or kind not in ('request', 'intent', 'dispatch', 'subtitle'):
            return
        payload = {}
        for field in self.fields:
            value = values.get(field)
            if not isinstance(value, str):
                continue
            for secret in self.secrets:
                value = value.replace(secret, '[REDACTED]')
            payload[field] = value[:1000]
        try:
            with self.lock, self.connection:
                self.connection.execute('INSERT INTO events (received_at, kind, payload) VALUES (?, ?, ?)',
                                        (time.time(), kind, json.dumps(payload, ensure_ascii=False)))
                self.connection.execute('DELETE FROM events WHERE id <= (SELECT MAX(id) - ? FROM events)', (self.capacity,))
            self.error = None
        except (sqlite3.Error, UnicodeError, ValueError):
            self.error = 'history_write_failed'

    def snapshot(self, limit=50):
        events = []
        if self.connection is not None:
            try:
                with self.lock:
                    rows = self.connection.execute('SELECT id, received_at, kind, payload FROM events ORDER BY id DESC LIMIT ?', (min(max(limit, 1), self.capacity),)).fetchall()
                events = [{'id': row[0], 'received_at': row[1], 'kind': row[2], **json.loads(row[3])} for row in reversed(rows)]
            except (sqlite3.Error, ValueError):
                self.error = 'history_read_failed'
        return {'events': events, 'capacity': self.capacity, 'available': self.connection is not None and self.error is None, 'error': self.error}

    def close(self):
        with self.lock:
            if self.connection is not None:
                self.connection.close()
                self.connection = None

"""Private process registry shared by Backend and the terminal fallback."""

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import tempfile
import time

NODES = ('intent', 'subtitle')
try:
    BOOT_ID = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
except FileNotFoundError:
    # Local mock previews also run on macOS, without Linux process control.
    BOOT_ID = None


def identity(pid):
    """Boot ID and Linux start ticks distinguish a process from a reused PID."""
    if BOOT_ID is None:
        return None
    try:
        stat = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            return None
        return f'{BOOT_ID}:{stat[19]}'
    except (OSError, IndexError):
        return None


def signal_owned(record, sig):
    pid = record.get('pid')
    expected = record.get('start_ticks')
    if not isinstance(expected, str) or not expected:
        return False
    if not isinstance(pid, int) or pid <= 1 or identity(pid) != expected:
        return False
    try:
        if os.getpgid(pid) != pid:
            return False
        os.killpg(pid, sig)
        return True
    except ProcessLookupError:
        return False


def external_nodes(domain):
    """Inspect only this user's local node executables, without exposing env."""
    found = {name: [] for name in NODES}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != os.getuid():
                continue
            args = entry.joinpath('cmdline').read_bytes().split(b'\0')
            modules = [f'agent_pkg.{name}_node'.encode() for name in NODES]
            for name, module in zip(NODES, modules):
                is_module = any(args[i:i+2] == [b'-m', module] for i in range(len(args)-1))
                is_script = any(Path(os.fsdecode(arg)).name == f'{name}_node' for arg in args[:2])
                if not (is_module or is_script) or identity(int(entry.name)) is None:
                    continue
                environment = entry.joinpath('environ').read_bytes().split(b'\0')
                actual = next((v.split(b'=', 1)[1].decode() for v in environment if v.startswith(b'ROS_DOMAIN_ID=')), '0')
                if actual == str(domain):
                    found[name].append(int(entry.name))
        except (OSError, UnicodeError, ValueError):
            continue
    return found


class RuntimeRegistry:
    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        digest = hashlib.sha256(os.fsencode(self.workspace)).hexdigest()[:16]
        # A terminal and a service can have different XDG_RUNTIME_DIR values.
        # One durable location per user/workspace keeps offline recovery reliable.
        base = Path.home() / '.local/state'
        self.directory = base / f'turtlebot-agents-{digest}'
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink() or self.directory.stat().st_uid != os.getuid():
            raise RuntimeError('Agent runtime directory must belong to this user')
        self.directory.chmod(0o700)
        self.owner = None

    def read(self, name, default):
        try:
            return json.loads((self.directory / name).read_text())
        except (OSError, ValueError):
            return default

    def write(self, name, value):
        fd, temp = tempfile.mkstemp(dir=self.directory)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream)
            os.replace(temp, self.directory / name)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def acquire_owner(self):
        self.owner = open(self.directory / 'owner.lock', 'a+')
        try:
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.owner.close()
            self.owner = None
            return False
        return True

    def release_owner(self):
        if self.owner:
            self.owner.close()
            self.owner = None

    @contextmanager
    def transaction(self):
        with open(self.directory / 'commands.lock', 'a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    def preferences(self):
        return self.read('preferences.json', {'manual': False, 'disabled': []})

    def fallback_manual(self, force=False):
        """No HTTP/ROS dependency. Persist Manual before signaling verified groups."""
        with self.transaction():
            self.write('preferences.json', {'manual': True, 'disabled': list(NODES)})
            records = self.read('processes.json', {})
            signaled = []
            for name in NODES:
                if signal_owned(records.get(name, {}), signal.SIGKILL if force else signal.SIGTERM):
                    signaled.append(name)
            if not force:
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline and any(
                    identity(records[n]['pid']) == records[n].get('start_ticks') for n in signaled
                ):
                    time.sleep(0.05)
                for name in signaled:
                    signal_owned(records[name], signal.SIGKILL)
            return {'mode': 'manual', 'signaled': signaled, 'directory': str(self.directory)}

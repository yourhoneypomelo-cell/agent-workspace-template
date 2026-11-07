"""The workspace lock: an operating-system lock on ws.flock, or the lock file of 3.8 under WS_LOCK=legacy."""
from __future__ import annotations

import contextlib
import json
import os
import time
from pathlib import Path

from .core import WorkspaceError, atomic_write, now, pid_alive, safe_path
from .schema import FLOCK, LOCK, LOCK_INFO

LOCK_ORPHAN_SECONDS = 60
# The workspace locks this process holds, so a check it runs while holding one does not count it as busy.
HELD = set()


@contextlib.contextmanager
def lock(root: Path):
    """The workspace lock: an operating-system lock on byte 0 of ws.flock. It ends with the process that holds it,
    so a killed command leaves nothing behind; ws.lock.info names the holder for messages. The ws.lock of 3.8 and
    older still counts while its process runs. WS_LOCK=legacy uses that older lock file instead, for 3.9 only."""
    if os.environ.get('WS_LOCK', '').lower() == 'legacy':
        with _legacy_lock(root):
            yield
        return
    path = safe_path(root, FLOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + float(os.environ.get('WS_LOCK_WAIT', '30'))
    fd = _open_lock(path, deadline)
    try:
        while True:
            if _take(fd):
                if not _legacy_holder(root):
                    break
                _drop(fd)  # an older ws.py holds its lock file: let it finish
            if time.monotonic() >= deadline:
                raise WorkspaceError(f'another ws.py command is running ({holder_text(root)}). Wait and retry; the '
                                     'lock ends with the process that holds it')
            time.sleep(0.1)
        HELD.add(path)
        info = safe_path(root, LOCK_INFO)
        try:
            atomic_write(info, json.dumps({'pid': os.getpid(), 'created_at': now()}))
        except OSError:
            pass  # the holder note only improves messages
        try:
            yield
        finally:
            HELD.discard(path)
            for _ in range(5):
                with contextlib.suppress(OSError):
                    info.unlink(missing_ok=True)
                    break
                time.sleep(0.05)
            _drop(fd)
    finally:
        os.close(fd)


def _open_lock(path: Path, deadline: float) -> int:
    while True:
        try:
            return os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        except PermissionError as error:
            # Windows refuses an open while the file is being replaced or scanned; that passes.
            if time.monotonic() >= deadline:
                raise WorkspaceError(f'cannot open the lock {FLOCK}: {error}. Check that the folder is writable')
            time.sleep(0.1)


def _take(fd: int) -> bool:
    """Lock byte 0 without waiting. False when another process holds it."""
    import errno
    try:
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError as error:
        if error.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK, getattr(errno, 'EDEADLOCK', errno.EDEADLK)):
            return False
        raise WorkspaceError(f'this drive cannot lock {FLOCK} ({error}). Move the project to a local disk, or set '
                             'WS_LOCK=legacy to use the lock file of 3.8 for this version') from error


def _drop(fd: int):
    with contextlib.suppress(OSError):
        if os.name == 'nt':
            import msvcrt
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)


def _legacy_holder(root: Path, clean=True):
    """The pid of a running older ws.py that holds ws.lock, or None. A ws.lock left by a process that ended is
    removed when clean is set; an empty or unreadable one, as a crash leaves it, holds nothing."""
    path = root / LOCK
    try:
        pid = int(json.loads(path.read_text(encoding='utf-8'))['pid'])
    except (OSError, ValueError, TypeError, KeyError):
        return None
    if pid == os.getpid():
        return None
    if pid_alive(pid):
        return pid
    for _ in range(5):
        if not clean or _unlink(path):
            break
    return None


def holder_text(root: Path) -> str:
    legacy = _legacy_holder(root, clean=False)
    if legacy:
        return f'pid {legacy}, an older ws.py'
    try:
        info = json.loads((root / LOCK_INFO).read_text(encoding='utf-8'))
        return f'pid {info.get("pid", "unknown")} since {info.get("created_at", "an unknown time")}'
    except (OSError, ValueError, AttributeError):
        return 'holder unknown'


def lock_busy(root: Path) -> bool:
    """Whether another process holds the workspace lock now. Never true for the process that holds it. Writes
    nothing, so read-only commands may ask."""
    if safe_path(root, FLOCK) in HELD or safe_path(root, LOCK) in HELD:
        return False
    if os.environ.get('WS_LOCK', '').lower() == 'legacy':
        return (root / LOCK).exists()
    if _legacy_holder(root, clean=False):
        return True
    if not (root / FLOCK).is_file():
        return False
    fd = os.open(root / FLOCK, os.O_RDWR)
    try:
        if _take(fd):
            _drop(fd)
            return False
        return True
    finally:
        os.close(fd)


@contextlib.contextmanager
def _legacy_lock(root: Path):
    """The lock file of 3.8 and older: created exclusively, its holder judged by pid. WS_LOCK=legacy, 3.9 only."""
    path = safe_path(root, LOCK)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + float(os.environ.get('WS_LOCK_WAIT', '30'))
    while True:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            pass
        except PermissionError as error:
            # Windows refuses to create a file whose delete is still pending: the lock is being released.
            if time.monotonic() >= deadline:
                raise WorkspaceError(f'cannot create the lock {LOCK}: {error}. Check that the folder is writable')
            time.sleep(0.1)
            continue
        try:
            holder = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            holder = {}
        if holder.get('pid') and not pid_alive(int(holder['pid'])):
            _unlink(path)
            continue
        # A crash while the lock was written leaves an empty or NUL-filled file that names no process.
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            continue
        if not holder.get('pid') and age > LOCK_ORPHAN_SECONDS:
            _unlink(path)
            continue
        if time.monotonic() >= deadline:
            raise WorkspaceError(
                f'another ws.py command is running (pid {holder.get("pid", "unknown")}, lock {int(age)} s old). '
                'Wait and retry. Do not delete the lock while another window may run ws; a lock that names no '
                f'process is removed after {LOCK_ORPHAN_SECONDS} s.')
        time.sleep(0.1)
    nonce = os.urandom(8).hex()
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(json.dumps({'pid': os.getpid(), 'created_at': now(), 'nonce': nonce}))
        HELD.add(path)
        yield
    finally:
        HELD.discard(path)
        _release(path, nonce)


def _unlink(path: Path) -> bool:
    """Delete a lock file. Windows refuses while another process reads it; the caller then tries again."""
    try:
        path.unlink(missing_ok=True)
        return True
    except PermissionError:
        time.sleep(0.05)
        return False


def _release(path: Path, nonce: str):
    """Remove the lock only while it is still ours: a process that took us for dead may have taken it since."""
    for _ in range(20):
        try:
            if json.loads(path.read_text(encoding='utf-8')).get('nonce') != nonce or _unlink(path):
                return
        except PermissionError:
            time.sleep(0.05)
        except (OSError, ValueError):
            return

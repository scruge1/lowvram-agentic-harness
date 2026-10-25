"""Linux pidfd facade for Python builds missing compiled pidfd wrappers.

Prefer Python's public wrappers. Otherwise use only the public libc functions
pidfd_open(int, unsigned int) and pidfd_send_signal(int, int, siginfo_t *,
unsigned int). A missing libc symbol or unsupported kernel fails closed. There
is no PID-based signal fallback, raw syscall number or global monkeypatch.

Only siginfo=None is supported. Callers retain their existing ownership checks
and descriptor lifetime. Exit observation can use poll/select on the pidfd;
this module does not invent P_PIDFD or perform unrelated child reaping.
"""
from __future__ import annotations

import ctypes
import errno
import operator
import os
import signal
import sys


_PY_OPEN = getattr(os, "pidfd_open", None)
_PY_SIGNAL = getattr(signal, "pidfd_send_signal", None)
_C_SYMBOLS = None
_C_LIBRARY = None
_INT_MIN = -(2 ** 31)
_INT_MAX = 2 ** 31 - 1
_UINT_MAX = 2 ** 32 - 1


def _linux():
    if sys.platform != "linux":
        raise OSError(errno.ENOSYS, "Native pidfd ownership requires Linux")


def _integer(value, *, unsigned=False):
    value = operator.index(value)
    minimum, maximum = (0, _UINT_MAX) if unsigned else (_INT_MIN, _INT_MAX)
    if not minimum <= value <= maximum:
        raise OverflowError("pidfd argument is outside its C integer range")
    return value


def _libc():
    global _C_SYMBOLS, _C_LIBRARY
    if _C_SYMBOLS is not None:
        return _C_SYMBOLS
    functions = {}
    try:
        library = ctypes.CDLL(None, use_errno=True)
    except OSError:
        library = None
    for name, arguments in (("pidfd_open", (ctypes.c_int, ctypes.c_uint)),
                            ("pidfd_send_signal", (ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint))):
        function = getattr(library, name, None) if library is not None else None
        if function is not None:
            function.argtypes = arguments
            function.restype = ctypes.c_int
        functions[name] = function
    _C_LIBRARY, _C_SYMBOLS = library, functions
    return functions


def backend():
    """Describe selected public wrappers, without opening or signaling a PID."""
    if sys.platform != "linux":
        return {"pidfd_open": "unavailable", "pidfd_send_signal": "unavailable"}
    need_libc = not callable(_PY_OPEN) or not callable(_PY_SIGNAL)
    functions = _libc() if need_libc else {}
    return {"pidfd_open": "python" if callable(_PY_OPEN) else "libc" if functions.get("pidfd_open") else "unavailable",
            "pidfd_send_signal": "python" if callable(_PY_SIGNAL) else "libc" if functions.get("pidfd_send_signal") else "unavailable"}


def _c_call(name, *arguments):
    function = _libc().get(name)
    if function is None:
        raise OSError(errno.ENOSYS, "Public libc " + name + " is unavailable; no PID or raw-syscall fallback")
    ctypes.set_errno(0)
    result = function(*arguments)
    if result == -1:
        number = ctypes.get_errno() or errno.EIO
        raise OSError(number, name + ": " + os.strerror(number))
    return result


def pidfd_open(pid, flags=0):
    """Open a Linux identity descriptor with close-on-exec preserved."""
    _linux()
    pid, flags = _integer(pid), _integer(flags, unsigned=True)
    descriptor = _PY_OPEN(pid, flags) if callable(_PY_OPEN) else _c_call("pidfd_open", pid, flags)
    try:
        # Linux pidfd_open sets FD_CLOEXEC atomically. Retain this invariant even
        # if a future compiled wrapper changes its descriptor handling.
        if os.get_inheritable(descriptor):
            os.set_inheritable(descriptor, False)
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def pidfd_send_signal(descriptor, sig, siginfo=None, flags=0):
    """Signal only the supplied kernel identity; custom siginfo is unsupported."""
    _linux()
    if siginfo is not None:
        raise TypeError("The portable pidfd facade supports siginfo=None only")
    descriptor, sig = _integer(descriptor), _integer(sig)
    flags = _integer(flags, unsigned=True)
    if callable(_PY_SIGNAL):
        _PY_SIGNAL(descriptor, sig, None, flags)
    else:
        _c_call("pidfd_send_signal", descriptor, sig, None, flags)
    return None


def require_support():
    """Probe only this process with signal 0 and close its self pidfd."""
    _linux()
    selected = backend()
    descriptor = None
    try:
        descriptor = pidfd_open(os.getpid())
        pidfd_send_signal(descriptor, 0)
    except OSError as error:
        raise OSError(error.errno, "Native pidfd self-probe failed via " + str(selected) + ": " + str(error)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
    return selected

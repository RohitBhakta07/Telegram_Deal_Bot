"""Cooperative restart coordination for the embedded dashboard and worker."""
import threading

_lock = threading.RLock()
_stop_event = None
_restart = False


def attach(stop_event):
    global _stop_event
    with _lock:
        _stop_event = stop_event


def detach():
    global _stop_event
    with _lock:
        _stop_event = None


def request_restart():
    global _restart
    with _lock:
        if _stop_event is None:
            return False
        _restart = True
        _stop_event.set()
        return True


def consume_restart():
    global _restart
    with _lock:
        requested = _restart
        _restart = False
        return requested

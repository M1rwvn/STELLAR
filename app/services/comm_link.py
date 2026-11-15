"""Simulated space-to-ground downlink with an Emergency Priority Queue.

Models the two things the Architecture slide talks about:
  * Communication delay: every message arrives `delay` seconds after it is sent.
  * Limited bandwidth / loss of signal: messages wait in a queue; while the
    link is down (blackout) they pile up, and when it comes back the queue is
    sent Emergency first, then High Risk, security, Attention, Normal.

Demo: POST /comm/blackout {"seconds": 20}, run the replay script, watch
GET /comm/status - Ryan's Emergency jumps ahead of everything queued before it.
"""
import heapq
import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

PRIORITY = {"Emergency": 0, "High Risk": 1, "security": 1, "Attention": 2, "Normal": 3}


@dataclass(order=True)
class Message:
    priority: int
    seq: int
    kind: str = field(compare=False)  # risk | alert
    astronaut_id: str | None = field(compare=False)
    summary: str = field(compare=False)
    level: str = field(compare=False)
    enqueued_at: datetime = field(compare=False)
    sent_at: datetime | None = field(default=None, compare=False)
    arrives_at: datetime | None = field(default=None, compare=False)

    def as_dict(self, now: datetime) -> dict:
        state = "queued"
        if self.arrives_at is not None:
            state = "delivered" if self.arrives_at <= now else "in_flight"
        return {
            "seq": self.seq, "kind": self.kind, "level": self.level, "priority": self.priority,
            "astronaut_id": self.astronaut_id, "summary": self.summary, "state": state,
            "enqueued_at": self.enqueued_at.isoformat(),
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "arrives_at": self.arrives_at.isoformat() if self.arrives_at else None,
        }


class CommLink:
    def __init__(self, delay_seconds: float = 2.0, transmit_seconds: float = 0.05,
                 history: int = 300):
        self.delay = delay_seconds
        self.transmit_seconds = transmit_seconds
        self._heap: list[Message] = []
        self._sent: deque[Message] = deque(maxlen=history)
        self._seq = itertools.count(1)
        self._cv = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = False
        self.blackout_until: datetime | None = None

    # ---- producer side ----
    def enqueue(self, kind: str, level: str, astronaut_id: str | None, summary: str) -> Message:
        msg = Message(priority=PRIORITY.get(level, 3), seq=next(self._seq), kind=kind,
                      astronaut_id=astronaut_id, summary=summary, level=level,
                      enqueued_at=datetime.now(timezone.utc))
        with self._cv:
            heapq.heappush(self._heap, msg)
            self._cv.notify()
        return msg

    def start_blackout(self, seconds: float) -> datetime:
        with self._cv:
            self.blackout_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
            self._cv.notify()
        return self.blackout_until

    def in_blackout(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return self.blackout_until is not None and now < self.blackout_until

    # ---- link side ----
    def transmit_next(self) -> Message | None:
        """Send the highest-priority queued message (no-op during blackout)."""
        now = datetime.now(timezone.utc)
        with self._cv:
            if not self._heap or self.in_blackout(now):
                return None
            msg = heapq.heappop(self._heap)
        msg.sent_at = now
        msg.arrives_at = now + timedelta(seconds=self.delay)
        self._sent.append(msg)
        return msg

    def _run(self) -> None:
        while not self._stop:
            with self._cv:
                while not self._stop and (not self._heap or self.in_blackout()):
                    timeout = 1.0
                    if self.in_blackout():
                        # wake up exactly when the signal comes back
                        timeout = max(0.05, (self.blackout_until - datetime.now(timezone.utc)).total_seconds())
                    self._cv.wait(timeout=timeout)
            if self._stop:
                break
            if self.transmit_next() is not None:
                time.sleep(self.transmit_seconds)  # bandwidth: one message at a time

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="comm-link", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()
        if self._thread:
            self._thread.join(timeout=2)

    # ---- monitoring ----
    def status(self, limit: int = 50) -> dict:
        now = datetime.now(timezone.utc)
        with self._cv:
            queued = sorted(self._heap)
        sent = list(self._sent)[-limit:]
        return {
            "delay_seconds": self.delay,
            "blackout": self.in_blackout(now),
            "blackout_until": self.blackout_until.isoformat() if self.in_blackout(now) else None,
            "queued": [m.as_dict(now) for m in queued[:limit]],
            "queued_count": len(queued),
            "sent": [m.as_dict(now) for m in reversed(sent)],
        }


comm_link = CommLink()

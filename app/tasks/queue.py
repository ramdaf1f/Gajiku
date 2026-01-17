import os
import threading
import time
from queue import Queue


_queue = Queue()
_worker_started = False

try:
    from redis import Redis
    from rq import Queue as RqQueue
except Exception:  # pragma: no cover - optional dependency
    Redis = None
    RqQueue = None

_redis_url = os.environ.get("REDIS_URL")
_mode = "rq" if (Redis and RqQueue and _redis_url) else "inline"


def get_mode():
    return _mode


def enqueue(func, *args, **kwargs):
    if _mode == "rq":
        conn = Redis.from_url(_redis_url)
        rq_queue = RqQueue("default", connection=conn)
        rq_queue.enqueue(func, *args, **kwargs)
        return
    _queue.put((func, args, kwargs, time.time()))


def start_worker(app):
    if _mode != "inline":
        return
    global _worker_started
    if _worker_started:
        return
    _worker_started = True
    thread = threading.Thread(target=_run, args=(app,), daemon=True)
    thread.start()


def get_stats():
    if _mode == "rq":
        try:
            conn = Redis.from_url(_redis_url)
            rq_queue = RqQueue("default", connection=conn)
            count = rq_queue.count
            oldest_age = None
            try:
                jobs = rq_queue.get_jobs(0, 1)
                if jobs:
                    enq = jobs[0].enqueued_at or jobs[0].created_at
                    if enq:
                        oldest_age = max(time.time() - enq.timestamp(), 0)
            except Exception:
                oldest_age = None
            return {"mode": "rq", "count": count, "oldest_age_sec": oldest_age}
        except Exception:
            return {"mode": "rq", "count": None, "oldest_age_sec": None}

    with _queue.mutex:
        items = list(_queue.queue)
    count = len(items)
    oldest_age = None
    if items:
        oldest_age = max(time.time() - items[0][3], 0)
    return {"mode": "inline", "count": count, "oldest_age_sec": oldest_age}


def _run(app):
    while True:
        func, args, kwargs, _enqueued_at = _queue.get()
        try:
            with app.app_context():
                func(*args, **kwargs)
        except Exception as exc:
            app.logger.warning(f"[QUEUE] job failed: {exc}")
        finally:
            _queue.task_done()

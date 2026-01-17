import os

from redis import Redis
from rq import Worker, Queue, Connection


os.environ["START_INLINE_WORKER"] = "0"


def main():
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    conn = Redis.from_url(redis_url)
    listen = ["default"]
    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()


if __name__ == "__main__":
    main()

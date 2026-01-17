import logging
import time

from flask import g


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        try:
            record.request_id = getattr(g, "request_id", "-")
        except Exception:
            record.request_id = "-"
        return True


def configure_logging(app):
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [handler]

    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    app.logger.info("logging configured", extra={"startup_ts": int(time.time())})

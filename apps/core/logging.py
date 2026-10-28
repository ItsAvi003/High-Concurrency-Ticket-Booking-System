"""
Request-id plumbing for logs.

A ContextVar holds the id of the request currently being handled. Unlike a plain
global, each thread (and each asyncio task) sees its own value, so two requests
served at the same time never mix up their ids.
"""

import logging
from contextvars import ContextVar

NO_REQUEST_ID = "-"

request_id_var: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def reset_request_id(**kwargs) -> None:
    """
    request_finished signal receiver.

    The signal fires when the response is closed, after Django has written its own
    error logs, so this is the last moment the id is still useful. Resetting stops it
    leaking into whatever this worker thread does next.
    """
    request_id_var.set(NO_REQUEST_ID)


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record passing through a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True  # never drop records; this filter only enriches them

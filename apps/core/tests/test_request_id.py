import json
import logging

import pytest
from django.urls import reverse
from django.utils.module_loading import import_string

from apps.core.logging import NO_REQUEST_ID, RequestIdFilter, request_id_var
from config.logging import build_logging_config


def test_response_gets_generated_request_id(client):
    response = client.get(reverse("core:health-live"))

    request_id = response["X-Request-ID"]
    assert len(request_id) == 32  # uuid4().hex


def test_valid_incoming_request_id_is_reused(client):
    response = client.get(reverse("core:health-live"), headers={"X-Request-ID": "nginx-abc.123"})

    assert response["X-Request-ID"] == "nginx-abc.123"


def test_malicious_incoming_request_id_is_replaced(client):
    response = client.get(
        reverse("core:health-live"),
        headers={"X-Request-ID": "x\nFAKE LOG LINE level=ERROR"},
    )

    assert response["X-Request-ID"] != "x\nFAKE LOG LINE level=ERROR"
    assert len(response["X-Request-ID"]) == 32


def test_request_id_does_not_leak_after_request(client):
    client.get(reverse("core:health-live"))

    assert request_id_var.get() == NO_REQUEST_ID


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.addFilter(RequestIdFilter())
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.mark.django_db
def test_djangos_own_error_log_carries_the_request_id(client, settings):
    # Django logs 5xx responses after the middleware chain has returned; this guards
    # against resetting the id too early (it used to show up as "-").
    settings.REDIS_URL = "redis://127.0.0.1:1/0"
    handler = _CapturingHandler()
    django_request_logger = logging.getLogger("django.request")
    django_request_logger.addHandler(handler)
    try:
        response = client.get(reverse("core:health-ready"))
    finally:
        django_request_logger.removeHandler(handler)

    assert response.status_code == 503
    assert [r.request_id for r in handler.records] == [response["X-Request-ID"]]


def test_filter_attaches_current_request_id():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
    token = request_id_var.set("req-42")
    try:
        RequestIdFilter().filter(record)
    finally:
        request_id_var.reset(token)

    assert record.request_id == "req-42"


def test_json_formatter_emits_one_parseable_object_with_extra_fields():
    # Build the formatter exactly as logging.config.dictConfig would from our config.
    formatter_config = dict(
        build_logging_config(level="INFO", json_logs=True)["formatters"]["json"]
    )
    formatter = import_string(formatter_config.pop("()"))(**formatter_config)

    record = logging.LogRecord(
        "apps.request", logging.INFO, __file__, 1, "request finished", (), None
    )
    record.request_id = "req-42"
    record.status = 200

    payload = json.loads(formatter.format(record))

    assert payload["message"] == "request finished"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "apps.request"
    assert payload["request_id"] == "req-42"
    assert payload["status"] == 200

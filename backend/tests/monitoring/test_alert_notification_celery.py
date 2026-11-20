from __future__ import annotations

import importlib
import inspect
import uuid
from pathlib import Path

import pytest
import yaml
from celery.exceptions import Reject


@pytest.fixture
def celery_modules(monkeypatch):
    """Reload the app/task pair against an inert, explicit test broker URL."""
    monkeypatch.setenv("ALERT_NOTIFICATION_BROKER_URL", "memory://")
    app_module = importlib.import_module("celery_app")
    app_module = importlib.reload(app_module)
    task_module = importlib.import_module("tasks.alert_notification_tasks")
    task_module = importlib.reload(task_module)
    return app_module, task_module


def test_celery_task_has_fixed_contract_and_two_alert_queues(celery_modules):
    app_module, task_module = celery_modules

    task = task_module.deliver_alert_notification
    assert task.name == "monitoring.alerts.deliver"
    assert list(inspect.signature(task.run).parameters) == [
        "delivery_id",
        "dispatch_generation",
    ]
    assert task.ignore_result is True
    assert task.acks_late is True
    assert task.reject_on_worker_lost is True
    assert getattr(task, "autoretry_for", ()) == ()

    assert {queue.name for queue in app_module.app.conf.task_queues} == {
        "alert_notify_critical",
        "alert_notify_normal",
    }
    assert app_module.app.conf.task_default_queue == "alert_notify_normal"
    assert app_module.app.conf.task_routes[task.name]["queue"] == "alert_notify_normal"

    critical_route = app_module.app.amqp.router.route(
        {"queue": "alert_notify_critical"},
        task.name,
        args=("delivery-42", 7),
        kwargs={},
    )
    assert critical_route["queue"].name == "alert_notify_critical"


def test_celery_worker_config_is_json_only_and_bounded(celery_modules):
    app_module, _task_module = celery_modules

    config = app_module.app.conf
    assert tuple(config.accept_content) == ("json",)
    assert config.task_serializer == "json"
    assert config.result_serializer == "json"
    assert config.event_serializer == "json"
    assert config.task_ignore_result is True
    assert config.worker_prefetch_multiplier == 1
    assert config.task_acks_late is True
    assert config.task_reject_on_worker_lost is True
    assert config.task_acks_on_failure_or_timeout is False
    assert config.broker_transport_options['visibility_timeout'] == 120
    assert config.broker_transport_options['global_keyprefix'] == 'nexora_alert_'
    assert config.worker_enable_remote_control is False
    assert config.worker_send_task_events is False


def test_celery_consumer_mode_setting_reads_environment_as_boolean(monkeypatch):
    from core.config import Settings

    monkeypatch.setenv("ALERT_NOTIFICATION_CELERY_ENABLED", "true")
    assert Settings(_env_file=None).ALERT_NOTIFICATION_CELERY_ENABLED is True

    monkeypatch.setenv("ALERT_NOTIFICATION_CELERY_ENABLED", "0")
    assert Settings(_env_file=None).ALERT_NOTIFICATION_CELERY_ENABLED is False


def test_task_invokes_generation_processor_with_private_owner_uuid(
    celery_modules, monkeypatch
):
    _app_module, task_module = celery_modules
    from services import monitoring_notification_outbox_service as outbox

    calls = []

    def process_alert_delivery_by_generation(**kwargs):
        calls.append(kwargs)
        return "succeeded"

    monkeypatch.setattr(
        outbox,
        "process_alert_delivery_by_generation",
        process_alert_delivery_by_generation,
        raising=False,
    )

    task_module.deliver_alert_notification.apply(
        args=("delivery-42", 7),
        throw=True,
    )

    assert len(calls) == 1
    assert calls[0]["delivery_id"] == "delivery-42"
    assert calls[0]["dispatch_generation"] == 7
    assert uuid.UUID(calls[0]["worker_id"])


def test_missing_broker_does_not_break_import_but_blocks_worker_start(monkeypatch):
    monkeypatch.delenv("ALERT_NOTIFICATION_BROKER_URL", raising=False)
    app_module = importlib.import_module("celery_app")
    app_module = importlib.reload(app_module)

    assert app_module.app.conf.broker_url is None
    with pytest.raises(RuntimeError, match="ALERT_NOTIFICATION_BROKER_URL"):
        app_module.app.Worker(pool="solo", loglevel="CRITICAL")


def test_processor_exception_propagates_without_exposing_details(
    celery_modules, monkeypatch, caplog
):
    _app_module, task_module = celery_modules
    from services import monitoring_notification_outbox_service as outbox

    def fail(**_kwargs):
        raise RuntimeError("private exception contents")

    monkeypatch.setattr(
        outbox,
        "process_alert_delivery_by_generation",
        fail,
        raising=False,
    )

    with pytest.raises(RuntimeError, match='private exception contents'):
        task_module.deliver_alert_notification.run("delivery-42", 7)

    assert "private exception contents" not in caplog.text


def test_compose_alert_broker_is_only_attached_to_its_private_network():
    compose_path = Path(__file__).resolve().parents[3] / "docker-compose.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert compose["networks"]["alert_notifications"]["internal"] is True
    assert compose["services"]["alert-redis"]["networks"] == ["alert_notifications"]
    broker_command = " ".join(compose["services"]["alert-redis"]["command"]).lower()
    assert "+publish" not in broker_command
    alert_services = (
        "alert-redis",
        "alert-notify-relay",
        "alert-notify-critical",
        "alert-notify-normal",
    )
    for name in alert_services[1:]:
        assert set(compose["services"][name]["networks"]) == {
            "default",
            "alert_notifications",
        }
    for name in alert_services:
        service = compose["services"][name]
        assert service["cpu_shares"] == 64
        assert "cpus" in service
        assert "mem_limit" in service
    for name in ("alert-notify-critical", "alert-notify-normal"):
        command = compose["services"][name]["command"]
        assert {
            "--without-gossip",
            "--without-mingle",
            "--without-heartbeat",
        }.issubset(command)


def test_invalid_task_arguments_are_rejected_without_requeue(celery_modules):
    _app_module, task_module = celery_modules

    with pytest.raises(Reject) as error:
        task_module.deliver_alert_notification.run("delivery-42", True)

    assert error.value.requeue is False

import threading
import time
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor

import pytest

from services.network_access_limiter import (
    NetworkAccessLimitError,
    NetworkAccessLimiter,
)
from services.network_access_lease_service import NetworkAccessLeaseError
from services.background_monitor_service import _device_poll_profile, _should_collect


def test_per_device_lane_serializes_operations():
    limiter = NetworkAccessLimiter(
        ssh_global_limit=2,
        ssh_per_device_limit=1,
        acquire_timeout=2,
        ssh_lease_factory=None,
    )
    active = 0
    max_active = 0
    guard = threading.Lock()

    def work():
        nonlocal active, max_active
        with limiter.ssh({"id": "device-1", "ip_address": "10.0.0.1"}):
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(work) for _ in range(2)]
        for future in futures:
            future.result(timeout=2)
    assert max_active == 1


def test_global_limit_applies_across_devices():
    limiter = NetworkAccessLimiter(
        ssh_global_limit=1,
        ssh_per_device_limit=1,
        acquire_timeout=2,
        ssh_lease_factory=None,
    )
    active = 0
    max_active = 0
    guard = threading.Lock()

    def work(device_id):
        nonlocal active, max_active
        with limiter.ssh({"id": device_id, "ip_address": device_id}):
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.03)
            with guard:
                active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(work, ("device-1", "device-2")))
    assert max_active == 1
    assert limiter.snapshot()["active_ssh"] == 0


def test_shared_lease_error_fails_closed_and_releases_process_guards():
    def unavailable_lease(**_kwargs):
        raise NetworkAccessLeaseError("shared SSH lease coordination is unavailable; access denied")

    limiter = NetworkAccessLimiter(
        ssh_global_limit=1,
        ssh_per_device_limit=1,
        acquire_timeout=0.1,
        ssh_lease_factory=unavailable_lease,
    )

    with pytest.raises(NetworkAccessLimitError, match="shared SSH lease coordination"):
        with limiter.ssh({"id": "device-1"}):
            pytest.fail("network work must not run without a shared lease")

    assert limiter.snapshot()["active_ssh"] == 0
    # A caller that owns a long-lived shared lease may bypass the nested claim.
    with limiter.ssh({"id": "device-1"}, coordinated=False):
        pass


def test_unknown_operation_label_is_not_echoed_in_errors():
    limiter = NetworkAccessLimiter(
        ssh_global_limit=1,
        ssh_per_device_limit=1,
        acquire_timeout=0.01,
        ssh_lease_factory=None,
    )
    with limiter.ssh({"id": "device-1"}):
        with pytest.raises(NetworkAccessLimitError) as error:
            with limiter.ssh(
                {"id": "device-1"},
                operation="user-provided-sensitive-label",
                timeout=0.01,
            ):
                pass
    assert "user-provided-sensitive-label" not in str(error.value)
    assert "operation=ssh" in str(error.value)


def test_cmdb_and_default_capacity_are_independent_for_the_same_device():
    limiter = NetworkAccessLimiter(
        ssh_global_limit=1, ssh_per_device_limit=1,
        acquire_timeout=0, ssh_lease_factory=None,
    )
    with limiter.ssh({"id": "device-1"}):
        with limiter.ssh({"id": "device-1"}, capacity_class="cmdb_cli"):
            assert limiter.snapshot()["active_ssh"] == 1
            assert limiter.snapshot()["active_cmdb_ssh"] == 1
            with pytest.raises(NetworkAccessLimitError):
                with limiter.ssh({"id": "device-1"}, capacity_class="cmdb_cli"):
                    pytest.fail("Duplicate CMDB session must be rejected")
    assert limiter.snapshot()["active_ssh"] == 0
    assert limiter.snapshot()["active_cmdb_ssh"] == 0


def test_cmdb_global_capacity_is_three_and_does_not_block_default_pool():
    limiter = NetworkAccessLimiter(acquire_timeout=0, ssh_lease_factory=None)
    with ExitStack() as stack:
        for device in range(3):
            stack.enter_context(limiter.ssh({"id": f"device-{device}"}, capacity_class="cmdb_cli"))
        with pytest.raises(NetworkAccessLimitError, match="global SSH"):
            with limiter.ssh({"id": "device-extra"}, capacity_class="cmdb_cli"):
                pytest.fail("CMDB capacity must not exceed three")
        with limiter.ssh({"id": "device-0"}):
            assert limiter.snapshot()["active_cmdb_ssh"] == 3
            assert limiter.snapshot()["active_ssh"] == 1
    assert limiter.snapshot()["active_cmdb_ssh"] == 0


def test_cmdb_shared_lease_failure_releases_local_capacity():
    def unavailable_lease(**kwargs):
        assert kwargs["capacity_class"] == "cmdb_cli"
        assert kwargs["global_capacity"] == 3
        assert kwargs["device_capacity"] == 1
        raise NetworkAccessLeaseError("simulated CMDB coordination failure")

    limiter = NetworkAccessLimiter(acquire_timeout=0, ssh_lease_factory=unavailable_lease)
    with pytest.raises(NetworkAccessLimitError, match="simulated CMDB"):
        with limiter.ssh({"id": "device-1"}, capacity_class="cmdb_cli"):
            pytest.fail("SSH cannot run without its shared lease")
    with limiter.ssh({"id": "device-1"}, capacity_class="cmdb_cli", coordinated=False):
        assert limiter.snapshot()["active_cmdb_ssh"] == 1
    assert limiter.snapshot()["active_cmdb_ssh"] == 0


def test_role_poll_profile_keeps_snmp_interface_frequent_and_cli_periodic():
    core = _device_poll_profile({"role": "core"})
    access = _device_poll_profile({"role": "access"})
    assert core["interface"] == 1
    assert core["info"] == 10
    assert core["protocol"] == 2
    assert access["protocol"] == 10
    assert _should_collect(1, core["interface"])
    assert not _should_collect(1, core["info"])
    assert _should_collect(10, core["info"])
    assert not _should_collect(1, access["protocol"])

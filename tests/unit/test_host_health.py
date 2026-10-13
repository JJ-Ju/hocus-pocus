"""Host side of the instance rows (review 19 papercut 4): the executor's busy time and the
registry entry keeping the name the bridge wrote."""

from __future__ import annotations

import json
import threading
import time

import pytest

from hocuspocus.host.executor import MainThreadExecutor
from hocuspocus.host.registry import InstanceRegistry

pytestmark = pytest.mark.unit


def test_executor_busy_counts_running_and_waiting_work():
    executor = MainThreadExecutor("headless", main_thread_ident=-1)
    executor.start()
    assert executor.busy_s() == 0.0
    executor.post(lambda: None)
    time.sleep(0.05)
    assert executor.busy_s() >= 0.04  # waiting since it was queued
    executor.pump_once()
    assert executor.busy_s() == 0.0
    started = threading.Event()
    release = threading.Event()

    def hold():
        started.set()
        release.wait(5)

    executor.post(hold)
    worker = threading.Thread(target=executor.pump_once)
    worker.start()
    started.wait(5)
    time.sleep(0.05)
    assert executor.busy_s() >= 0.04  # running now
    release.set()
    worker.join(5)
    assert executor.busy_s() == 0.0
    executor.stop()


def test_registry_update_keeps_the_name_the_bridge_wrote(tmp_path):
    registry = InstanceRegistry(tmp_path, pid=4242)
    registry.write({"port": 1, "token": "t", "hip": "a.hip", "generation": 0})
    data = json.loads(registry.path.read_text())
    registry.path.write_text(json.dumps(dict(data, name="worker")))  # the bridge names it
    registry.update(hip="b.hip", generation=1)
    after = json.loads(registry.path.read_text())
    assert after["name"] == "worker" and after["hip"] == "b.hip"
    registry.path.write_text(json.dumps({k: v for k, v in after.items() if k != "name"}))
    registry.update(generation=2)
    assert "name" not in json.loads(registry.path.read_text())

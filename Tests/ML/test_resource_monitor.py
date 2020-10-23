#  ------------------------------------------------------------------------------------------
#  Copyright (c) Microsoft Corporation. All rights reserved.
#  Licensed under the MIT License (MIT). See LICENSE in the repo root for license information.
#  ------------------------------------------------------------------------------------------
import os
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from GPUtil import GPU
from azureml.core import Run

from InnerEye.Common.output_directories import TestOutputDirectories
from InnerEye.Common.resource_monitor import GpuUtilization, RESOURCE_MONITOR_AGGREGATE_METRICS, ResourceMonitor


def test_utilization_enumerate() -> None:
    """
    Test if metrics are converted correctly into a loggable format.
    """
    u1 = GpuUtilization(
        id=1,
        load=0.1,
        mem_util=0.2,
        mem_allocated=30,
        mem_reserved=40,
        count=1
    )
    metrics1 = u1.enumerate()
    assert len(metrics1) == 4
    assert metrics1 == [
        # Utilization should be multiplied by 100 to get per-cent
        ('GPU1/MemUtil_Percent', 20.0),
        ('GPU1/Load_Percent', 10.0),
        ('GPU1/MemReserved_GB', 40),
        ('GPU1/MemAllocated_GB', 30),
    ]
    metrics2 = u1.enumerate(prefix="Foo")
    assert len(metrics2) == 4
    assert metrics2[0] == ('GPU1/FooMemUtil_Percent', 20.0)


def test_utilization_add() -> None:
    """
    Test arithmetic operations on a GPUUtilization object.
    """
    u1 = GpuUtilization(
        id=1,
        load=10,
        mem_util=20,
        mem_allocated=30,
        mem_reserved=40,
        count=1
    )
    u2 = GpuUtilization(
        id=2,
        load=100,
        mem_util=200,
        mem_allocated=300,
        mem_reserved=400,
        count=9
    )
    sum = u1 + u2
    assert sum == GpuUtilization(
        id=1,
        load=110,
        mem_util=220,
        mem_allocated=330,
        mem_reserved=440,
        count=10
    )


def test_utilization_average() -> None:
    """
    Test averaging on GpuUtilization objects.
    """
    sum = GpuUtilization(
        id=1,
        load=110,
        mem_util=220,
        mem_allocated=330,
        mem_reserved=440,
        count=10
    )
    # Average is the metric value divided by count
    assert sum.average() == GpuUtilization(
        id=1,
        load=11,
        mem_util=22,
        mem_allocated=33,
        mem_reserved=44,
        count=1
    )


def test_utilization_max() -> None:
    """
    Test if metric-wise maximum is computed correctly.
    """
    u1 = GpuUtilization(
        id=1,
        load=1,
        mem_util=200,
        mem_allocated=3,
        mem_reserved=400,
        count=1
    )
    u2 = GpuUtilization(
        id=2,
        load=100,
        mem_util=2,
        mem_allocated=300,
        mem_reserved=400,
        count=9
    )
    assert u1.max(u2) == GpuUtilization(
        id=1,
        load=100,
        mem_util=200,
        mem_allocated=300,
        mem_reserved=400,
        count=10
    )


def test_resource_monitor(test_output_dirs: TestOutputDirectories) -> None:
    """
    Test if metrics are correctly updated in the ResourceMonitor class.
    """
    tensorboard_folder = Path(test_output_dirs.root_dir)
    r = ResourceMonitor(interval_seconds=5, tensorboard_folder=tensorboard_folder)

    def create_gpu(id: int, load: float, mem_total: float, mem_used: float):
        return GPU(ID=id, uuid=None, load=load, memoryTotal=mem_total, memoryUsed=mem_used,
                   memoryFree=None, driver=None, gpu_name=None,
                   serial=None, display_mode=None, display_active=None, temp_gpu=None)

    # Fake objects coming from GPUtil: Two entries for GPU1, 1 entry only for GPU2
    gpu1 = create_gpu(1, 0.1, 10, 2)  # memUti=0.2
    gpu2 = create_gpu(2, 0.2, 10, 3)  # memUti=0.3
    gpu3 = create_gpu(1, 0.3, 10, 5)  # memUti=0.5
    # Mock torch calls so that we can run on CPUs. memory allocated: 2GB, reserved: 1GB
    with mock.patch("torch.cuda.memory_allocated", return_value=2 ** 31):
        with mock.patch("torch.cuda.memory_reserved", return_value=2 ** 30):
            # Update with results for both GPUs
            r.update_metrics([gpu1, gpu2])
            # Next update with data for GPU2 missing
            r.update_metrics([gpu3])
    # Element-wise maximum of metrics
    assert r.gpu_max == {
        1: GpuUtilization(id=1, load=0.3, mem_util=0.5, mem_allocated=2.0, mem_reserved=1.0, count=2),
        2: GpuUtilization(id=2, load=0.2, mem_util=0.3, mem_allocated=2.0, mem_reserved=1.0, count=1),
    }
    # Aggregates should contain the sum of metrics that were observed.
    assert r.gpu_aggregates == {
        1: GpuUtilization(id=1, load=0.4, mem_util=0.7, mem_allocated=4.0, mem_reserved=2.0, count=2),
        2: GpuUtilization(id=2, load=0.2, mem_util=0.3, mem_allocated=2.0, mem_reserved=1.0, count=1),
    }
    mock_run = Run.get_context()
    mock_run.log = MagicMock(name="run_context.log")
    mock_run.flush = MagicMock(name="run_context.flush")
    with mock.patch("azureml.core.Run.get_context", return_value=mock_run):
        with mock.patch("InnerEye.Common.resource_monitor.is_offline_run_context", return_value=False):
            r.flush()
    assert mock_run.log.call_count == 16, "Called for 2 GPUs times, max and average, 4 metrics"  # type: ignore
    assert mock_run.flush.call_count == 1  # type: ignore
    tb_file = list(Path(tensorboard_folder).rglob("*tfevents*"))[0]
    assert os.path.getsize(str(tb_file)) > 100
    aggregates_file = tensorboard_folder / RESOURCE_MONITOR_AGGREGATE_METRICS
    assert aggregates_file.is_file
    assert len(aggregates_file.read_text().splitlines()) == 16

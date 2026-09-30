from dataclasses import replace

import pytest

from d64tr_factory_tool.commands import CommandStep
from d64tr_factory_tool.runner import CommandRunner
from tests.fakes import FakeProcessFactory


@pytest.fixture
def fake_process_factory():
    return FakeProcessFactory()


@pytest.fixture
def steps():
    return (
        CommandStep("first", "First", "tool", ("one",)),
        CommandStep("second", "Second", "tool", ("two",)),
    )


def capture_runner(runner):
    outputs = []
    step_results = []
    queue_results = []
    runner.output_received.connect(lambda channel, text: outputs.append((channel, text)))
    runner.step_finished.connect(step_results.append)
    runner.queue_finished.connect(queue_results.append)
    return outputs, step_results, queue_results


def test_runner_executes_steps_in_order_and_reports_success(
    qtbot, fake_process_factory, steps
):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)

    runner.start(steps)
    fake_process_factory.finish_current(0, stdout="one\n")
    fake_process_factory.finish_current(0, stdout="two")

    assert fake_process_factory.started == [
        ("tool", ("one",)),
        ("tool", ("two",)),
    ]
    assert queue_results[-1].success is True
    assert runner.busy is False


def test_runner_stops_after_required_failure(qtbot, fake_process_factory, steps):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)
    failing_step = replace(steps[0], arguments=("fail",))

    runner.start((failing_step, steps[1]))
    fake_process_factory.finish_current(7, stderr="failed")

    assert fake_process_factory.started == [("tool", ("fail",))]
    assert queue_results[-1].success is False


def test_runner_continues_after_allowed_failure(qtbot, fake_process_factory, steps):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)
    allowed_failure = replace(steps[0], continue_on_error=True)

    runner.start((allowed_failure, steps[1]))
    fake_process_factory.finish_current(1)
    fake_process_factory.finish_current(0)

    assert len(queue_results[-1].results) == 2
    assert queue_results[-1].success is False


def test_runner_flushes_output_without_trailing_newline(
    qtbot, fake_process_factory, steps
):
    runner = CommandRunner(process_factory=fake_process_factory)
    outputs, _, _ = capture_runner(runner)

    runner.start((steps[0],))
    fake_process_factory.finish_current(0, stdout="final fragment")

    assert ("stdout", "final fragment") in outputs


def test_runner_timeout_never_starts_the_next_step(
    qtbot, fake_process_factory, steps
):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)
    short_timeout = replace(steps[0], timeout_ms=10)

    runner.start((short_timeout, steps[1]))
    qtbot.waitUntil(lambda: bool(queue_results), timeout=500)

    assert queue_results[-1].success is False
    assert queue_results[-1].results[-1].timed_out is True
    assert len(fake_process_factory.started) == 1
    assert fake_process_factory.current.terminated is True


def test_runner_cancel_never_starts_the_next_step(
    qtbot, fake_process_factory, steps
):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)

    runner.start(steps)
    runner.cancel()

    assert queue_results[-1].cancelled is True
    assert len(fake_process_factory.started) == 1
    assert fake_process_factory.current.terminated is True


def test_runner_reports_failed_to_start_as_a_process_error(
    qtbot, fake_process_factory, steps
):
    runner = CommandRunner(process_factory=fake_process_factory)
    _, _, queue_results = capture_runner(runner)

    runner.start((steps[0], steps[1]))
    fake_process_factory.fail_current_to_start("The system cannot find adb")

    assert queue_results[-1].results[-1].process_error == (
        "The system cannot find adb"
    )
    assert queue_results[-1].success is False
    assert len(fake_process_factory.started) == 1


def test_runner_rejects_concurrent_or_empty_queues(fake_process_factory, steps):
    runner = CommandRunner(process_factory=fake_process_factory)
    runner.start((steps[0],))

    with pytest.raises(RuntimeError, match="already running"):
        runner.start((steps[1],))

    runner.cancel()
    with pytest.raises(ValueError, match="at least one"):
        runner.start(())

from d64tr_factory_tool.info import build_info_steps


def test_info_steps_target_both_version_files_and_continue_independently():
    steps = build_info_steps("SERIAL")

    assert [step.arguments for step in steps] == [
        ("-s", "SERIAL", "shell", "cat", "/etc/aerora-version"),
        ("-s", "SERIAL", "shell", "cat", "/etc/gimbal-version"),
    ]
    assert [step.key for step in steps] == ["camera-version", "gimbal-version"]
    assert all(step.continue_on_error for step in steps)


def test_info_steps_have_short_timeouts():
    assert all(step.timeout_ms == 10_000 for step in build_info_steps("SERIAL"))

# D64TR Factory Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tested PySide6 factory application with Info, Update, and Configuration workflows for one D64TR device over ADB and Fastboot.

**Architecture:** Keep device parsing and command-plan construction as pure Python modules, execute plans through one asynchronous `QProcess` runner, and let each tab own only its workflow state and presentation. Every command is an argument array targeted at one resolved serial; destructive queues stop on the first error.

**Tech Stack:** Python 3.11, PySide6 6.x, pytest, pytest-qt, PyInstaller 6.x, GitHub Actions on Windows

**Spec:** `docs/superpowers/specs/2026-09-30-d64tr-factory-tool-design.md`

## Global Constraints

- The visible tab order is exactly `Info`, `Update`, `Configuration`; do not create the legacy hidden `TEST` tab.
- Keep all UI copy in English and keep `main.py` as the PyInstaller entry point.
- Support exactly one eligible device and pass its serial to every ADB/Fastboot command with `-s`.
- Never combine commands through a host shell or interpolate operator input into shell command strings.
- Treat boot and system images as required; treat `abl.elf` as optional and log its omission.
- Apply only checked configuration rows, append exactly one `sync`, and never reboot automatically.
- Do not add camera type, connection type, or autopilot mode configuration in this release.
- Run all hardware-independent tests with `QT_QPA_PLATFORM=offscreen`; tests must never invoke real ADB or Fastboot.

## Review Focus

- ADB/Fastboot output with CRLF, blank lines, or ADB daemon chatter must still resolve devices correctly; Task 1 adds parser coverage.
- Update directories containing spaces or non-ASCII characters must remain one command argument; Task 4 adds exact argument coverage.
- Output without a trailing newline must not disappear when a process exits; Task 2 adds final-buffer coverage.
- Programmatic widget updates during Configuration refresh must not mark settings for application; Task 7 adds signal-blocking coverage.
- Closing the window during an active operation must cancel it and prevent the next queued command; Task 8 adds shutdown coverage.

---

### Task 1: Project Foundation, Command Types, and Device Resolution

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `pytest.ini`
- Create: `.gitignore`
- Create: `d64tr_factory_tool/__init__.py`
- Create: `d64tr_factory_tool/commands.py`
- Create: `d64tr_factory_tool/devices.py`
- Test: `tests/test_devices.py`

**Interfaces:**
- Consumes: No earlier task interfaces.
- Produces: `CommandStep`, `CommandResult`, and `QueueResult` dataclasses; `DeviceRecord`; `parse_adb_devices(output: str) -> tuple[DeviceRecord, ...]`; `parse_fastboot_devices(output: str) -> tuple[str, ...]`; `require_single_adb_device(output: str) -> str`; `require_single_fastboot_device(output: str, expected_serial: str | None = None) -> str`; `DeviceSelectionError`; `build_device_list_step(transport: Literal["adb", "fastboot"]) -> CommandStep`.

- [ ] **Step 1: Add the Python and test environment configuration**

Set `requirements.txt` to `PySide6>=6.5,<7`. Make `requirements-dev.txt` include the runtime requirements plus `pytest>=8,<9`, `pytest-qt>=4.4,<5`, and `pyinstaller>=6,<7`. Configure pytest for PySide6 and ignore generated build directories; ignore `.venv/`, caches, `build/`, `dist/`, and PyInstaller spec files in `.gitignore`.

- [ ] **Step 2: Install the declared development dependencies**

Run: `python -m pip install -r requirements-dev.txt`
Expected: exit code 0 and imports for `PySide6`, `pytest`, and `pytestqt` succeed.

- [ ] **Step 3: Write failing device and command-model tests**

```python
def test_parse_adb_devices_preserves_noneligible_states_and_ignores_chatter():
    output = "* daemon started successfully *\r\nList of devices attached\r\nABC\tdevice\r\nBAD\tunauthorized\r\nOFF\toffline\r\n\r\n"
    assert [(item.serial, item.state) for item in parse_adb_devices(output)] == [
        ("ABC", "device"), ("BAD", "unauthorized"), ("OFF", "offline")
    ]

def test_require_single_adb_device_rejects_zero_and_multiple_eligible_devices():
    with pytest.raises(DeviceSelectionError, match="No eligible ADB device"):
        require_single_adb_device("List of devices attached\nBAD\tunauthorized\n")
    with pytest.raises(DeviceSelectionError, match="Multiple ADB devices"):
        require_single_adb_device("List of devices attached\nA\tdevice\nB\tdevice\n")

def test_require_single_fastboot_device_enforces_expected_serial():
    assert require_single_fastboot_device("ABC\tfastboot\r\n", "ABC") == "ABC"
    with pytest.raises(DeviceSelectionError, match="expected ABC"):
        require_single_fastboot_device("OTHER\tfastboot\n", "ABC")

def test_device_list_steps_are_argument_arrays():
    assert build_device_list_step("adb").program == "adb"
    assert build_device_list_step("adb").arguments == ("devices",)
    assert build_device_list_step("fastboot").arguments == ("devices",)
```

- [ ] **Step 4: Run the tests and verify RED**

Run: `python -m pytest tests/test_devices.py -v`
Expected: FAIL during import because `d64tr_factory_tool.commands` and `devices` do not exist.

- [ ] **Step 5: Implement the command dataclasses and strict parsers**

In `commands.py`, define immutable `CommandStep(key: str, label: str, program: str, arguments: tuple[str, ...], timeout_ms: int | None = 10000, continue_on_error: bool = False)`, `CommandResult(step: CommandStep, exit_code: int, stdout: str, stderr: str, timed_out: bool = False, process_error: str | None = None)`, and `QueueResult(results: tuple[CommandResult, ...], cancelled: bool = False)` with a derived `success` property. In `devices.py`, parse complete lines, retain ADB states for diagnostics, accept only state `device`, enforce one eligible target, and include all observed serial/state pairs in selection errors.

- [ ] **Step 6: Run the focused and current full suites**

Run: `python -m pytest tests/test_devices.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add .gitignore requirements.txt requirements-dev.txt pytest.ini d64tr_factory_tool tests/test_devices.py
git commit -m "feat: add command and device foundations"
```

### Task 2: Asynchronous Command Runner

**Files:**
- Create: `d64tr_factory_tool/runner.py`
- Create: `tests/fakes.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `CommandStep`, `CommandResult`, and `QueueResult` from Task 1.
- Produces: `CommandRunner(QObject)` with `start(steps: Sequence[CommandStep]) -> None`, `cancel() -> None`, `busy: bool`, and signals `step_started(object)`, `output_received(str, str)`, `step_finished(object)`, `queue_finished(object)`.

- [ ] **Step 1: Write failing runner tests with a controllable fake process**

```python
def test_runner_executes_steps_in_order_and_reports_success(qtbot, fake_process_factory):
    runner = CommandRunner(process_factory=fake_process_factory)
    runner.start((first_step, second_step))
    fake_process_factory.finish_current(0, stdout="one\n")
    fake_process_factory.finish_current(0, stdout="two")
    assert fake_process_factory.started == [("tool", ("one",)), ("tool", ("two",))]
    assert finished_results[-1].success is True

def test_runner_stops_after_required_failure(qtbot, fake_process_factory):
    runner.start((failing_step, must_not_run))
    fake_process_factory.finish_current(7, stderr="failed")
    assert fake_process_factory.started == [("tool", ("fail",))]
    assert finished_results[-1].success is False

def test_runner_continues_after_allowed_failure(qtbot, fake_process_factory):
    runner.start((replace(failing_step, continue_on_error=True), second_step))
    fake_process_factory.finish_current(1)
    fake_process_factory.finish_current(0)
    assert len(finished_results[-1].results) == 2

def test_runner_flushes_output_without_trailing_newline(qtbot, fake_process_factory):
    fake_process_factory.finish_current(0, stdout="final fragment")
    assert ("stdout", "final fragment") in outputs

def test_runner_timeout_and_cancel_never_start_the_next_step(qtbot, fake_process_factory):
    runner.start((short_timeout_step, second_step))
    qtbot.waitUntil(lambda: finished_results, timeout=500)
    assert finished_results[-1].success is False
    assert len(fake_process_factory.started) == 1

def test_runner_reports_failed_to_start_as_a_process_error(qtbot, fake_process_factory):
    fake_process_factory.fail_to_start("The system cannot find adb")
    assert finished_results[-1].results[-1].process_error == "The system cannot find adb"
    assert finished_results[-1].success is False
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_runner.py -v`
Expected: FAIL importing `CommandRunner`.

- [ ] **Step 3: Implement `CommandRunner`**

Use one injected process instance at a time and a per-step single-shot `QTimer`. Drain both output channels during execution and once more on finish, handle `QProcess.errorOccurred` including `FailedToStart`, build one `CommandResult` per step, continue only when the result succeeds or `continue_on_error` is true, and emit exactly one `queue_finished` result. `cancel()` must stop the timer, terminate then kill an active process if necessary, clear pending steps, and finish with `cancelled=True`.

- [ ] **Step 4: Run the focused and full suites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_runner.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS with no Qt warnings.

- [ ] **Step 5: Commit**

```bash
git add d64tr_factory_tool/runner.py tests/fakes.py tests/test_runner.py
git commit -m "feat: add asynchronous command runner"
```

### Task 3: Info Command Plan and Tab

**Files:**
- Create: `d64tr_factory_tool/info.py`
- Create: `d64tr_factory_tool/info_tab.py`
- Test: `tests/test_info.py`
- Test: `tests/test_info_tab.py`

**Interfaces:**
- Consumes: Task 1 device-list and command types; Task 2 `CommandRunner`.
- Produces: `build_info_steps(serial: str) -> tuple[CommandStep, CommandStep]`; `InfoTab(runner_factory: Callable[[], CommandRunner] = CommandRunner)`; `InfoTab.shutdown() -> None`.

- [ ] **Step 1: Write failing plan and widget tests**

```python
def test_info_steps_target_both_version_files_and_continue_independently():
    steps = build_info_steps("SERIAL")
    assert [step.arguments for step in steps] == [
        ("-s", "SERIAL", "shell", "cat", "/etc/aerora-version"),
        ("-s", "SERIAL", "shell", "cat", "/etc/gimbal-version"),
    ]
    assert all(step.continue_on_error for step in steps)

def test_info_tab_has_refresh_clear_and_read_only_log(qtbot, fake_runner_factory):
    tab = InfoTab(runner_factory=fake_runner_factory)
    qtbot.addWidget(tab)
    assert tab.refresh_button.text() == "Refresh"
    assert tab.clear_button.text() == "Clear"
    assert tab.log.isReadOnly()

def test_info_tab_reports_one_failed_read_and_the_other_result(qtbot, fake_runner_factory):
    # Complete device detection, fail Camera Version, and succeed Gimbal Version.
    assert "Camera Version" in tab.log.toPlainText()
    assert "FAILED" in tab.log.toPlainText()
    assert "Gimbal Version" in tab.log.toPlainText()
    assert "gimbal-1.2" in tab.log.toPlainText()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_info.py tests/test_info_tab.py -v`
Expected: FAIL importing the Info plan and widget.

- [ ] **Step 3: Implement the Info plan and two-phase UI workflow**

On Refresh, first run `adb devices`, resolve one eligible serial, then start the two continue-on-error reads. Label results by each step key instead of parsing text output. Keep timestamp formatting in a small `append_log(text: str, timestamp: bool = True)` method, disable Refresh while active, and let Clear operate locally at all times.

- [ ] **Step 4: Run the focused and full suites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_info.py tests/test_info_tab.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add d64tr_factory_tool/info.py d64tr_factory_tool/info_tab.py tests/test_info.py tests/test_info_tab.py
git commit -m "feat: add camera information tab"
```

### Task 4: Update Package Validation and Flash Plans

**Files:**
- Create: `d64tr_factory_tool/update.py`
- Test: `tests/test_update.py`

**Interfaces:**
- Consumes: `CommandStep` from Task 1.
- Produces: constants `BOOT_IMAGE_NAME`, `SYSTEM_IMAGE_NAME`, `ABL_IMAGE_NAME`; `UpdatePackage`; `PackageValidationError`; `validate_update_package(root: Path) -> UpdatePackage`; `build_enter_bootloader_steps(serial: str) -> tuple[CommandStep, ...]`; `build_flash_steps(package: UpdatePackage, serial: str) -> tuple[CommandStep, ...]`; `build_fastboot_reboot_step(serial: str) -> CommandStep`.

- [ ] **Step 1: Write failing package and command-plan tests**

```python
def test_validate_package_accepts_optional_abl_absence(tmp_path):
    touch_required_images(tmp_path)
    package = validate_update_package(tmp_path)
    assert package.abl is None
    assert package.boot.name == BOOT_IMAGE_NAME
    assert package.system.name == SYSTEM_IMAGE_NAME

@pytest.mark.parametrize("missing", [BOOT_IMAGE_NAME, SYSTEM_IMAGE_NAME])
def test_validate_package_rejects_each_missing_required_image(tmp_path, missing):
    touch_required_images(tmp_path)
    (tmp_path / missing).unlink()
    with pytest.raises(PackageValidationError) as error:
        validate_update_package(tmp_path)
    assert error.value.missing == (missing,)

def test_flash_plan_with_abl_has_exact_order_and_serial(tmp_path):
    package = make_valid_package(tmp_path, include_abl=True)
    assert [(step.program, step.arguments) for step in build_flash_steps(package, "SER")] == [
        ("fastboot", ("-s", "SER", "flash", "abl_a", str(package.abl))),
        ("fastboot", ("-s", "SER", "flash", "abl_b", str(package.abl))),
        ("fastboot", ("-s", "SER", "--slot", "all", "flash", "boot", str(package.boot))),
        ("fastboot", ("-s", "SER", "--slot", "all", "flash", "system", str(package.system))),
    ]

def test_paths_with_spaces_and_unicode_remain_single_arguments(tmp_path):
    root = tmp_path / "D64TR 固件 package"
    package = make_valid_package(root, include_abl=False)
    steps = build_flash_steps(package, "SER")
    assert steps[0].arguments[-1] == str(package.boot)
    assert steps[1].arguments[-1] == str(package.system)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `python -m pytest tests/test_update.py -v`
Expected: FAIL importing `d64tr_factory_tool.update`.

- [ ] **Step 3: Implement immutable package validation and exact plans**

Resolve the selected root to an absolute `Path`; report all missing required filenames in deterministic boot/system order. Set `timeout_ms=None` on flash steps, keep short timeouts on ADB entry and reboot, and use labels that name `abl_a`, `abl_b`, `boot`, and `system` for failure reporting.

- [ ] **Step 4: Run the focused and full suites**

Run: `python -m pytest tests/test_update.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add d64tr_factory_tool/update.py tests/test_update.py
git commit -m "feat: add D64TR update plans"
```

### Task 5: Update Tab State Machine

**Files:**
- Create: `d64tr_factory_tool/update_tab.py`
- Test: `tests/test_update_tab.py`

**Interfaces:**
- Consumes: Task 1 device resolution; Task 2 runner; Task 4 validation and command builders.
- Produces: `UpdateTab(runner_factory: Callable[[], CommandRunner] = CommandRunner)`; `set_update_folder(path: Path) -> None`; `shutdown() -> None`.

- [ ] **Step 1: Write failing widget and state-transition tests**

```python
def test_update_tab_disables_update_for_missing_required_image(qtbot, tmp_path):
    tab.set_update_folder(tmp_path)
    assert not tab.update_button.isEnabled()
    assert "Missing" in tab.boot_status.text()

def test_update_tab_allows_missing_optional_abl_after_fastboot_detection(qtbot, valid_package):
    tab.set_update_folder(valid_package)
    finish_fastboot_probe("SER\tfastboot\n")
    assert "Optional" in tab.abl_status.text()
    assert tab.update_button.isEnabled()

def test_enter_mode_uses_existing_fastboot_device_without_adb_reboot(qtbot):
    click_enter_mode_and_finish_probe("SER\tfastboot\n")
    assert started_programs == ["fastboot"]
    assert tab.fastboot_serial == "SER"

def test_enter_mode_falls_back_to_root_wait_reboot_and_bounded_poll(qtbot):
    finish_initial_fastboot_probe("")
    finish_adb_probe("List of devices attached\nSER\tdevice\n")
    assert queued_arguments == [
        ("-s", "SER", "root"),
        ("-s", "SER", "wait-for-device"),
        ("-s", "SER", "reboot", "bootloader"),
    ]

def test_flash_failure_stops_plan_and_never_enables_reboot(qtbot, valid_package_with_abl):
    start_flash_then_fail("flash-abl-a")
    assert not tab.reboot_button.isEnabled()
    assert "abl_a" in tab.log.toPlainText()
    assert "FAILED" in tab.log.toPlainText()
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_update_tab.py -v`
Expected: FAIL importing `UpdateTab`.

- [ ] **Step 3: Implement the explicit update states and UI**

Build the folder picker, three artifact status labels, `Enter Update Mode`, `Update`, `Reboot`, and a read-only log. Track `fastboot_serial`, current package, and phase (`idle`, `probing`, `entering`, `polling`, `flashing`, `ready_to_reboot`). Poll with `QTimer` for at most 10 attempts at one-second intervals, enforce the expected serial after ADB transition, revalidate files immediately before flash, log the optional ABL skip, and derive every button's enabled state from phase plus package validity.

- [ ] **Step 4: Add success, multiple-device, missing-tool, and shutdown tests**

```python
def test_successful_full_flash_enables_reboot_and_logs_optional_abl_skip(qtbot):
    complete_flash_successfully(package_without_abl)
    assert tab.reboot_button.isEnabled()
    assert "ABL image not present; skipped" in tab.log.toPlainText()

def test_multiple_fastboot_devices_never_start_flash(qtbot):
    finish_fastboot_probe("A\tfastboot\nB\tfastboot\n")
    assert "Multiple Fastboot devices" in tab.log.toPlainText()
    assert no_destructive_queue_started()

def test_missing_fastboot_executable_restores_controls(qtbot):
    fail_current_process_to_start("fastboot was not found")
    assert tab.enter_mode_button.isEnabled()
    assert "fastboot was not found" in tab.log.toPlainText()

def test_shutdown_cancels_runner_and_poll_timer(qtbot):
    tab.shutdown()
    assert fake_runner.cancelled
    assert not tab.poll_timer.isActive()
```

- [ ] **Step 5: Run the focused and full suites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_update_tab.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add d64tr_factory_tool/update_tab.py tests/test_update_tab.py
git commit -m "feat: add safe firmware update workflow"
```

### Task 6: Configuration Model, Validation, and Command Plans

**Files:**
- Create: `d64tr_factory_tool/configuration.py`
- Test: `tests/test_configuration.py`

**Interfaces:**
- Consumes: `CommandStep` and `CommandResult` from Task 1.
- Produces: `ConfigSelection(ethernet_range: str | None = None, preview_mode: str | None = None, bitrate_mbps: str | None = None, encoder: str | None = None)`; `CurrentConfig`; `ConfigurationError`; `mbps_to_bps(text: str) -> str`; `bps_to_mbps(text: str) -> str`; `build_config_read_steps(serial: str) -> tuple[CommandStep, ...]`; `current_config_from_results(results: Sequence[CommandResult]) -> CurrentConfig`; `build_config_apply_steps(serial: str, selection: ConfigSelection) -> tuple[CommandStep, ...]`; `build_adb_reboot_step(serial: str) -> CommandStep`.

- [ ] **Step 1: Write failing bitrate and selection tests**

```python
@pytest.mark.parametrize(("text", "expected"), [("10", "10000000"), (" 2.5 ", "2500000"), ("0.000001", "1")])
def test_mbps_to_bps_uses_exact_decimal_conversion(text, expected):
    assert mbps_to_bps(text) == expected

@pytest.mark.parametrize(("text", "expected"), [("10000000", "10"), ("2500000", "2.5")])
def test_bps_to_mbps_returns_concise_display_value(text, expected):
    assert bps_to_mbps(text) == expected

@pytest.mark.parametrize("text", ["", "abc", "0", "-1", "NaN", "Infinity", "0.0000001"])
def test_mbps_to_bps_rejects_invalid_or_sub_bps_values(text):
    with pytest.raises(ConfigurationError):
        mbps_to_bps(text)

def test_apply_plan_contains_selected_properties_in_ui_order_and_one_sync():
    selection = ConfigSelection(ethernet_range="144", bitrate_mbps="2.5", encoder="h265")
    steps = build_config_apply_steps("SER", selection)
    assert [step.arguments[-2:] for step in steps[:-1]] == [
        ("persist.eth0.ip.range", "144"),
        ("persist.video.preview.bitrate", "2500000"),
        ("persist.video.preview.encoder", "h265"),
    ]
    assert steps[-1].arguments == ("-s", "SER", "shell", "sync")

def test_apply_plan_rejects_empty_selection_before_building_commands():
    with pytest.raises(ConfigurationError, match="Select at least one"):
        build_config_apply_steps("SER", ConfigSelection())
```

- [ ] **Step 2: Write failing read-plan and result-mapping tests**

Assert the read keys and property names are in Ethernet, resolution, bitrate, encoder order; successful stdout is stripped into `CurrentConfig`; and an empty/failed property remains explicitly unknown rather than receiving a default.

- [ ] **Step 3: Run the tests and verify RED**

Run: `python -m pytest tests/test_configuration.py -v`
Expected: FAIL importing the configuration module.

- [ ] **Step 4: Implement exact decimal validation and configuration plans**

Use `Decimal`, require a finite positive value, multiply or divide by exactly `1_000_000`, reject a non-integral bps result on input, and format device bps without trailing fractional zeros. Validate Ethernet values against `144|199`, modes against `1920x1080@30|1280x720@30`, and encoders against `h264|h265`. Build each set operation as `adb -s SERIAL shell setprop PROPERTY VALUE`, followed by one required sync step.

- [ ] **Step 5: Run the focused and full suites**

Run: `python -m pytest tests/test_configuration.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add d64tr_factory_tool/configuration.py tests/test_configuration.py
git commit -m "feat: add persistent configuration plans"
```

### Task 7: Configuration Tab and Batch Apply Workflow

**Files:**
- Create: `d64tr_factory_tool/config_tab.py`
- Test: `tests/test_config_tab.py`

**Interfaces:**
- Consumes: Task 1 device resolution; Task 2 runner; Task 6 configuration model and plans.
- Produces: `ConfigTab(runner_factory: Callable[[], CommandRunner] = CommandRunner)`; `shutdown() -> None`.

- [ ] **Step 1: Write failing layout, selection, and refresh tests**

```python
def test_config_tab_has_four_apply_rows_and_manual_reboot(qtbot):
    assert [box.text() for box in tab.apply_checkboxes] == ["Apply"] * 4
    assert tab.apply_button.text() == "Apply Selected"
    assert tab.reboot_button.text() == "Reboot Device"
    assert not tab.reboot_button.isEnabled()

def test_user_edit_automatically_checks_only_that_row(qtbot):
    tab.bitrate_edit.setText("2.5")
    assert tab.bitrate_apply.isChecked()
    assert not tab.encoder_apply.isChecked()

def test_refresh_populates_known_values_without_selecting_them(qtbot, fake_runner_factory):
    finish_refresh(ethernet="199", mode="1280x720@30", bitrate="2500000", encoder="h264")
    assert tab.bitrate_edit.text() == "2.5"
    assert all(not box.isChecked() for box in tab.apply_checkboxes)

def test_refresh_displays_unknown_raw_value_without_overwriting_editor(qtbot):
    finish_refresh(mode="custom-mode")
    assert tab.preview_current.text() == "custom-mode"
    assert not tab.preview_apply.isChecked()

def test_h265_selection_shows_exact_uvc_warning(qtbot):
    tab.encoder_combo.setCurrentData("h265")
    assert "UVC preview is unavailable" in tab.encoder_warning.text()

def test_first_show_starts_one_refresh_but_reshow_does_not(qtbot, fake_runner_factory):
    tab.show()
    qtbot.wait(0)
    tab.hide()
    tab.show()
    assert fake_runner_factory.device_probe_count == 1
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_config_tab.py -v`
Expected: FAIL importing `ConfigTab`.

- [ ] **Step 3: Implement refresh, editors, and signal-safe current-value display**

Create one row per setting with a current-value label, editor, and Apply checkbox. Use item data for normalized combo values and `QSignalBlocker` while refresh results populate editors. Convert device bps back to a concise Mbps decimal for display, preserve unknown raw values in current labels, and clear all checkboxes only after a completed refresh. Schedule exactly one initial Refresh from the first `showEvent`; later shows preserve the operator's in-progress edits.

- [ ] **Step 4: Add failing apply/reboot workflow tests**

```python
def test_invalid_checked_bitrate_starts_no_device_command(qtbot):
    tab.bitrate_edit.setText("not-a-number")
    tab.apply_button.click()
    assert fake_runner_factory.started == []
    assert "valid positive bitrate" in tab.log.toPlainText()

def test_empty_selection_starts_no_apply_queue(qtbot):
    tab.apply_button.click()
    assert "Select at least one setting" in tab.log.toPlainText()

def test_selected_subset_uses_domain_plan_and_stops_before_sync_on_failure(qtbot):
    select_ethernet_and_encoder(tab)
    finish_device_probe("SER")
    fail_apply_step("set-encoder")
    assert started_step_keys == ["set-ethernet", "set-encoder"]
    assert "Refresh before retrying" in tab.log.toPlainText()

def test_apply_success_clears_selection_and_enables_manual_reboot(qtbot):
    complete_apply_successfully()
    assert all(not box.isChecked() for box in tab.apply_checkboxes)
    assert tab.reboot_button.isEnabled()
    tab.bitrate_edit.setText("12")
    assert tab.reboot_button.isEnabled()
    assert tab.bitrate_apply.isChecked()

def test_reboot_resolves_and_targets_the_current_adb_serial(qtbot):
    tab.reboot_button.click()
    finish_device_probe("NEW-SERIAL")
    assert queued_steps[-1].arguments == ("-s", "NEW-SERIAL", "reboot")
```

- [ ] **Step 5: Implement batch apply and explicit reboot**

Resolve an ADB target immediately before each apply or reboot action. Validate the complete checked selection before starting writes. Disable conflicting controls while active, append per-step results, enable Reboot only after a successful apply, and do not run reboot automatically.

- [ ] **Step 6: Run the focused and full suites**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_config_tab.py -v && QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add d64tr_factory_tool/config_tab.py tests/test_config_tab.py
git commit -m "feat: add batch configuration tab"
```

### Task 8: Main Window, Shutdown, Documentation, and Windows Package

**Files:**
- Create: `d64tr_factory_tool/main_window.py`
- Create: `main.py`
- Create: `tests/test_main_window.py`
- Create: `README.md`
- Create: `.github/workflows/build-windows-package.yml`

**Interfaces:**
- Consumes: `InfoTab`, `UpdateTab`, and `ConfigTab` from Tasks 3, 5, and 7.
- Produces: `MainWindow(tab_factories: tuple[Callable[[], QWidget], Callable[[], QWidget], Callable[[], QWidget]] | None = None)`; `main() -> int`; documented source and packaged launch workflows.

- [ ] **Step 1: Write failing main-window and shutdown tests**

```python
def test_main_window_has_exactly_three_tabs_in_required_order(qtbot):
    window = MainWindow(tab_factories=fake_tab_factories)
    qtbot.addWidget(window)
    assert window.tabs.count() == 3
    assert [window.tabs.tabText(i) for i in range(3)] == ["Info", "Update", "Configuration"]

def test_close_cancels_every_tab_and_prevents_queued_work(qtbot):
    window = MainWindow(tab_factories=fake_tab_factories)
    window.close()
    assert all(tab.shutdown_called == 1 for tab in created_tabs)
    assert all(tab.started_after_shutdown == 0 for tab in created_tabs)
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest tests/test_main_window.py -v`
Expected: FAIL importing `MainWindow`.

- [ ] **Step 3: Implement the window and entry point**

Create a resizable, centered window titled `D64TR Factory Tool`; add only the three required tabs; call each tab's `shutdown()` from `closeEvent`; and make `main.py` create `QApplication`, show `MainWindow`, and return the application exit code under an `if __name__ == "__main__"` guard.

- [ ] **Step 4: Run the full automated suite**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q`
Expected: all tests PASS with no collection errors, Qt warnings, or calls to real device tools.

- [ ] **Step 5: Write operator and developer documentation**

Document Python 3.11 setup, `adb`/`fastboot` PATH requirements, the two required and one optional update files, single-device restriction, Info/Update/Configuration workflows, H.265 UVC warning, source launch, test command, PyInstaller command, and troubleshooting for unauthorized/offline/multiple devices and failed flashes.

- [ ] **Step 6: Add the Windows test-and-package workflow**

Use Python 3.11 on `windows-latest`; install `requirements-dev.txt`; set `QT_QPA_PLATFORM=offscreen`; run `python -m pytest -q`; derive a sanitized version from the latest tag plus commit count; build with `pyinstaller --onefile --windowed --name "d64tr-factory-tool-$env:APP_VERSION" main.py`; and upload only the resulting executable.

- [ ] **Step 7: Verify packaging metadata and the local entry point**

Run: `python -m PyInstaller --clean --onefile --windowed --name d64tr-factory-tool-smoke main.py`
Expected: exit code 0 and `dist/d64tr-factory-tool-smoke` (or `.exe` on Windows) exists.

Run: `QT_QPA_PLATFORM=offscreen python -c "from PySide6.QtCore import QTimer; from PySide6.QtWidgets import QApplication; from d64tr_factory_tool.main_window import MainWindow; app=QApplication([]); window=MainWindow(); window.show(); QTimer.singleShot(100, app.quit); app.exec()"`
Expected: exit code 0 with no traceback.

- [ ] **Step 8: Run final repository verification**

Run: `QT_QPA_PLATFORM=offscreen python -m pytest -q && git diff --check && git status --short`
Expected: all tests PASS; `git diff --check` prints nothing; status lists only the intended Task 8 files before commit.

- [ ] **Step 9: Commit**

```bash
git add main.py d64tr_factory_tool/main_window.py tests/test_main_window.py README.md requirements-dev.txt .github/workflows/build-windows-package.yml
git commit -m "feat: ship D64TR factory tool"
```

- [ ] **Step 10: Perform a hardware handoff check without executing it automatically**

Record the manual acceptance sequence for a factory operator: connect exactly one D64TR; Refresh Info; Refresh and apply a safe Configuration selection, then reboot; enter Fastboot; validate both a package without ABL and a release package with ABL; flash the approved package; reboot; and confirm the reported versions. Do not run this sequence unless an authorized device and approved firmware package are explicitly provided.

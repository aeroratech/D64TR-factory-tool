from pathlib import Path

import pytest

from d64tr_factory_tool.update import (
    ABL_IMAGE_NAME,
    BOOT_IMAGE_NAME,
    SYSTEM_IMAGE_NAME,
    PackageValidationError,
    build_enter_bootloader_steps,
    build_fastboot_reboot_step,
    build_flash_steps,
    validate_update_package,
)


def touch_required_images(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / BOOT_IMAGE_NAME).touch()
    (root / SYSTEM_IMAGE_NAME).touch()


def make_valid_package(root: Path, include_abl: bool):
    touch_required_images(root)
    if include_abl:
        (root / ABL_IMAGE_NAME).touch()
    return validate_update_package(root)


def test_validate_package_accepts_optional_abl_absence(tmp_path):
    touch_required_images(tmp_path)

    package = validate_update_package(tmp_path)

    assert package.root == tmp_path.resolve()
    assert package.abl is None
    assert package.boot.name == BOOT_IMAGE_NAME
    assert package.system.name == SYSTEM_IMAGE_NAME


def test_validate_package_includes_optional_abl_when_present(tmp_path):
    package = make_valid_package(tmp_path, include_abl=True)

    assert package.abl == tmp_path.resolve() / ABL_IMAGE_NAME


@pytest.mark.parametrize("missing", [BOOT_IMAGE_NAME, SYSTEM_IMAGE_NAME])
def test_validate_package_rejects_each_missing_required_image(tmp_path, missing):
    touch_required_images(tmp_path)
    (tmp_path / missing).unlink()

    with pytest.raises(PackageValidationError) as error:
        validate_update_package(tmp_path)

    assert error.value.missing == (missing,)


def test_validate_package_reports_all_missing_files_in_stable_order(tmp_path):
    with pytest.raises(PackageValidationError) as error:
        validate_update_package(tmp_path)

    assert error.value.missing == (BOOT_IMAGE_NAME, SYSTEM_IMAGE_NAME)


def test_validate_package_rejects_file_instead_of_directory(tmp_path):
    selected_file = tmp_path / "not-a-directory"
    selected_file.touch()

    with pytest.raises(PackageValidationError, match="not a directory"):
        validate_update_package(selected_file)


def test_flash_plan_with_abl_has_exact_order_and_serial(tmp_path):
    package = make_valid_package(tmp_path, include_abl=True)

    assert [
        (step.program, step.arguments) for step in build_flash_steps(package, "SER")
    ] == [
        ("fastboot", ("-s", "SER", "flash", "abl_a", str(package.abl))),
        ("fastboot", ("-s", "SER", "flash", "abl_b", str(package.abl))),
        (
            "fastboot",
            (
                "-s",
                "SER",
                "--slot",
                "all",
                "flash",
                "boot",
                str(package.boot),
            ),
        ),
        (
            "fastboot",
            (
                "-s",
                "SER",
                "--slot",
                "all",
                "flash",
                "system",
                str(package.system),
            ),
        ),
    ]


def test_flash_plan_without_abl_contains_only_boot_and_system(tmp_path):
    package = make_valid_package(tmp_path, include_abl=False)

    steps = build_flash_steps(package, "SER")

    assert [step.key for step in steps] == ["flash-boot", "flash-system"]
    assert all(step.timeout_ms is None for step in steps)


def test_paths_with_spaces_and_unicode_remain_single_arguments(tmp_path):
    root = tmp_path / "D64TR 固件 package"
    package = make_valid_package(root, include_abl=False)

    steps = build_flash_steps(package, "SER")

    assert steps[0].arguments[-1] == str(package.boot)
    assert steps[1].arguments[-1] == str(package.system)


def test_enter_bootloader_plan_targets_serial_in_required_order():
    steps = build_enter_bootloader_steps("SER")

    assert [step.arguments for step in steps] == [
        ("-s", "SER", "root"),
        ("-s", "SER", "wait-for-device"),
        ("-s", "SER", "reboot", "bootloader"),
    ]
    assert all(step.timeout_ms is not None for step in steps)


def test_fastboot_reboot_step_targets_serial():
    step = build_fastboot_reboot_step("SER")

    assert step.program == "fastboot"
    assert step.arguments == ("-s", "SER", "reboot")

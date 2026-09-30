# D64TR Factory Tool Design

## Purpose

Build a Windows-oriented PySide6 desktop application for factory operators to inspect and
configure one D64TR camera and to install its firmware over ADB and Fastboot. The application
keeps the familiar three-tab workflow from `~/work/factory_tool`, while replacing the legacy
camera-type and connection configuration with the persistent properties documented by
OpenMAVCam.

The first release has three visible tabs only: `Info`, `Update`, and `Configuration`. All UI text
is English. The application is distributed as a versioned, single-file Windows executable and
also remains runnable from Python on development hosts.

Reference documentation:

- [OpenMAVCam Configuration](https://openmavcam.github.io/docs/api-reference/configuration-interfaces)
- [D64TR deployment](https://openmavcam.github.io/docs/products/d64tr/deploy)

## Goals

- Read the camera and gimbal version files without blocking the UI.
- Validate a selected update directory and flash the D64TR bootloader, boot image, and system
  image in a safe, ordered workflow.
- Make `abl.elf` optional: flash both A/B ABL partitions when present and explicitly skip ABL
  when absent.
- Read the current persistent configuration and apply any selected subset of Ethernet, preview
  resolution, preview bitrate, and preview encoder settings in one batch.
- Flush configuration once and let the operator explicitly reboot after a successful batch.
- Stop destructive workflows on the first error and prevent ambiguous multi-device operations.
- Keep command construction and sequencing independently testable without camera hardware.

## Non-goals

- Camera brand/model selection.
- USB, Ethernet, or WLAN MAVLink connection selection.
- Standalone/autopilot mode selection. This will be designed in a later release.
- The reference tool's hidden `TEST` tab or its dual-mode, SD card, and parameter-reset actions.
- Concurrent operation on multiple D64TR devices.
- Downloading firmware or discovering update artifacts outside the operator-selected directory.

## Application Structure

`main.py` is the PyInstaller entry point. Application code is organized into a small package with
clear ownership:

- Main window: constructs the application shell and the three visible tabs.
- Info tab: presents camera/gimbal information and starts the read workflow.
- Update tab: selects and validates an update directory, controls the bootloader transition,
  starts flashing, and presents progress.
- Configuration tab: reads persistent properties, validates operator input, selects which
  settings to apply, and controls apply/reboot actions.
- Command runner: executes argument arrays asynchronously with `QProcess`, forwards stdout and
  stderr, enforces per-step failure policy and timeout, and reports queue completion.
- Pure command builders: create information, configuration, and update command plans. They do not
  import UI classes and can be tested without ADB, Fastboot, or hardware.

Commands are represented as program-plus-argument arrays. The host shell is not used to combine
commands or interpolate operator data. A queue runs one process at a time, and a nonzero exit code
stops the queue unless the caller explicitly marks a read-only step as allowed to continue.

## Device Selection and Process Safety

The first release supports exactly one target. Before an ADB or Fastboot operation, the relevant
device listing is parsed:

- No eligible device: do not start the requested operation and explain how the operator can
  recover.
- One eligible device: address it by serial number for every subsequent command in that workflow.
- More than one eligible device: refuse the operation, display the serial numbers, and ask the
  operator to leave only the intended target connected.
- An unauthorized or offline ADB target is not eligible and is reported with its state.

Addressing each command by the resolved serial prevents a device attached during a long operation
from becoming the implicit target. Controls that could start a conflicting operation are disabled
while a queue is active. Closing the application terminates any active child process and prevents
the next queued command from starting.

Short information, detection, and configuration commands have bounded timeouts and report a
timeout as failure. System-image flashing is expected to take a long time and is not subject to a
short command timeout.

If `adb` or `fastboot` is not found, the application reports the missing executable and does not
advance the workflow.

## Main Window

The main window contains three English tabs in this order:

1. `Info`
2. `Update`
3. `Configuration`

The layout follows the compact desktop proportions of the reference application while allowing
the configuration controls and log to resize. There is no hidden fourth tab.

## Info Workflow

The Info tab provides `Refresh` and `Clear` actions and a read-only, timestamped output area.
`Refresh` resolves one eligible ADB device, then reads:

```text
/etc/aerora-version
/etc/gimbal-version
```

The corresponding commands are equivalent to:

```text
adb -s <serial> shell cat /etc/aerora-version
adb -s <serial> shell cat /etc/gimbal-version
```

The UI labels results as `Camera Version` and `Gimbal Version`. A failure reading one file is shown
under that item but does not suppress the other read. `Clear` removes current output only and does
not contact the device.

## Update Workflow

### Package validation

Selecting a directory immediately validates these artifacts:

| Artifact | Requirement | Use |
| --- | --- | --- |
| `qti-ubuntu-robotics-image-qrb5165-rb5-boot.img` | Required | Flash `boot` to all slots |
| `qti-ubuntu-robotics-image-qrb5165-rb5-sysfs.ext4` | Required | Flash `system` to all slots |
| `abl.elf` | Optional | Flash `abl_a` and `abl_b` |

The UI shows each artifact's status. Missing boot or system images make the package invalid and
disable `Update`. A missing ABL is shown as `Optional — skipped` and does not invalidate the
package. Validation is repeated immediately before flashing so a moved or deleted artifact cannot
leave a stale valid state.

### Enter update mode

`Enter Update Mode` first checks for exactly one Fastboot device. If present, the workflow selects
that serial and enables the valid update actions without rebooting it again.

If there is no Fastboot device, it resolves exactly one eligible ADB device and runs:

```text
adb -s <serial> root
adb -s <serial> wait-for-device
adb -s <serial> reboot bootloader
```

The application then polls `fastboot devices` for a bounded period. It succeeds only when the
expected serial is the sole eligible Fastboot target. Root, wait, reboot, or detection failure
stops the transition and restores the controls.

### Flash plan

`Update` requires a valid package and one selected Fastboot serial. It disables package selection,
mode entry, update, and reboot controls while flashing.

When `abl.elf` exists, the plan is:

```text
fastboot -s <serial> flash abl_a <directory>/abl.elf
fastboot -s <serial> flash abl_b <directory>/abl.elf
fastboot -s <serial> --slot all flash boot <directory>/qti-ubuntu-robotics-image-qrb5165-rb5-boot.img
fastboot -s <serial> --slot all flash system <directory>/qti-ubuntu-robotics-image-qrb5165-rb5-sysfs.ext4
```

When `abl.elf` is absent, the first two steps are omitted and the log explicitly records that ABL
was skipped. Every included step is required: a nonzero exit status stops the plan, identifies the
failed partition, and does not report overall success.

After every step succeeds, the UI displays a full-update success message and enables `Reboot`.
`Reboot` executes:

```text
fastboot -s <serial> reboot
```

It then clears the selected Fastboot device and disables update/reboot until update mode is
confirmed again.

Stdout and stderr from Fastboot are streamed into a timestamped log without losing partial final
lines.

## Configuration Workflow

### Settings UI

The Configuration tab contains five rows. Each row has an `Apply` checkbox and its editor:

| Setting | Editor | Persistent property | Runtime default |
| --- | --- | --- | --- |
| Ethernet Range | `192.168.144.x` or `192.168.199.x` | `persist.eth0.ip.range` | `199` |
| Preview Resolution | `1920x1080 @ 30 fps` or `1280x720 @ 30 fps` | `persist.video.preview.mode` | `1280x720@30` |
| Preview Bitrate | Positive decimal Mbps input | `persist.video.preview.bitrate` | `2000000` bps |
| Encoder | `H.264` or `H.265` | `persist.video.preview.encoder` | `h264` |
| Transform | `0° (Normal)` or `180° (Flip)` | `[streaming-output]` in `/etc/xdg/weston/weston.ini` | `normal` (0°) |

Editing a row automatically checks it, and the operator may manually include or exclude it. A
`Refresh` resolves one ADB device, reads four properties with `getprop` plus the Weston transform,
populates known values, and clears the apply checkboxes. When a successful read returns an empty
value, the UI shows and selects the corresponding device runtime default from the table. A failed
read remains `Unknown`, so transport and permission errors are not mistaken for unset settings.
Transform is read from the Weston streaming-output section. Applying transform directly replaces
or adds only that section's `transform=normal` or `transform=180` entry; it does not run `adb root`
and does not modify the other Weston output sections.

Selecting H.265 shows this warning near the encoder control: `UVC preview is unavailable when
H.265 is configured. Use H.264 when UVC preview is required.`

### Validation and conversion

`Apply Selected` requires at least one checked row. Every checked row is validated before any
command starts, so invalid input cannot cause a partially applied batch.

Preview bitrate is entered in Mbps and converted to an integer bps property value using exact
decimal arithmetic:

```text
2.5 Mbps -> 2500000
10 Mbps  -> 10000000
```

The value must be numeric, finite, greater than zero, and convertible to a whole number of bits per
second. Whitespace around input is ignored. The UI does not impose an undocumented camera-specific
maximum.

### Apply and reboot

Selected properties are written in stable UI order. A batch containing all settings is equivalent
to:

```text
adb -s <serial> shell setprop persist.eth0.ip.range 144
adb -s <serial> shell setprop persist.video.preview.mode 1920x1080@30
adb -s <serial> shell setprop persist.video.preview.bitrate 10000000
adb -s <serial> shell setprop persist.video.preview.encoder h264
adb -s <serial> shell <safe weston.ini streaming-output transform update>
adb -s <serial> shell sync
```

Only selected settings generate `setprop` commands. `sync` runs exactly once, after all selected
properties succeed. If any write fails, the runner stops, does not execute remaining writes or
`sync`, and reports that the batch was not completed. Because prior successful `setprop` calls may
already have changed persistent state, the log names every completed and failed setting and tells
the operator to use `Refresh` before retrying.

After the complete batch succeeds, the apply checkboxes are cleared, the UI states that settings
take effect after reboot, and `Reboot Device` is enabled. It does not reboot automatically. The
button runs:

```text
adb -s <serial> reboot
```

Changing another value after a successful apply leaves the reboot action available but clearly
marks the new selection as not yet applied.

## Logging and UI State

Each tab owns a read-only log so information from one workflow does not hide another. User-facing
messages include timestamps; raw command output is preserved beneath the related step. Logs do not
include an unnecessary host shell command line, but they identify the operation, target serial,
artifact or property, result, and recovery hint.

Success is based on process exit status and required postconditions, never on the presence of a
word such as `OKAY` in output. Buttons are re-enabled consistently after success, failure, or
timeout. A stopped or failed workflow never advances to the next destructive command.

## Testing

Automated tests run without physical hardware and cover:

- Exact Info command arguments and independent handling of the two reads.
- Update package validation with both required files, each missing required file, optional ABL
  present, and optional ABL absent.
- Exact flash order and serial targeting with and without ABL.
- Configuration property mapping, stable ordering, selected subsets, and one trailing `sync`.
- Mbps conversion for integer and fractional values, plus empty, nonnumeric, zero, negative,
  non-finite, and sub-bps values.
- Device-list parsing for zero, one, multiple, unauthorized, and offline devices.
- Command runner success, nonzero exit, timeout, stop-on-error, and stdout/stderr forwarding.
- Offscreen PySide6 smoke tests for the three visible tabs, package-dependent button states,
  automatic configuration checkbox selection, validation errors, H.265 warning, and successful
  apply/reboot states.

The test suite uses fake process results and temporary update directories. It never invokes a real
ADB or Fastboot operation.

## Packaging and Documentation

Runtime dependencies include PySide6. Test-only dependencies are kept separate from the packaged
application. A GitHub Actions Windows workflow runs the automated tests before invoking PyInstaller
to build a versioned, single-file, windowed executable named for the D64TR factory tool.

The repository README documents supported hosts, Python startup, required `adb` and `fastboot`
executables, update package layout, all three workflows, Windows packaging, and common device
connection failures.

# D64TR Factory Tool

Desktop factory utility for one D64TR camera connected over ADB or Fastboot. The PySide6
application provides three workflows:

- **Info** reads camera and gimbal versions.
- **Update** validates and flashes a D64TR image package.
- **Configuration** reads and updates persistent Ethernet and preview-stream settings.

The UI and all device operations are asynchronous, so long Fastboot transfers do not freeze the
window. Destructive operations stop on their first failed command.

## Requirements

- Python 3.11
- `adb` and `fastboot` available in `PATH`
- One connected D64TR device
- A GUI-capable Windows, Linux, or macOS host

Install the runtime dependencies:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows, activate the environment with `.venv\Scripts\activate`.

## Run from Source

```bash
python main.py
```

The tool refuses an operation when no eligible device is available or when multiple eligible
devices are connected. Every command is explicitly targeted at the one detected serial number.

## Info

Click **Refresh** to read:

- Camera Version: `/etc/aerora-version`
- Gimbal Version: `/etc/gimbal-version`

Failure to read one version does not prevent the other read. **Clear** removes the local log.

## Update

Select an update directory containing:

| File | Requirement | Target |
| --- | --- | --- |
| `qti-ubuntu-robotics-image-qrb5165-rb5-boot.img` | Required | `boot`, all slots |
| `qti-ubuntu-robotics-image-qrb5165-rb5-sysfs.ext4` | Required | `system`, all slots |
| `abl.elf` | Optional | `abl_a` and `abl_b` |

The Update button stays disabled until both required images are present and one Fastboot device
has been selected.

1. Click **Enter Update Mode**. The tool uses an existing Fastboot target when available;
   otherwise it runs ADB root/wait/reboot and waits for the same serial in Fastboot.
2. Click **Update**. If `abl.elf` is absent, the log records that ABL was skipped and continues
   with boot and system.
3. Wait for **FULL UPDATE SUCCESS**. Do not disconnect power during the system transfer.
4. Click **Reboot**.

Every included flash is required. A failed ABL, boot, or system command stops the remaining plan
and does not enable Reboot.

## Configuration

The page reads current values when first displayed or when **Refresh** is clicked. Select any
combination of rows and click **Apply Selected**:

- Ethernet Range: `192.168.144.x` or `192.168.199.x`
- Preview Resolution: `1920×1080 @ 30 fps` or `1280×720 @ 30 fps`
- Preview Bitrate: any positive Mbps value that converts to a whole number of bps, such as `2.5`
- Encoder: H.264 or H.265

Editing a row automatically checks its Apply box. Only checked rows are written. The tool validates
the whole selection first, executes the corresponding `setprop` commands, and runs `sync` once.
After a successful batch, click **Reboot Device** to activate the new settings.

> H.265 limitation: UVC preview is unavailable when H.265 is configured. Use H.264 when UVC
> preview is required.

The persistent properties follow the
[OpenMAVCam Configuration documentation](https://openmavcam.github.io/docs/api-reference/configuration-interfaces).

## Test

Install development dependencies and run the hardware-independent suite:

```bash
python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen python -m pytest -q
```

Tests use fake process results and temporary image directories. They never call real ADB or
Fastboot tools.

## Build a Single-file Executable

```bash
python -m PyInstaller --clean --onefile --windowed --name d64tr-factory-tool main.py
```

The executable is written under `dist/`. GitHub Actions runs the tests and produces a versioned
Windows executable for pushes, pull requests, tags, and manual workflow runs.

## Troubleshooting

- **ADB unauthorized:** accept the authorization prompt on the target, reconnect it, then retry.
- **ADB offline:** reconnect USB, restart ADB if necessary, and wait for `adb devices` to report
  `device`.
- **Multiple devices:** disconnect every device except the intended D64TR. The first release does
  not offer a device selector.
- **ADB/Fastboot not found:** install Android platform tools and ensure both executables are in
  `PATH` before starting the app.
- **Update disabled:** select a directory containing both exact required filenames and enter
  Fastboot mode.
- **Flash failed:** do not reboot into an incomplete image. Review the failed partition in the log,
  correct the package or connection, re-enter Fastboot, and restart the complete update.
- **Configuration batch failed:** some earlier properties might already have been written. Click
  Refresh before selecting values and retrying.

## Hardware Acceptance Checklist

Run this manually only with an authorized D64TR and an approved firmware package:

1. Connect exactly one D64TR and confirm Info reports both versions.
2. Refresh Configuration, apply a safe multi-setting selection, reboot, and confirm the values.
3. Enter Fastboot and validate a package without `abl.elf`; confirm the UI marks ABL as skipped.
4. Validate an approved release package with `abl.elf`; confirm ABL is included.
5. Flash the approved package, reboot, and confirm the expected camera and gimbal versions.

# D64TR Black Aperture Icon Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current camera-body application icon with a black simplified aperture-and-lens icon visually related to the SAMO Factory Tool.

**Architecture:** Generate one high-resolution raster master from the approved visual brief and the SAMO icon reference, validate it before touching project assets, then downscale it to the existing PNG path and derive a seven-frame Windows ICO. The application, tests, README, and packaging workflow continue consuming the same filenames, so no source-code or build-config change is needed.

**Tech Stack:** Built-in image generation, ImageMagick `convert`/`identify`, PySide6, pytest

**Spec:** `docs/superpowers/specs/2026-11-09-d64tr-black-aperture-icon-design.md`

## Global Constraints

- Use a rounded-square silhouette, five or six broad aperture blades, and one small central lens.
- Use black, graphite, gunmetal, subtle silver highlights, and only restrained dark-blue glass reflection.
- Include no camera body, dual-camera layout, gear, text, letters, branding, bright neon palette, or fine decoration.
- Preserve `d64tr_factory_tool/assets/d64tr-icon.png` as a transparent 256×256 PNG.
- Preserve `d64tr_factory_tool/assets/d64tr-icon.ico` with 16, 24, 32, 48, 64, 128, and 256 pixel frames.
- Do not modify application icon-loading or packaging logic.

## Review Focus

- Transparent outer corners: the PNG corner pixels must have zero alpha.
- Exact project size: the final PNG must be 256×256, not the generator's master size.
- Windows scaling: the ICO must contain exactly the seven required frame dimensions.
- Tiny-size legibility: aperture blades and the central lens must remain distinguishable at 32×32.
- Runtime loading: `MainWindow.windowIcon()` must remain non-null after the assets are replaced.

---

### Task 1: Generate and install the black aperture icon

**Files:**
- Modify: `d64tr_factory_tool/assets/d64tr-icon.png`
- Modify: `d64tr_factory_tool/assets/d64tr-icon.ico`
- Test: `tests/test_main_window.py`

**Interfaces:**
- Consumes: the approved design spec and `/tmp/samo-factory-tool-reference-20261109/assets/app-icon.png` as a style/composition reference only.
- Produces: the two existing icon asset paths with unchanged consumers and file roles.

- [ ] **Step 1: Generate a high-resolution draft without replacing project assets**

Use the built-in image generation tool with the SAMO PNG as a reference image. Request a `logo-brand` desktop icon: black rounded-square base, five or six broad graphite aperture blades, a small central dark lens, restrained dark-blue reflection, subtle silver rim highlights, transparent outside corners, and no camera body, gear, text, letters, branding, or fine details.

- [ ] **Step 2: Inspect the master against the approved brief**

Open the generated master and reject it unless it has one centered aperture, one small lens, a predominantly black/graphite palette, a clean silhouette, and none of the forbidden elements. Iterate with one targeted prompt change if a required visual invariant fails.

- [ ] **Step 3: Create temporary 256×256 and 32×32 previews**

Run ImageMagick with Lanczos filtering to create `/tmp/d64tr-black-aperture-256.png` and `/tmp/d64tr-black-aperture-32.png` from the accepted master. Open both previews and verify that the 32×32 version still shows distinct aperture blades and a central lens.

- [ ] **Step 4: Verify temporary PNG dimensions and transparency**

Run:

```bash
identify /tmp/d64tr-black-aperture-256.png /tmp/d64tr-black-aperture-32.png
identify -format '%[pixel:p{0,0}]\n' /tmp/d64tr-black-aperture-256.png
```

Expected: dimensions are `256x256` and `32x32`; the first corner pixel has zero alpha.

- [ ] **Step 5: Replace the project PNG and regenerate the multi-size ICO**

Copy the accepted 256×256 preview to `d64tr_factory_tool/assets/d64tr-icon.png`, then use ImageMagick `-define icon:auto-resize=256,128,64,48,32,24,16` to overwrite `d64tr_factory_tool/assets/d64tr-icon.ico` from that PNG.

- [ ] **Step 6: Verify final asset formats and ICO frames**

Run:

```bash
identify d64tr_factory_tool/assets/d64tr-icon.png
identify d64tr_factory_tool/assets/d64tr-icon.ico
```

Expected: the PNG is 256×256 with alpha; the ICO lists exactly 256, 128, 64, 48, 32, 24, and 16 pixel frames.

- [ ] **Step 7: Run the icon regression test and full suite**

Run:

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_main_window.py::test_main_window_uses_application_icon
QT_QPA_PLATFORM=offscreen python3 -m pytest -q
```

Expected: the targeted icon test passes and the full suite reports no failures.

- [ ] **Step 8: Review and commit the two asset replacements**

Run `git diff --check`, inspect `git status --short`, and confirm no files beyond the two icon assets changed. Commit with:

```bash
git add d64tr_factory_tool/assets/d64tr-icon.png d64tr_factory_tool/assets/d64tr-icon.ico
git commit -m "feat: redesign application icon in black"
```

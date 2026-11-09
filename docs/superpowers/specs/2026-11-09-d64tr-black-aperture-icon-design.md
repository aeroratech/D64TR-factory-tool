# D64TR Black Aperture Icon Design

## Intent

Redesign the D64TR Factory Tool application icon so it visually belongs with
the SAMO Factory Tool icon while remaining simpler and using a black color
system. The result should read as camera-related at small desktop-icon sizes
without depicting a complete camera body or detailed lens assembly.

## Goals

- Use a rounded-square application-icon silhouette like the SAMO reference.
- Center one simplified circular aperture made from five or six broad blades.
- Keep a small central lens element with restrained dark-blue glass reflection.
- Use black, graphite, gunmetal, and subtle silver edge highlights.
- Remain recognizable from 16×16 through 256×256 pixels.
- Replace the existing PNG and regenerate the multi-size Windows ICO.

## Non-goals

- No camera body, dual-camera layout, gear, text, letters, or product branding.
- No realistic multi-element lens, bright neon palette, or fine decoration.
- No changes to the application's icon-loading or packaging logic.

## Approaches

1. **Selected — simplified aperture and small lens:** closest to the SAMO icon's
   composition while removing the previous camera-body complexity.
2. **Concentric lens rings:** clearest at tiny sizes, but less visually related
   to the SAMO tool.
3. **Aperture outline only:** most minimal, but too generic and less clearly a
   camera-related tool.

## Deliverables and Validation

- `d64tr_factory_tool/assets/d64tr-icon.png`: transparent 256×256 PNG.
- `d64tr_factory_tool/assets/d64tr-icon.ico`: the same design at 16, 24, 32,
  48, 64, 128, and 256 pixels.
- Inspect the 256×256 result and verify dimensions, alpha, ICO frame sizes,
  existing icon tests, and the full test suite.

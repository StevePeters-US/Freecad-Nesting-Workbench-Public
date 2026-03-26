# Skill: Icon Design Guidelines

> Read this before creating or modifying toolbar icons.

## Location

All icons live in `Resources/icons/` relative to the project root.

## Current Icons

| File | Format | Used by |
|------|--------|---------|
| `Nesting_Workbench.svg` | SVG | Workbench icon in FreeCAD toolbar |
| `Nest_Icon.png` | PNG | Run Nesting command |
| `CNC_Icon.png` | PNG | Create CAM Job command |
| `DXF_Icon.png` | PNG | Export Sheets command |
| `Stack_Icon.png` | PNG | Stack/Unstack Sheets command |
| `Silhouette_Icon.svg` | SVG | Create Silhouette command |
| `Nesting_Transform.svg` | SVG | Manual Nester command |
| `Transform_Icon.png` | PNG | Manual Nester (alternate) |

## New Icon Format (SVG preferred)

For new icons, use SVG with these specifications:

```xml
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="64" height="64" viewBox="0 0 64 64">
  <!-- icon content -->
</svg>
```

### Colors

| Role | Color | Usage |
|------|-------|-------|
| Main fill | `#e0e0e0` (light gray) | Primary shape fill |
| Secondary | `#ffffff` or `none` | Highlights or transparent |
| Stroke | `#000000` | Outlines, `stroke-width: 2` |
| Accent | `#4a90d9` (blue) | Nesting-specific elements |
| Warning/optional | `#ffaa00` (orange) | Optional features, GPU |

### Rules

- Use **inline styles** only — no external stylesheets
- Canvas is 64x64 pixels
- Keep shapes simple and recognizable at 16x16 (FreeCAD toolbar size)
- Use `stroke-width: 2` for outlines
- Test visibility at both 64px and 16px scales
- Save source `.xcf` (GIMP) files alongside PNGs when applicable

### Template — General Tool

```xml
<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="64" height="64" viewBox="0 0 64 64">
  <rect x="8" y="8" width="48" height="48" rx="4"
        style="fill:#e0e0e0; stroke:#000000; stroke-width:2"/>
  <!-- Add tool-specific elements here -->
</svg>
```

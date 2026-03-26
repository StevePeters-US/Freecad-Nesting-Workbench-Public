---
name: NW Icon Design Guidelines
description: Guidelines for creating custom SVG icons for the Nesting Workbench (NW).
---

# NW Icon Design Guidelines

> Read this before creating or modifying toolbar icons.

When creating custom SVG icons for the Nesting Workbench in FreeCAD, adhere to the following strict styling rules to ensure consistency across the UI.

## File Format & Dimensions

- **Format**: SVG (`<svg xmlns="http://www.w3.org/2000/svg" ...>`)
- **Dimensions**: Viewport size strictly `width="64" height="64"`.
- **Version**: `version="1.1"`

## Styling & Colors

All styling must be applied using inline SVG `style` attributes. Avoid classes or external stylesheets.

### Base Colors
- **Main Shape Fill**: Light gray `#e0e0e0`
- **Secondary / Highlight Shape Fill**: White `#ffffff` or `none` depending on context.
- **Default Stroke**: Black `#000000` with `stroke-width:2`

### Nesting Workbench Specific Colors
For tools related to nesting, packing, and boundaries:
- **Primary Accent (Teal Green)**: `#00a86b` (Teal Green). Used to indicate primary shapes, parts being nested, or active tool elements. Apply to `fill` or `stroke` with `stroke-width:2`.
- **Secondary Accent (Purple)**: `#9b5de5` (Purple). Used to denote sheets, boundaries, or container areas. Apply to `stroke` with `stroke-width:2` or `stroke-dasharray:4,4` for dashed guides.

## Example Templates

### General Tool Icon (e.g., General Part)
```xml
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" version="1.1">
    <rect width="50" height="50" x="7" y="7" style="fill:#ffffff;stroke:#000000;stroke-width:2"/>
    <rect width="40" height="40" x="12" y="12" style="fill:#e0e0e0;stroke:#000000;stroke-width:1"/>
</svg>
```

### Nesting Operation Icon (e.g., Nest Parts on Sheet)
```xml
<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" version="1.1">
    <!-- Boundary / Sheet -->
    <rect width="56" height="56" x="4" y="4" style="fill:none;stroke:#9b5de5;stroke-width:2;stroke-dasharray:4,4"/>
    <!-- Nested Parts -->
    <rect width="20" height="20" x="10" y="10" style="fill:#00a86b;stroke:#000000;stroke-width:2"/>
    <path d="M 36 16 A 12 12 0 1 0 36 40 A 12 12 0 0 1 36 16 Z" style="fill:#00a86b;stroke:#000000;stroke-width:2"/>
</svg>
```

## Directory
All custom NW icons should be saved to `Resources/icons/` relative to the project root. Keep shapes simple and recognizable at 16x16 (FreeCAD toolbar size).

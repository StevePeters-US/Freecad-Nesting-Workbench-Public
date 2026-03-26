---
name: NW Icon Design Guidelines
description: Guidelines for creating custom icons for the Nesting Workbench (NW).
---

# NW Icon Design Guidelines

> Read this before creating or modifying toolbar icons.

When creating custom icons for the Nesting Workbench in FreeCAD, adhere to the following styling rules to ensure consistency across the UI. We embrace a quirky, literal, and illustrative style using real-world objects and visual metaphors rather than abstract geometry.

## File Format & Dimensions

- **Format**: PNG (`.png`) - Raster graphics with transparency.
- **Background**: Must be **transparent**.
- **Dimensions**: Square viewport, designed to scale nicely to 64x64 or 32x32.

## Styling & Colors

Our icons heavily feature **Teal Greens** (e.g., `#00a86b`) and **Purples** (e.g., `#9b5de5`), but retain the detailed, pixel-art/illustrative vibe of the original icons. Avoid flat, overly minimalist SVG outlines unless requested.

## Existing Icon Metaphors

Our existing styles convey the tool's meaning through highly recognizable, somewhat playful metaphors:

- **Run Nesting (`Nest_Icon.png`)**: A literal **bird's nest with eggs**. The nest represents the concept of "nesting" parts together securely.
- **Create CAM Job (`CNC_Icon.png`)**: A **drill bit / endmill digging into a material block**. Represents the CNC milling process that results from the layout.
- **Export Sheets (`DXF_Icon.png`)**: A **traditional printer outputting a document**. Represents exporting 2D DXF files for laser cutters or routers.
- **Stack/Unstack Sheets (`Stack_Icon.png`)**: A **stack of pancakes with syrup and butter**. A playful take on the concept of "stacking" multiple 2D sheets on top of each other.
- **Manual Nester (`Transform_Icon.png`)**: A **cartoon gloved hand**. Represents manually grabbing, moving, and interacting with placed parts.

## Directory
All custom NW icons should be saved to `Resources/icons/` relative to the project root in `.png` format.

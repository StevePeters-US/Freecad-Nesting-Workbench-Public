# FreeCAD Nesting Workbench

A workbench for 2D nesting of shapes in FreeCAD, utilizing the Minkowski Sum algorithm for efficient packing.

## Installation

There are three ways to install the Nesting Workbench. Choose the one that best suits your needs.

### Path A: Automated Installation (Recommended)

This is the easiest method. It uses a FreeCAD macro to download and install the workbench automatically.

1.  **Download the Macro:** Download [InstallNestingWorkbench.FCMacro](InstallNestingWorkbench.FCMacro) from this repository.
2.  **Run in FreeCAD:**
    *   Open FreeCAD.
    *   Go to **Macro -> Macros...**
    *   Click **Open** and select the `InstallNestingWorkbench.FCMacro` file.
    *   Click **Execute**.
3.  **Follow Prompts:** The macro will ask you which branch to install (default is `main`). Click **Install**.
4.  **Restart FreeCAD:** Once finished, restart FreeCAD to see the **Nesting** workbench in the workbench selector.

---

### Path B: Manual Installation (GitHub Download)

If you prefer to install manually, follow these steps:

1.  **Download the ZIP:** Click the green **Code** button on GitHub and select **Download ZIP**.
2.  **Locate your Mod Directory:**
    *   **Windows:** `%APPDATA%\FreeCAD\Mod` (usually `C:\Users\<User>\AppData\Roaming\FreeCAD\Mod`)
    *   **Linux:** `~/.local/share/FreeCAD/Mod`
    *   **macOS:** `~/Library/Application Support/FreeCAD/Mod`
3.  **Extract:** Unzip the downloaded file into the `Mod` directory.
4.  **Rename:** Rename the extracted folder (e.g., `Freecad-Nesting-Workbench-main`) to exactly `Freecad-Nesting-Workbench`.
5.  **Restart FreeCAD.**

---

### Path C: Advanced Installation (Developer / Symlink)

For developers or users who want to keep the repository in a custom location and stay updated via `git`:

1.  **Clone the Repo:**
    ```bash
    git clone https://github.com/StevePeters-US/Freecad-Nesting-Workbench.git /path/to/your/dev/folder
    ```
2.  **Create a Symlink:**
    Create a symbolic link (or junction on Windows) from your FreeCAD `Mod` directory to the cloned folder.

    *   **Windows (PowerShell):**
        ```powershell
        New-Item -ItemType Junction -Path "$env:APPDATA\FreeCAD\Mod\Freecad-Nesting-Workbench" -Target "C:\path\to\your\dev\folder"
        ```
    *   **Linux / macOS:**
        ```bash
        ln -s /path/to/your/dev/folder ~/.local/share/FreeCAD/Mod/Freecad-Nesting-Workbench
        ```
3.  **Restart FreeCAD.**

---


## Usage Guide

### 1. Preparing Parts
Select the 3D parts or 2D shapes you wish to nest from the Tree View or 3D View.

### 2. Running the Nester
Click the **Run Nesting** icon (or access via the Nesting menu). This opens the Nesting Task Panel.

### 3. Configuring Options

#### Sheet Settings
*   **Sheet Width/Height:** Dimensions of the material sheet.
*   **Sheet Thickness:** Thickness of the material (used for 3D visualization and CAM).
*   **Part Spacing:** Minimum distance between nested parts.

#### Bounds Resolution (Advanced)
*   **Curve Angle (Quality):** Controls how smooth curved edges are approximated. Lower angles (5-10°) give smoother curves but are slower. Higher angles (30°+) are faster but coarser.
*   **Simplification:** Tolerance for reducing determining points on a polygon. Higher values (1.0mm+) speed up nesting by removing tiny details.

#### Minkowski Nester Settings
*   **Packing Direction:** Choose the primary direction to gravity-pack parts (Down, Left, Up, Right).
*   **Use Random Strategy:** If checked, randomizes placement heuristics for potentially better (or worse) results.
*   **Clear NFP Cache:** Forces recalculation of No-Fit Polygons. Useful if you suspect caching issues, but slower.
*   **Generations / Population Size:** Settings for the Genetic Algorithm optimizer. Increase these for complex nests to find better solutions over time (default is 1 for a single pass).

#### Part Options (In the Table)
*   **Quantity:** How many copies of this part to nest.
*   **Rotations:** Global setting for rotation steps (e.g., 4 steps = 0°, 90°, 180°, 270°).
*   **Override:** Check this to set specific rotation behavior for individual parts.
*   **Up Dir:** Define which axis is "Up" (Z+, Y+, etc.) for projecting the 3D part to 2D.
*   **Fill:** Mark a part as "filler" to be placed in gaps after main parts are nested.

### 4. Generating the Layout
Click **Run Nesting** at the bottom of the panel.
*   The tool will process the shapes and generate a `Layout` group in the tree.
*   This group contains `Sheet` objects with the nested parts.

## Other Tools

*   **Stack Sheets:** Stacks the sheets at origin.
*   **Export Sheets:** Export the nested sheets to DXF or SVG files.
*   **Create CAM Job:** Generates a Path/CAM job from the nested layout, organizing parts, labels, and outlines for machining.
*   **Create Silhouette:** Generates a 2D projection (outline) of a 3D part which can be used in a cam job.
*   **Transform Parts:** (Experimental) A manual tool to move/rotate nested parts. **NOTE: This tool is currently under construction and may not function correctly.**

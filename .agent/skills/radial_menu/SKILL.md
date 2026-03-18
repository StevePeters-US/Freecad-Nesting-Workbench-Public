---
name: radial_menu
description: Technical guide on how FreeCAD's PieMenu add-on replaces native UI elements.
---

# Radial Menu Implementation (PieMenu)

This skill documents how the FreeCAD *PieMenu* add-on replaces native UI elements with a radial interface.

## Core Mechanisms

### 1. Command Registration (Shadowing)
- **Action**: Defines Python classes for FreeCAD commands (implementing `GetResources`, `Activated`, etc.).
- **Mechanism**: Registered via `FreeCADGui.addCommand`.
- **Result**: If a command name matches an existing one, it **shadows** the original. Subsequent calls to that name invoke the PieMenu version.

### 2. UI Clearing
- **Action**: Retrieves the main window via `FreeCADGui.getMainWindow()`.
- **Mechanism**: Iterates over `QToolBar` objects and calls `clear()`.
- **Result**: Removes all default actions/buttons from the toolbars.

### 3. Injecting Triggers
- **Action**: Creates `QAction` objects connected to a `showPieMenu` slot.
- **Mechanism**: Added to the main window's toolbar via `addToolBar`.
- **Result**: The pie-menu buttons become the primary UI entry points.

### 4. Qt Event Filtering
- **Action**: Subclasses `QtCore.QObject` with an `eventFilter`.
- **Mechanism**: Intercepts `QEvent.ContextMenu` events.
- **Result**: Stops the default right-click menu and launches the custom radial menu instead.

### 5. Dynamic Pie Construction
- **Action**: Calls `FreeCADGui.listCommands()` on trigger.
- **Mechanism**: Filters commands by current workbench/selection.
- **Result**: Dynamically populated radial menus based on context.

### 6. Persistence
- **Action**: User preferences are saved to `~/.FreeCAD/PieMenu.cfg`.
- **Mechanism**: Read on startup to re-apply the UI override.

## Best Practices
- Use command shadowing to preserve standard shortcut integration.
- Ensure the `eventFilter` returns `True` after handling `ContextMenu` events to prevent event propagation.
- Filter commands carefully to avoid cluttering the radial menu with irrelevant actions.

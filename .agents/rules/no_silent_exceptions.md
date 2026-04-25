# Rule: No Silent Exceptions

## Mandate

Every `except` block **must** log the exception. No bare `except:` or `except Exception: pass`.

## Required Pattern

```python
# Correct — specific type, logged with context
try:
    result = compute_nfp(part_a, part_b)
except (ValueError, GeometryError) as e:
    FreeCAD.Console.PrintError(f"[MinkowskiEngine] NFP failed for '{part_a.label}': {e}\n")
    return None

# Correct — broad catch when unavoidable, with traceback
try:
    shape = prepare_master(obj)
except Exception as e:
    import traceback
    FreeCAD.Console.PrintError(f"[ShapePreparer] Failed: {e}\n{traceback.format_exc()}\n")
    return None
```

## Prohibited Patterns

```python
# NEVER — bare except catches SystemExit and KeyboardInterrupt
except:
    pass

# NEVER — swallows the error silently
except Exception:
    pass

# NEVER — catches too broadly with no context
except Exception as e:
    print(e)
```

## Logging Target

Use `FreeCAD.Console.Print*` with module name in brackets and `\n` terminator:
- `PrintError` for failures
- `PrintWarning` for non-fatal issues
- `PrintLog` for debug-level exceptions in hot paths

See the `logging` skill for full guidelines.

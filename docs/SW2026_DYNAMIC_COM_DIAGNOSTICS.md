# SOLIDWORKS 2026 Dynamic COM Diagnostic Rule

## Problem

SOLIDWORKS 2026 can expose zero-argument COM methods through pywin32 dynamic dispatch as already-evaluated property values. Direct Python calls such as:

```python
doc.GetFeatureCount()
segment.GetStartPoint2()
segment.GetEndPoint2()
```

can therefore fail even though the underlying SOLIDWORKS object is valid. Typical symptoms are:

- `TypeError: 'int' object is not callable`
- `DISP_E_MEMBERNOTFOUND`

These failures are diagnostic-call artifacts and must not be interpreted as stale COM objects or failed CAD geometry without further evidence.

## Mandatory rule

For dynamic SOLIDWORKS COM objects, read zero-argument members through `com_get` unless a typed makepy interface is deliberately being used:

```python
feature_count = com_get(doc, "GetFeatureCount", default=None)
start = com_get(segment, "GetStartPoint2", default=None)
end = com_get(segment, "GetEndPoint2", default=None)
```

For members requiring arguments, `com_get` is also preferred because it normalizes property-vs-method dispatch and can re-flag dynamic members as methods when required.

## Existing-dimension updates

Parametric edits of an existing model should use `DimensionUpdateOperations.set_dimension_value` rather than creating a replacement dimension. The operation:

- resolves the existing stored dimension by exact name,
- verifies that it is a driving dimension,
- writes only its existing `SystemValue`,
- performs one rebuild,
- reacquires the same dimension by name,
- verifies the post-rebuild value and driving state,
- checks the feature count through `com_get(doc, "GetFeatureCount", ...)`,
- rolls the old value back if the write/rebuild/readback sequence fails.

This operation must not create or delete sketches, dimensions, features, or bodies.

## Test C implication

When repeating the 120 mm -> 130 mm width test, diagnostic baselines and post-checks must not directly invoke zero-argument dynamic members. In particular, do not use `doc.GetFeatureCount()` in custom Python diagnostics. Use `com_get` or the new `set_dimension_value` operation.

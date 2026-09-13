# SW2026 cut direction semantics

## Why this note exists

A live D2 acceptance test on SOLIDWORKS 2026 SP0.0 exposed a direction-assumption bug in the caller, not in `semantic_cut` or body identity resolution.

The tested sketch was created on the top face of a body at Y=20 mm. The verified sketch normal pointed in +Y while the material occupied Y=0..20 mm. A 15 mm blind cut therefore had to travel toward -Y.

The failed call used:

```text
direction_flip=true
```

SOLIDWORKS rejected the feature (`FeatureCut4` returned no feature, legacy `swFeatureError` 103). The otherwise identical call with:

```text
direction_flip=false
```

succeeded and produced the expected pocket from Y=20 to Y=5 mm.

## API rule

For SOLIDWORKS extruded cuts, the default Direction 1 is **opposite the sketch normal**. Setting the `Dir`/`direction_flip` argument to true reverses that default.

Therefore:

```text
direction_flip=false -> cut opposite sketch normal
direction_flip=true  -> cut along sketch normal
```

This differs from a boss extrude, whose default direction is along the sketch normal.

## Deterministic decision rule

For a blind cut from a face sketch:

1. Determine the verified sketch normal `n`.
2. Determine which side of the sketch plane contains the scoped body's material.
3. If material lies in direction `-n`, use `direction_flip=false`.
4. If material lies in direction `+n`, use `direction_flip=true`.
5. When the intended spatial envelope is known, pass `expected_bbox` so a live-but-wrong-side feature is rolled back.
6. Use `auto_flags=true` only when bounded automatic direction search is explicitly permitted by the calling workflow.

## D2 reference case

```text
body Y-range:      0 .. 20 mm
sketch plane:      Y = 20 mm
sketch normal:     +Y
wanted pocket:     Y = 20 .. 5 mm
material direction relative to sketch normal: -n
correct direction_flip: false
```

Successful live result:

```text
feature:       F_main_pocket
feature bbox:  [-60,5,-30] .. [50,20,30] mm
body:          B_insert_main
body count:    1
final volume:  109000 mm^3
feature count: 21
```

## Error classification

A rejected `FeatureCut4` call that returns no feature without a COM exception or HRESULT is a feature-creation failure, not evidence that the COM member is missing or mismatched. The runtime therefore classifies `Cut failed on sketch ...` and `Extrude failed on sketch ...` as `FEATURE_CREATE_FAILED`. `COM_MEMBER_MISMATCH` remains the fallback for genuinely unknown COM automation failures.
# Auto-mode input safety

`auto_material_side` requires `auto_flags=false` and an unshifted
`start_condition="sketch_plane"` with zero `start_offset` and no
`start_face_ray`. Other start conditions require `explicit` mode because the
current classifier proves material side relative to the sketch plane only.
The explicit path keeps forwarding the requested direction unchanged.

The resolver rejects negative or non-finite tolerance, non-finite sketch
transforms, and malformed, inverted, or non-finite body bounding boxes before
feature creation. The wrapper also rejects a successful resolver response that
lacks a boolean direction; a missing flag must never silently mean false.

Bounding-box classification proves a material half-space only. It does not
prove that the profile intersects that material or that a requested depth/end
condition is realizable. Feature rejection must still be reported and geometry
verified after creation. Complex or oblique geometry can be conservatively
ambiguous. No ray-based fallback or trial feature is used.

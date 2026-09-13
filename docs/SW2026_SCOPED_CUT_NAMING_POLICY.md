# SW2026 scoped-cut naming policy

## Status

This document describes the **legacy compatibility fallback** for models in
which a SOLIDWORKS feature and its solid body already share the same display
name. New production models should use the semantic CAD identity layer in
`docs/SEMANTIC_CAD_IDENTITY.md` instead:

- sketches: `S_*`
- features: `F_*`
- bodies: `B_*`
- logical body references: `body:<lower_snake_case>`

Separating namespaces prevents the collision rather than repairing it after a
feature operation.

## Legacy problem

SOLIDWORKS 2026 can allow a source feature and its original body to carry the
same display name before a cut. After a topology-changing cut, however, the
resulting body is owned by the new cut feature and restoring the body's old name
can collide with the older source feature that still owns that name.

Observed live case:

- source feature before cut: `BaseExtrude20`
- body before cut: `BaseExtrude20`
- new cut feature: `PocketCut15`
- body immediately follows the new feature name
- attempting to restore the body to `BaseExtrude20` is rejected while the old
  source feature is still named `BaseExtrude20`

The upstream compatibility implementation resolves that collision by renaming
the source feature to `BaseExtrude20_SourceFeature`. This is unsafe for new
parametric production workflows because later edits commonly resolve features
by stable feature names.

## Compatibility policy

For ordinary single-ended cuts the SW2026 compatibility wrapper prioritizes
model-tree reference stability:

1. Existing source feature names are restored.
2. New cut feature names are preserved as requested when possible.
3. If the post-cut body cannot reuse its old display name because that name is
   owned by a pre-existing feature, the body receives a deterministic legacy
   alias `<old_body_name>_Body` (and `_2`, `_3`, ... when necessary).
4. The alias transition is reported explicitly as `scope_body_name_changes`.
5. If final stabilization cannot be verified, the new cut is rolled back
   instead of silently accepting an unexpected source-feature rename.

Existing double-ended `through_all_both` behavior remains unchanged for
backward compatibility until that path receives its own live migration test.
This exception is one reason the compatibility policy is not the recommended
production identity architecture.

## Production policy

`semantic_extrude` assigns the solid body a canonical `B_*` name immediately
after creation while preserving the separately named feature (`F_*`).
`semantic_cut` scopes cuts by logical body id rather than by a historical
feature-derived body name.

Example production state:

- sketch: `S_base_profile`
- source feature: `F_base_extrude`
- body identity: `body:insert_main`
- persisted body name: `B_insert_main`
- pocket sketch: `S_card_pocket`
- cut feature: `F_card_pocket`

No feature/body namespace collision exists, so the legacy alias-repair path is
not expected to run.

## Legacy result contract

On a collision-free legacy cut:

- `source_feature_names_preserved = true`
- `scope_body_name_changes = []`

On a single-ended legacy collision resolved by body aliasing:

- `source_feature_names_preserved = true`
- `scope_feature_renames = []` in the final state
- `temporary_scope_feature_renames` records the internal temporary rename
- `scope_body_name_changes` records the final body alias
- `body_name_policy = preserve_feature_name_alias_body_on_collision`

The body rename is a display-name transition, not a body deletion/recreation.

## Acceptance requirement

New production workflows should not depend on the legacy alias chain. They
should migrate a legacy body once with `register_body_identity`, then use
`semantic_extrude` / `semantic_cut` and logical `body:*` references. A semantic
cut is accepted only if every scoped logical body id resolves to its canonical
`B_*` body after the topology change.

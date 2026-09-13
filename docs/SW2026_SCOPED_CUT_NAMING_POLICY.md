# SW2026 scoped-cut naming policy

## Problem

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

The previous implementation resolved the collision by silently renaming the
source feature to `BaseExtrude20_SourceFeature`. This is unsafe for parametric
workflows because feature names are persistent references used by later edits.

## Policy

The SW2026 wrapper prioritizes model-tree reference stability:

1. Existing source feature names are immutable across `advanced_cut`.
2. New cut feature names are preserved as requested when possible.
3. If the post-cut body cannot reuse its old display name because that name is
   owned by a pre-existing feature, the body receives a deterministic alias:
   `<old_body_name>_Body`.
4. If that alias is already occupied, `_2`, `_3`, ... is appended.
5. The alias transition is reported explicitly as `scope_body_name_changes`.
6. Temporary source-feature renames made by the base SW2026 workaround are
   restored before the operation is reported as successful.
7. If final name stabilization cannot be verified, the new cut feature is
   deleted and the wrapper performs best-effort restoration instead of leaving
   a silently renamed source feature behind.

## Result contract

On a collision-free cut:

- `source_feature_names_preserved = true`
- `scope_body_name_changes = []`

On a name collision resolved by body aliasing:

- `source_feature_names_preserved = true`
- `scope_feature_renames = []` in the final state
- `temporary_scope_feature_renames` records the internal temporary rename
- `scope_body_name_changes` records the final body alias
- `body_name_policy = preserve_feature_name_alias_body_on_collision`

Example final state for the live acceptance model:

- source feature: `BaseExtrude20`
- cut feature: `PocketCut15`
- body: `BaseExtrude20_Body`

The body rename is a display-name transition, not a body deletion/recreation;
`new_bodies` and `merged_bodies` remain empty when topology is preserved.

## Acceptance requirement

A scoped cut must never be accepted if it leaves a pre-existing source feature
renamed solely to recover a body display name. Future tests should verify the
feature by its original name and use the returned final body name for subsequent
body-scoped operations.

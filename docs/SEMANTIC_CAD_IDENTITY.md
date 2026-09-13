# Semantic CAD identity architecture

## Purpose

Complex insert models must remain editable after many features, body-topology
changes, saves, closes, reopens and MCP restarts.  SOLIDWORKS display names are
useful labels, but they should not be the only identity mechanism.

The production architecture therefore separates:

1. **logical identity** — stable API reference such as `body:insert_main`;
2. **persisted canonical body name** — deterministic SOLIDWORKS name such as
   `B_insert_main`;
3. **feature/sketch names** — independent namespaces (`F_*`, `S_*`);
4. **session verification metadata** — current name plus a light-weight body
   geometry signature.

The canonical `B_*` name is deliberately persisted in the native SLDPRT and can
be re-derived from the logical id after Save/Close/Reopen or a new MCP process.

## Naming contract

For newly generated production models:

| Object | Prefix | Example |
|---|---|---|
| sketch | `S_` | `S_base_profile` |
| feature | `F_` | `F_base_extrude` |
| solid body | `B_` | `B_insert_main` |
| logical body id | `body:` | `body:insert_main` |

A logical body id must match:

```text
body:<lower_snake_case>
```

with a maximum key length of 64 characters.  The mapping is deterministic:

```text
body:insert_main -> B_insert_main
body:card_tray   -> B_card_tray
body:lid         -> B_lid
```

`semantic_extrude` rejects a feature name equal to the canonical body name.
`semantic_cut` rejects a cut feature name equal to a scoped semantic body name.

## Why canonical names are the persistence layer

The repository already records an important SW2026 limitation: broad
`GetPersistReference3` reads can block indefinitely on a dirty document after
an interrupted feature operation.  Persistent references therefore must not be
a mandatory correctness dependency for every feature/body operation.

The semantic identity layer uses:

```text
logical id
   -> deterministic B_* name persisted by SOLIDWORKS
   -> session registry
   -> unique geometry-signature recovery (same MCP session only)
```

The session signature contains body bounding box and face count.  It is a
recovery/verification mechanism, not a primary identity.  If more than one body
matches a stored signature, resolution fails as ambiguous rather than guessing.

A future targeted persistent-reference cache can be added as an optimization,
but it must remain bounded and opt-in on SW2026 dirty documents.

## Public tools

### `register_body_identity`

Migrates an existing/legacy body once:

```text
feature: BaseExtrude20
body:    BaseExtrude20
```

with:

```text
body_id = body:insert_main
```

into:

```text
feature: BaseExtrude20
body:    B_insert_main
```

The operation snapshots feature names before the body rename and verifies that
none changed.  A body rename that unexpectedly changes the feature tree fails
closed.

### `resolve_body_identity`

Resolves a logical id without mutation. Resolution order:

1. current-name entry in the session registry;
2. deterministic persisted canonical name (`B_*`);
3. unique stored geometry-signature match from the same MCP session.

Failure or ambiguity produces `REFERENCE_MISMATCH`.

### `list_body_identities`

Lists known identities and infers identities from valid persisted `B_*` body
names. This is the normal rehydration mechanism after an MCP restart.

### `semantic_extrude`

Runs the verified native `advanced_extrude`, then commits a logical identity to
the resulting body.  If the target body is ambiguous or canonical naming cannot
be verified, the created feature is deleted and the operation fails rather than
leaving partially committed identity state.

Recommended example:

```text
sketch_name  = S_base_profile
feature_name = F_base_extrude
body_id      = body:insert_main
```

Final state:

```text
S_base_profile
F_base_extrude
B_insert_main
```

### `semantic_cut`

Accepts `scope_body_ids` instead of historical body display names.  Every id is
resolved before mutation.  The existing verified `advanced_cut` performs the
SOLIDWORKS operation with the resolved body names.  After the topology change,
every logical id must still resolve to its canonical `B_*` body.  Otherwise the
new cut feature is deleted and the operation fails with an invariant error.

Recommended example:

```text
sketch_name    = S_card_pocket
feature_name   = F_card_pocket
scope_body_ids = [body:insert_main]
```

## Result contract

Semantic operations return both normal native feature diagnostics and identity
metadata. Typical `semantic_cut` additions are:

```text
scope_body_ids
resolved_scope_bodies
body_identities_before
body_identities_after
semantic_identity_verified = true
semantic_naming = {S_, F_, B_}
```

Typical `semantic_extrude` additions are:

```text
body_identity
body_identity_resolution
semantic_naming = {S_, F_, B_}
```

## Legacy compatibility

`advanced_extrude` and `advanced_cut` remain available and retain their existing
contracts.  The SW2026 cut-name wrapper remains a compatibility fallback for
legacy models where feature and body already share a name.

New production code should prefer semantic tools. This allows the migration to
happen incrementally without breaking upstream tests or existing users.

## Recommended migration for the current acceptance model

Current saved Test-C state:

```text
feature: BaseExtrude20
body:    BaseExtrude20
```

Before repeating Test D:

```text
register_body_identity(
    body_id="body:insert_main",
    body_name="BaseExtrude20",
    role="main_insert_body"
)
```

Expected state:

```text
feature: BaseExtrude20
body:    B_insert_main
```

Then Test D should use:

```text
semantic_cut(
    scope_body_ids=["body:insert_main"],
    ...,
    feature_name="F_main_pocket"
)
```

This validates the production architecture instead of the legacy name-repair
path.

## Current scope and deliberate limits

This first identity layer covers solid bodies because scoped cuts and multibody
insert workflows are the immediate production risk.  The same pattern should be
extended later to features, sketches and semantic face/edge selectors, but face
and edge identity should remain geometry/semantics-based rather than relying on
raw `Face17`/`Edge42` indices.

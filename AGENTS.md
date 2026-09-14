# AGENTS.md

This file contains repository-level instructions for AI coding agents and automated development work in `Belegur123123/SolidworksMCP`.

It applies to the whole repository unless a more specific `AGENTS.md` exists in a subdirectory.

## 1. Inspect reality before changing code

Do not assume an old prompt's commit SHA, branch topology, test count, tool count, or qualification state is current.

Before substantial work:

1. inspect the active branch, current head, open PRs, and release path;
2. read the README, tool registry/server contracts, relevant tests, acceptance reports, and current changelog/version notes;
3. query the actual capability surface when a live server is available;
4. continue from the real implementation rather than recreating already-delivered features.

Do not create synthetic changes or commits merely to show activity.

## 2. Repository role

SolidworksMCP is the generic SOLIDWORKS automation and verification layer.

It owns:

- SOLIDWORKS document/session handling;
- generic semantic CAD operations;
- transactions, checkpoints, rollback, and bounded recovery;
- native assembly/document operations;
- stable semantic identity mechanisms;
- native geometry probes and evidence;
- save/export/reopen verification;
- capability discovery and versioned MCP contracts.

It does not own:

- board-game component semantics;
- insert architecture or functional grouping;
- tray selection or global packing;
- Local-CAD design search;
- board-game-specific manufacturing decisions;
- scanner/metrology logic.

Keep board-game-specific logic in `Belegur123123/Local-CAD`.

## 3. System boundary

Target system:

```text
Boardgame-Metrology
    -> Local-CAD full-3D design
    -> PartGeometrySpec / CADPlan
    -> SolidworksMCP
    -> SOLIDWORKS 2026
    -> native SLDPRT / SLDASM + evidence
```

SOLIDWORKS is the only native CAD authoring engine. Local-CAD may perform computational geometry and full-3D planning outside SOLIDWORKS; this repository must provide the generic materialization and verification operations needed to realize the already-selected design.

Do not make SolidworksMCP depend on Local-CAD implementation modules or insert-domain schemas.

## 4. Generic-first design rule

Any new MCP operation must be justified as generally useful SOLIDWORKS automation, not as a one-off operation for a specific board game or insert.

Prefer generic primitives such as:

- arbitrary closed contour sketches;
- transformed/reference planes;
- loft/sweep/revolve/surface operations;
- body import/boolean operations;
- mesh/hybrid-BREP operations;
- component insertion/transforms;
- interference/measurement/export probes.

Avoid tools named or structured around specific games, tray types, or Local-CAD domain entities.

## 5. Semantic identities and unstable topology

Preserve stable semantic identity namespaces/contracts where available.

Do not expose transient COM object references or fragile face/edge indices as durable cross-process identities unless the operation is explicitly ephemeral and documented as such.

After boolean, import, mesh/hybrid, or other topology-changing operations, verify that expected semantic body/feature identity remains resolvable or return explicit evidence of identity loss.

## 6. Transaction and rollback requirements

Mutating workflows should be transactional wherever technically feasible.

Required principles:

- explicit preconditions;
- bounded operation/runtime budgets;
- checkpoint/rollback policy;
- idempotency where applicable;
- explicit commit/rollback outcome;
- document restoration evidence;
- no blind retry after uncertain state.

A failed operation that reports rollback must independently prove restoration when the caller relies on it.

Post-dispatch timeout or connection loss is `TRANSPORT_UNCERTAIN` until reconciled. Never assume the mutation did not occur merely because a response was lost.

## 7. Document ownership and reconciliation

Document identity is safety-critical.

New or modified execution paths should preserve enough information to determine:

- active document identity/type;
- intended save path;
- ownership/lifecycle context;
- whether the document was recreated/reopened;
- whether a mutation was committed;
- whether evidence belongs to the expected document/revision.

Reject stale/wrong-document evidence.

Recovery after uncertain dispatch must reconcile live SOLIDWORKS state before a caller is allowed to retry the mutation.

## 8. Evidence is separate from execution success

`success=true` is execution evidence only.

Do not treat it as proof of geometry, topology, artifact freshness, or acceptance.

Where relevant, provide independent evidence such as:

- rebuild state;
- expected identities;
- body count;
- bounding box;
- volume;
- critical dimensions;
- section/ray/surface probes;
- interference;
- component transforms;
- tessellation/native geometry export;
- artifact/document fingerprints;
- save/reopen consistency.

Never satisfy a verification field by copying the requested/expected value from the plan instead of measuring the actual native model.

## 9. Native assembly capability

The target architecture requires a robust generic assembly surface.

Prioritize and qualify operations equivalent to:

- create assembly;
- insert/replace/remove component;
- set/get component transform;
- list components;
- measure assembly envelope;
- interference checking;
- save, close, reopen, and verify assembly.

Mechanical mates are not required for every insert use case. Deterministic explicit component transforms are a valid primary path when they give better reproducibility.

Assembly acceptance must survive save/reopen rather than being trusted only immediately after construction.

## 10. Mesh and hybrid-BREP materialization

Local-CAD's target design space includes full-3D mesh-derived pockets and organic regions.

SolidworksMCP must therefore support/qualify generic materialization paths for the required editability classes:

- E1: native parametric BREP;
- E2: parametric model plus controlled organic region;
- E3: qualified mesh/hybrid-BREP path.

Do not force arbitrary organic meshes through uncontrolled automatic full-parametric reconstruction.

For mesh/hybrid operations, qualify at least:

- import correctness and units;
- closed/open mesh assumptions;
- body type after import/conversion;
- boolean behavior;
- body identity behavior;
- save/reopen persistence;
- export/readback;
- geometric deviation from source/planning geometry.

A successful import or feature call alone is not qualification.

## 11. Construction recipes versus product design

SolidworksMCP executes construction operations; it does not decide product architecture.

If one native construction method fails (for example loft, fillet, shell, or boolean), report a structured materialization failure. The caller may choose an alternative recipe without changing the product design.

Use failure classes that distinguish, where possible:

- invalid source geometry;
- recipe/feature failure;
- native rebuild failure;
- environment/UI failure;
- document mismatch;
- transport uncertainty.

Do not silently redesign geometry to make a feature succeed.

## 12. SOLIDWORKS UI and COM safety

The server controls an interactive SOLIDWORKS process, not a headless pure kernel.

Never auto-confirm unknown modal dialogs.

Only narrowly scoped, recognized dialogs may be handled automatically, with explicit operation context and bounded watchdog behavior.

Be cautious with locale, units, template discovery, selection state, active sketch/document state, and view commands.

MCP-facing coordinates use the declared user unit (normally millimetres). Raw SOLIDWORKS COM uses metres. Keep unit conversion explicit and tested.

## 13. Testing and live qualification

Keep these states distinct:

- implementation complete;
- deterministic unit/regression tests green;
- CI qualified;
- live response qualified;
- live CAD lifecycle qualified;
- full end-to-end live qualified.

Mocks cannot qualify SOLIDWORKS COM behavior.

Any new high-risk native capability should have:

1. deterministic tests for argument validation, ordering, normalization, and failure handling;
2. live qualification on the target SOLIDWORKS version;
3. independent evidence after mutation;
4. save/reopen verification when persistence matters.

Regression testing must retain previously qualified sketches/features/transactions/evidence while adding mesh/hybrid and assembly coverage.

## 14. Compatibility and capability discovery

Treat the live tool schema and `get_capabilities` as authoritative for clients.

Do not make callers rely on a fixed total tool count.

When changing a tool contract:

- preserve backward compatibility where practical;
- version/describe capability changes;
- update tests and documentation together;
- avoid ambiguous overloaded response shapes.

Known response normalizations must be exact and fail closed; unknown states must not be coerced into ready/success states.

## 15. Public repository discipline

This repository is public. Do not commit:

- local credentials/tokens;
- machine-specific secrets;
- private project/game data;
- generated user CAD files unless deliberately sanitized fixtures;
- private filesystem paths when they are not required test data.

Keep machine-specific overrides in ignored/local configuration.

## 16. Roadmap priorities for the current target architecture

Unless superseded by a newer accepted ADR/roadmap, prioritize:

1. release/mainline convergence and a single clear development path;
2. document ownership and post-dispatch reconciliation;
3. generic native assembly operations and verification;
4. materialization primitives needed by Local-CAD PartGeometrySpec recipes;
5. mesh/hybrid-BREP qualification;
6. expanded native geometry evidence;
7. construction-recipe fault classification;
8. golden part and assembly materialization benchmarks.

Do not spend substantial effort on insert-specific optimization or board-game semantics in this repository.

## 17. Git/PR discipline

Before starting a new branch or PR, inspect current branch/PR topology and avoid duplicating active work.

Prefer one clear release path instead of indefinitely growing branch stacks.

Keep commits scoped and technically meaningful. Do not create no-op or documentation-only churn unless documentation itself is the intended deliverable.

Do not merge merely because CI is green when required live acceptance gates remain open. State the actual qualification level clearly.

For substantial work, leave a compact handoff with branch/head, tests, live qualification, known gaps, and next steps.

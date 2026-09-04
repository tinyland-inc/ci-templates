# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer 2.0](https://semver.org/).

## [Unreleased]

## [5.1.1] — 2026-09-04

### Changed

- **TIN-4257 qualified-result caller contract.** Pass every `spoke-ci-v4.yml`
  invocation one new job-unique result directory beneath `RUNNER_TEMP`. The
  checked-in ActionPlan remains the sole result-disposition authority; the
  workflow does not parse, upload, publish, or fall back from the
  image-custodied client's result.

## [5.1.0] — 2026-09-03

### Changed

- **TIN-4246 portable v4 dispatch edge.** Route `spoke-ci-v4.yml` through the
  adopting organization's `gf-v4-dispatch` edge instead of a Tinyland provider
  label. The thin edge invokes the compiled client; REAPI schedules actions.
  Consumer repositories still name neither runner supply nor provider detail.

### Removed

- Retire the active v3 cache/profile enrollment instructions. V4 adoption is an
  organization-owned App and overlay plus a checked-in ActionPlan and immutable
  workflow call; missing authority fails closed and has no cache-only or local
  compatibility path.

## [5.0.0] — 2026-09-02

### Changed

- **TIN-2130/TIN-4249 ActionPlan/v4 schema 3 (targets ci-templates v5.0.0).**
  Make `result` mandatory for every action, with the closed dispositions
  `status-only` and `export-regular-files`. Export mode requires exact Bazel
  target labels and 1--8 named output groups; it is carried only through the
  compiled client's verified `ActionOutputSet/v1`, never through workflow-side
  artifact discovery. Admit both Linux x86_64 and Darwin arm64 as abstract,
  provider-blind capability demand; absent signed supply fails resolution.
  The reusable `spoke-ci-v4.yml` dispatcher is byte-identical. The schema bytes
  are vendored from signed site.scaffold #163 commit
  `0a46c06b3415ba0b9dc4e8ff98173a6087d0ba68`.

### Removed

- Treat schema 2 as historical `v4.0.0` input, not a compatibility or local
  execution fallback. Schema-3 consumers must migrate atomically with their
  signed consumer-owned overlay digest and provider image; GF core and this
  repository continue to own no consumer instances.

### Fixed

- Correct the v4 release boundary after the first consumer canaries failed
  closed on an absent `/usr/local/bin/gf-action-client`: the immutable template
  requires the client at a provider-custodied image path, but its source release
  does not prove that provider rollout. The released 4.0.0 entry no longer calls
  its own tagged source a held, unreleased carrier.

## [4.0.0] — 2026-09-01

### Changed

- **TIN-2130 v4 action-fabric foundation** (carrier comment
  `a7fb6f87-5d45-45a6-bd99-136c4f461fbd`). `spoke-ci-v4.yml` is now an
  exact-checkout, compiled-client dispatcher. One invocation selects one named
  action from the checked-in `.github/lanes.json` plan, and the workflow invokes
  `/usr/local/bin/gf-action-client run` once with the admitted source SHA. The
  plan is an admissibility boundary and does not claim one invocation executes
  every member. The
  admitted SHA is the exact owner-overlay identity: the pull-request head SHA
  for same-repository pull requests and `github.sha` for pushes. Unsupported
  event shapes do not enter the action-fabric job, and the workflow never
  substitutes GitHub's synthetic merge commit for a pull-request head. The
  vendored schema is an exact
  projection of GloriousFlywheel `Core.dhall`: actions contain only Bazel
  command, finite targets, and the one currently executable abstract REAPI
  capability (`rbe-linux-x86_64`). Darwin remains schema-inadmissible until its
  worker, provider route, client support, and canary exist. Provider pool,
  runner, resolved platform, endpoint, profile, upload, and fixed concurrency
  fields were removed from consumer manifests and plans. Inline
  OIDC, token, proxy, sandbox, OCI, cleanup, and fallback orchestration was deleted rather
  than becoming a second scheduler/client implementation. The old lane-env and
  zero-caller public-preview surfaces remain deleted, and the existing central
  validator shrank with the public surface. V3 remains unmodified. The
  `v4.0.0` tag releases this workflow source only; it does not itself prove
  adoption, provider convergence, installation, or runtime execution.

### Removed

- **The dependency-free fallback validator is deleted** (TIN-4132, operator
  ratification 2026-08-27; landed per TIN-4192). This SUPERSEDES the three
  entries below that describe widening and guarding that subset: there is no
  second engine left to widen. `scripts/manifest-schema-validate.py` now
  imports `jsonschema` or exits 5 naming the dependency, and the composite does
  the same before it reads anything.

  The subset was a gate that read as coverage while enforcing less than the
  schema said. `not` went unevaluated for months, so every prohibition passed
  unconditionally — static spokes carrying the evicted
  `authorities.gitops_receiver` validated at exit 0 against the authority v1
  schema. Under it, v2's `allOf[5]` overlay guard fired vacuously alongside
  `allOf[11]`, making `application-owner-overlay` and
  `organization-execution-overlay` unsatisfiable; that was misread as schema
  over-reach for weeks. Widening the subset and adding
  `assert_fallback_covers()` made it honest about its gaps, but honest-about-a-
  gap is still a second engine kept in step by a hand-written harness.

  Its REASON FOR EXISTING is also gone: the TIN-2109 cold-`nix develop`
  store-lock failure belonged to the shared-store host-runner generation, and
  current ARC pods mount per-pod ephemeral nix stores (GF substrate
  confirmation, 2026-08-27).

  **Supplying `jsonschema` is the calling workflow's job, and no ci-templates
  composite does it.** An earlier draft of this entry — and of the refusal
  message itself — said the `nix-setup` composite supplied it "cache-hot from
  the in-cluster Attic". That was wrong: `nix-setup` detects Attic and Bazel
  cache endpoints (grep its action.yml for `python|pip|jsonschema|nix develop`
  and only `set -euo pipefail` matches), and `setup-nix` installs Nix and its
  daemon. Neither installs a python package. A hard refusal whose named remedy
  is inert is a dead end with a helpful tone, so the message now names remedies
  that exist (`nix profile install nixpkgs#python3Packages.jsonschema`, or a
  devshell the job runs inside) and states which composites cannot help. Two
  selftest cases pin both halves of that sentence.

  **The action still does not shell out to `nix develop`** — the TIN-2109
  ruling that it must not stands, and `just cache-backed-optin-contract-check`
  still asserts it. Providing the interpreter is the calling workflow's job.

  What replaces the deleted differential lane is a REFUSAL contract in
  `scripts/manifest-schema-validate-selftest.sh`: with `jsonschema` hidden, the
  validator must exit 5 and name the dependency, and must NOT return a verdict
  of any kind — including on an invalid manifest, where answering 1 would mean
  something still validated it. Every one of those cases returned 0 or 1 off
  the subset before this change, so they are live guards against a fallback
  being reintroduced rather than tautologies. Mutate-proved: reinstating a
  fallback that answers "valid" on `ImportError` fails 6 of 24 cases and
  nothing else. On a host that cannot import `jsonschema` the harness itself
  refuses (its own exit 2) instead of reporting green over an engine it never
  ran.

### Fixed

- **The refusal has its own exit code (5); exit 2 means usage/IO again.** They
  were one code, and the composite action's `2)` arm — written for the refusal
  — announced "this is a RUNNER problem, not a manifest problem" for every
  usage/IO error it inherited. Reproduced: a `tinyland.repo.json` with a stray
  comma made the validator print its own honest `::error::cannot read manifest:
  Expecting value: line 1 column 32`, and the action then told the caller their
  runner was broken. It is a diagnostic regression against `main`, where the
  passthrough arm let the real error stand, and it is the same "two copies of
  one fact drift apart" failure this release exists to close, reproduced one
  directory from the file closing it.

  `EXIT_NO_ENGINE = 5` is now the refusal, `2` is only "the CLI was called
  wrongly, or the manifest or a schema could not be read", and the action has
  an arm for each. The selftest grew a usage/IO lane (malformed manifest,
  absent manifest, no arguments — all with the engine present) which had no
  coverage before; that absence is precisely why the two meanings could drift
  apart unnoticed. Mutate-proved: collapsing 5 back into 2 fails 6 cases,
  restoring the inert `nix-setup` remedy text fails 2.

- **The vendored-schema provenance gate covers `schemas/*.schema.json`, not
  just the manifest pair.** It globbed `tinyland-repo-manifest*.json` and
  printed "all 2 vendored schemas match" over a directory holding four. The
  file it structurally could not see, `schemas/lanes.schema.json`, carries a
  site.scaffold `$id`, is drifted today, and backs the `lanes-load` action that
  consumer CI runs — a gate reading as coverage while enforcing less than it
  appears to, which is the standard this release is written against.

  `blahaj-dispatch.schema.json` remains `unsourced`: its `$id` names a
  site.scaffold path that **404s** at the recorded revision, so its digest is
  pinned but no provenance can be
  claimed. That also shows the "`$id` names the authority" heuristic this
  record rests on is not reliable on its own.

  The earlier v3-era instruction not to re-vendor `lanes.schema.json` is
  superseded by TIN-2130 comment `a7fb6f87-5d45-45a6-bd99-136c4f461fbd`.
  V4 removes runner selection from the schema entirely and deletes the orphaned
  `lanes-schema-runner-class-check`. The paired site source is committed at
  `7be3a545f530d003e734dd8e6f1fd5b8481244e1`; the vendoring record pins that
  revision and matching upstream SHA-256, so the entry is now `identical`.

- **`state` and `upstream_sha256` in `schemas/VENDORED.json` are asserted, not
  merely recorded.** `identical` now requires `upstream_sha256` to equal the
  vendored digest, `drifted` requires one that differs, `unsourced` requires
  none, and an unknown state is an error. Before this, an entry could claim
  `identical` beside an `upstream_sha256` of 64 zeros and pass silently — in
  the exact field an operator reads to sequence the v1 de-fork. A malformed
  entry now names its missing keys instead of dying on an uncaught `KeyError`
  traceback. `source_revision` stays advisory and says so: no offline check can
  prove a string names a real commit.

### Added

- **`schemas/VENDORED.json` + `just vendored-schema-provenance-check`.**
  ci-templates carries COPIES of schemas whose own `$id` names
  `tinyland-inc/site.scaffold` as the authority, and until now there was no
  lock and no gate — which is how the v1 copy diverged from its source in BOTH
  directions (ci-templates gained `authorities.artifact_registry`;
  site.scaffold gained a `gitops_receiver` prohibition) with nothing comparing
  them. The v2 copy arrived the same way and is byte-identical to its source
  today, which is exactly why this is the cheapest moment to record it.

  The gate is deliberately HERMETIC: it compares the vendored bytes to the
  recorded digests and does not reach site.scaffold, because a network call
  would make every consumer's CI depend on another repository being reachable.
  It catches what a lock can catch offline — a hand-edit that never went
  through a re-vendor — plus a schema in `schemas/` that no entry records at
  all, a malformed entry, and an empty record that would otherwise vouch for
  nothing. v1 is recorded as `drifted` and REPORTED, not failed: adopting
  upstream's v1 bytes changes what every existing consumer is validated against
  and is its own change with its own review. Mutate-proved eight ways: a
  flipped byte in a vendored copy, an unrecorded schema file, an emptied
  record, a dropped `sha256` key, `identical` beside a zeroed
  `upstream_sha256`, `drifted` with a matching one, `unsourced` carrying one,
  and an unknown state. Each goes red; the restored tree goes green. A garbage
  `source_revision` stays green **by design**, and both the record and the
  summary line now say so.

### Fixed

- **`validate-ci-templates.py manifest` no longer hardcodes v1 either.** It
  resolved `schemas/tinyland-repo-manifest.schema.json` unconditionally — the
  same defect the composite shipped, one directory over, and it survived that
  fix because nothing pointed the two at each other. Measured on this repo's
  own manifest with `schema_version` set to 2, the old code answered
  `/schema_version: 1 was expected`; it now imports `resolve_schema_name` from
  `scripts/manifest-schema-validate.py` so `SCHEMA_BY_VERSION` stays the single
  copy of the mapping, and reports the real v2 errors instead.

- **`repo-manifest-validate` routes by `schema_version` instead of hardcoding
  v1** (MINOR — a previously-failing consumer starts passing; no passing
  consumer changes). The composite passed
  `schemas/tinyland-repo-manifest.schema.json` unconditionally, so a spoke that
  had migrated to the published `schema_version` 2 failed the gate with a wall
  of `Additional properties are not allowed` ending in `at /schema_version: 1
  was expected` — the gate blaming the manifest for declaring the version it
  actually declares, when the real fact was that the action had no branch for
  it. `schemas/tinyland-repo-manifest.v2.schema.json` is now vendored alongside
  v1, and the action passes `--schemas-dir schemas` so
  `scripts/manifest-schema-validate.py` owns the whole version → schema mapping
  in one place (`SCHEMA_BY_VERSION`). Routing is total: an absent, mistyped, or
  unpublished version exits 3 naming the value it saw, never silently routed to
  v1; a version that routes to a schema missing from the ci-templates checkout
  exits 4, because that means nothing validated the manifest at all.
  `validate-ci-templates.py cache-backed-optin-contract` now fails if the action
  resolves a schema file itself or if a mapped version is not vendored here.

- **The router and the schema it routes to now agree about what an integer is.**
  `schema_version: 2.0` exited 3 as "mistyped" while the v2 schema it would have
  routed to accepts `2.0` outright — JSON Schema 2020-12 counts a number with
  zero fractional part as an `integer` and compares numbers mathematically, so
  the gate was rejecting a document that is in fact conformant and telling the
  operator to fix it. `_as_schema_version()` now accepts integral floats and
  still rejects `true` (`bool` subclasses `int` in Python, but `true` is not
  version 1 in JSON), `2.5`, `NaN`, and `inf`.

- **The fallback validator compared `const`/`enum` with Python equality, so a
  JSON boolean satisfied a numeric `const`.** `True == 1` in Python; in JSON a
  boolean and a number are never equal. Pointed at the v1 schema, whose
  `schema_version` is `{"const": 1}`, the subset returned exit 0 for
  `{"schema_version": true}` where the authoritative validator returns 1 —
  measured against the previous revision of the file. Comparison is now
  `_json_equal()`, implementing the 2020-12 equality rules; note this is *not* a
  type check, because numbers must still compare mathematically (`1.0` satisfies
  `{"const": 1}`), and the harness pins both directions.

- **The dependency-free fallback validator no longer under-enforces the schema
  it is pointed at.** Its JSON Schema subset implemented neither `not`, `anyOf`,
  nor `contains` — which is how the v2 schema expresses every boundary rule
  (17/4/13 occurrences: a spoke must NOT claim apply-plane authority, a layered
  role MUST contain its layer). Routing v2 to the v2 schema without this would
  have swapped a loud wrong answer for a silent one on precisely the nix cluster
  runners the fallback exists for: measured, the old subset returns exit 0 for a
  v2 manifest the authoritative validator rejects. The subset now implements
  those keywords plus `oneOf`/`maxLength`/`maxItems` and boolean schemas, and
  `assert_fallback_covers()` refuses to produce a verdict at all (exit 2) when a
  schema asserts with a keyword outside `ENFORCED_KEYWORDS`. A future schema
  keyword now stops the gate loudly rather than quietly draining it.

- **The action guards read the action's shell, not the action's prose.**
  `validate-ci-templates.py` asserted the composite passed `--schemas-dir` with
  a whole-file substring test — which the paragraph in that very step explaining
  why `--schemas-dir` is passed satisfies on its own. Deleting the flag from the
  command while keeping the comment left the guard green and every consumer
  silently re-pinned to v1. The guards now extract the `Validate repo manifest
  schema` step's `run:` block, drop comments, resolve shell variables, and
  inspect the argument vectors that actually execute; a step that names the
  validator only in a comment fails as "a comment naming it is not a gate", and
  a line the lexer cannot read is reported rather than skipped. Mutate-proved
  three ways (flag deleted, explicit schema file passed, invocation commented
  out); the old substring test passes the first of those.

- **`just manifest-validate-selftest` became a real harness**
  (`scripts/manifest-schema-validate-selftest.sh`, 33 cases). It runs every case
  down BOTH validator paths — the authoritative `jsonschema` one, and again with
  `jsonschema` forced unimportable — so the fallback is exercised on machines
  that have the package; a harness that only tests the path the developer
  happens to have is how the coverage gap survived. The authoritative lane now
  carries a **positive control**: a schema using `dependentRequired`, which
  `jsonschema` evaluates (exit 0) and the stdlib subset refuses (exit 2), so the
  lanes must disagree. On a host with no `jsonschema` the "authoritative" lane
  would otherwise be a second silent run of the fallback and every agreement
  assertion would be a self-comparison — mutate-proved: collapsing the lanes
  fails the control and nothing else (32 pass, 1 fails). Such a host now gets a
  named SKIP and a counted lane list rather than a relabelled duplicate. The old
  negative fixture mutated `schema_version` to `2` to produce an "invalid"
  manifest, which now asserts that a supported version is invalid; it is
  replaced with mutations that are wrong for exactly one reason each, including
  one that only a `contains` assertion can catch.

- **Known drift recorded, not silently reconciled** (README § Schemas): the
  vendored v1 manifest schema and site.scaffold's copy have diverged in both
  directions. Measured with the normalise-then-diff command recorded in the
  README (a raw `diff -u` reports 136 changed lines, almost all formatting):
  22 differing lines, 13 only upstream and 9 only here, resolving to **two**
  constraint-bearing differences — this repo carries an
  `authorities.artifact_registry` property site.scaffold lacks; site.scaffold
  carries an `authorities` `not`/`required` constraint on `gitops_receiver` this
  copy lacks — plus five annotation-only differences. Pinned to blobs so the
  figure stays checkable: `c724d1bf` here, `981427d8` at site.scaffold
  `6c58bb6`. Nothing compares them. The v2 schema vendored here is
  byte-identical to site.scaffold's (both blob `74c13a7a`, last changed upstream
  by `8659dcd`). Reconciling the v1 copies is a change to the vendored file, not
  to this router.

- **`tinyland.repo.json`: retired the stale gitops-receiver assertions**
  (PATCH) — removed the `gitops-receiver` taxonomy layer and the
  `authorities.gitops_receiver: tinyland-inc/blahaj` key. The blahaj
  receiver path was evicted at blahaj #1255 (2026-08-05); lane lifecycle
  belongs to each application's owner overlay (site.scaffold
  `docs/patterns/owner-overlay-apply-plane.md`), which is per-application
  and cannot be honestly named in a single-string authority field. This
  repo only ever shipped the dispatch composites that talked to a
  receiver; it never hosted one, and `boundaries.owns_gitops_apply` was
  already `false`. Manifest-only; no consumer reads either value.

## [3.1.0] — 2026-08-19

> **This section releases as `v3.1.0` (MINOR)** per `RELEASING.md`: a new
> optional input, with the default preserving today's behaviour byte-for-byte.
> No existing caller changes, and no repo that passes CI today starts failing.

This bump silently upgrades gitleaks 8.21.2 → 8.30.1 for every `spoke-ci.yml`
consumer (via the `@v2`→`@v3` internal-ref bump below) — spokes with
`[[allowlists]]` will see them honored for the first time.

### Added

- **TIN-3815: `allowed_repo_roles` input on `spoke-ci.yml`** — makes the
  repo-manifest role census caller-configurable, so a repo whose ratified
  `taxonomy.primary_role` is not a static-spoke variant can run this lane
  without a template edit. Accepts a comma-separated list **or a JSON array**;
  both normalize identically (surrounding brackets, quotes, and whitespace are
  stripped before the comma split, so there is no second code path).

  **Where the normalization runs is part of the contract.** The JSON→comma
  conversion is done by the *workflow* (`startsWith`/`fromJSON`/`join`), not by
  the composite action. A `uses:` step resolves the action at its own ref, so an
  action-side rule ships only when a release moves that ref — and never for the
  restricted variant, whose closure is pinned to an exact release by contract.
  Verified against the real tags before choosing: `git show
  v2:.github/actions/repo-manifest-validate/action.yml` and its `v3` equivalent
  both comma-split with no stripping, so an action-side normalization would have
  been a JSON promise the shipped artifact did not keep. The workflow file is
  what a consumer pins, so the rule lives there and holds at every action ref.
  `repo-role-census-contract.rb` pins that expression byte-for-byte and refuses
  to render any other shape.

  **The defect was two hardcoded sites, not one.** `spoke-ci.yml` pinned
  `required_roles: static-spoke,static-spoke-scaffold` at the `repo-manifest`
  job **and** again at the `cache_backed` lane's manifest gate inside
  `flywheel-build` — independently. A spoke could satisfy one and fail the
  other, and a fix applied to either would have looked complete. Both are
  threaded now, and so are the matching pair in `spoke-ci-restricted.yml`.

  New `just repo-role-census-contract-check` (+ `-selftest`, 9 negative
  oracles) therefore asserts a **site census** first and values second: the set
  of `repo-manifest-validate` invocations is pinned, and every one must route
  through the input — add a third census site without threading it and the
  build fails. It then proves `allowed_repo_roles` unset renders the pinned
  pre-TIN-3815 literal byte-for-byte, set threads the caller's value verbatim,
  and `spoke-ci-restricted.yml` matches site for site. The oracles reject each
  site left hardcoded (separately), a silently widened *or* narrowed default,
  an undeclared input, a dropped `required_roles`, an untreaded new site, and
  restricted-variant drift.

- **A census failure now names its remedy.** `repo-manifest-validate` printed
  only `taxonomy.primary_role=X is not one of: …`, which read as a hard wall.
  It now adds the exact caller-side line that widens the census. That silence
  is a fair share of why this looked like a template limitation rather than a
  one-line input.

### Fixed

- **`spoke-ci.yml`'s internal action refs were frozen on the v2 line, so a
  shipped security fix reached nobody.** All 14 `uses:
  tinyland-inc/ci-templates/.github/actions/…@v2` refs stopped advancing when
  `v2` froze at v2.14.0 — and `@v2`'s `secrets-scan` still installs **gitleaks
  8.21.2**, the version that silently ignores a repo's `[[allowlists]]` table.
  That is exactly the bug TIN-3900 fixed and v3.0.0 shipped; because the
  workflow pulled its action at `@v2`, every `spoke-ci.yml` consumer kept
  running the broken scanner while believing they had the fix. Refs now track
  `@v3`. Same for `spoke-lane-env.yml`'s 6 refs (provably inert — none of its
  four actions changed between v2.14.0 and v3.0.0 — but it pairs with a
  restricted variant, which requires both lanes on the same floating line), and
  for two composite-to-composite `nix-setup@v2` refs in `greedy-cache` and
  `nix-build` that the new check surfaced.

  **The check could not have caught this: it discarded the ref.**
  `internal-refs-check` iterated `for action, _ref in …` and only asserted the
  action *existed*. It now asserts every internal ref is on the current release
  line or is an exact release pin (the restricted variants' immutability
  contract), and carries an explicit debt ledger for files still on the old
  line — `js-bazel-package.yml`, `spoke-deploy-cloudflare-pages.yml`,
  `spoke-public-preview.yml` (TIN-3914). The ledger fails closed in **both**
  directions: an unlisted file with a stale ref fails, and a listed file that is
  no longer stale also fails, so it cannot rot into a lie.

- **`restricted-workflow-contract.rb`'s legacy↔restricted `uses:` mapping
  hardcoded `@v2`.** It normalizes a restricted exact pin back to the legacy
  floating ref for the structural comparison; the target major was a literal, so
  it silently stopped matching the moment the legacy lane moved to v3. Now a
  named `LEGACY_FLOATING_MAJOR` constant.

### Changed

- **`SPECS["spoke-ci"][:legacy_sha256]` re-recorded** (`a312785b…` →
  `ac5018e8…`) for the input above, with the reason written at the pin. The two
  literals became `${{ inputs.allowed_repo_roles }}` whose declared default is
  that same literal, so the census default is unchanged; the digest is a
  tripwire on the legacy bytes, not a claim they never change deliberately. It
  also absorbs the `@v2`→`@v3` ref bump above, which *is* a deliberate
  behaviour change: it delivers the gitleaks fix consumers already believe they
  have. `SPECS["spoke-lane-env"][:legacy_sha256]` re-recorded for its own ref
  bump (`c238ab59…` → new), reason written at the pin.

### Deliberately not changed

- **`app-stateful-spoke` is NOT in the default allowlist.** It is ratified in
  the vendored schema's `$defs.repoRole`, and adding it to the default was
  proposed — but ratification of a **role** is not ratification of a **template
  binding**, and three things argue against it:

  1. **The schema itself separates the families, materially.** Its `allOf`
     block constrains `static-spoke`/`static-spoke-scaffold` to
     `owns_runtime_backend`, `owns_auth`, `owns_payments`,
     `owns_activitypub_delivery`, `owns_live_broker_fetch`,
     `owns_gitops_apply`, `owns_cloudflare_mutation` **all `const: false`**, and
     deliberately omits `app-stateful-spoke` from that `if`. An app-stateful
     spoke may own a runtime backend, auth, and payments. The two roles are not
     interchangeable inputs to a census whose job is "is this the right
     template for this repo".
  2. **The premise that other gates would cover it does not hold here.** This
     census is the *only* place in ci-templates where `taxonomy.primary_role` is
     enforced at all (`grep -rn primary_role` reaches exactly one action), and
     the boundaries constraint above is precisely what does *not* apply to
     `app-stateful-spoke`. Widening the default would remove a signal with
     nothing behind it, in the workflow that runs on every spoke.
  3. **AGENTS.md rule 2, and the semver line this repo just drew.** Widening the
     default changes behaviour for consumers who did not opt in; the input *is*
     the mechanism rule 2 prescribes. `v3.0.0` took a MAJOR precisely because it
     changed defaults without an opt-out, and `docs/migration-v2-to-v3.md`
     argues a MINOR must be a safe unread pin bump. Shipping a widened default
     as a MINOR one release later would retract that.

  Widening by default is also close to irreversible: once ~190 consumers
  inherit a wider census, narrowing it again is a MAJOR. Widening per-spoke via
  the input is reversible and costs the adopting spoke one line. An
  app-stateful spoke opts in with:

  ```yaml
      allowed_repo_roles: static-spoke,static-spoke-scaffold,app-stateful-spoke
  ```

## [3.0.0] — 2026-08-19

> **This section releases as `v3.0.0` (MAJOR).** TIN-3914 below changes default
> consumer behavior with no opt-out and narrows two documented input value
> domains. The MAJOR-vs-MINOR argument is written out in
> `docs/migration-v2-to-v3.md`; the short version is that a MINOR is a promise
> that a pin bump is safe without reading the changelog, and that promise cannot
> be kept here. `RELEASING.md` also requires a `docs/migration-vN-to-vN+1.md`
> for a MAJOR — that document is the consumer migration.

### Removed

- **TIN-3914: every GitHub-hosted runner is gone from this repository.**
  Operator ruling, 2026-08-19, verbatim: *"we should NEVER have gh ubuntu
  runners in place ever, we ONLY use GF infra cache fronted runners."* Every
  `runs-on` in `.github/workflows/*` now names a self-hosted org
  capability-class label. There is deliberately **no opt-out input**: an
  estate-wide prohibition with a "keep using hosted" knob would not be a
  prohibition, which is exactly why this ships as a MAJOR instead of the
  default-off addition `AGENTS.md` rule 2 would otherwise require.

  | Workflow | Job(s) | Before | After |
  |---|---|---|---|
  | `spoke-ci.yml` | `secrets-scan`, `lanes-load`, `repo-manifest` | `ubuntu-latest` | `inputs.default_runner_class` (default `tinyland-nix`), group-routed when `runner_group` is set |
  | `spoke-lane-env.yml` *(deprecated)* | `check-blahaj-token`, `lanes-load`, `dispatch-apply`, `destroy-lanes` | `ubuntu-latest` | `tinyland-nix` |
  | `js-bazel-package.yml` | `resolve-runner` | `ubuntu-latest` | `tinyland-nix` |
  | `npm-publish.yml` | `build-and-test`, `publish-gpr`, `publish-npm` | `ubuntu-latest` | `tinyland-nix` |
  | `rust-bazel-application.yml` | `trust-gate` | `ubuntu-24.04` | `tinyland-nix` |
  | `spoke-deploy-cloudflare-pages.yml` | `build` | `ubuntu-latest` | `tinyland-nix` |
  | `spoke-public-preview.yml` | `dispatch` | `ubuntu-latest` | `tinyland-nix` |

  `spoke-ci-restricted.yml`, `spoke-lane-env-restricted.yml`, and
  `spoke-pulse-ingest.yml` had no hosted path and are unchanged. The restricted
  variants stay a strict subset with **no edit**: `validate_restricted`
  normalizes each job's `runs-on` back to the legacy node before the structural
  comparison, so a legacy routing change cannot widen the restricted contract.

  Routing choice, and why it differs per workflow: a hosted job was moved onto
  the workflow's **existing** runner-class input where one exists
  (`spoke-ci.yml` → `default_runner_class`, so a tenant org that already passes
  `great-falls-tool-bus-nix` gets every job routed with one edit), and onto a
  literal `tinyland-nix` where none exists. No new runner-class inputs were
  invented: `npm-publish.yml`, `spoke-deploy-cloudflare-pages.yml`, and
  `spoke-public-preview.yml` have zero callers in the 2026-08-19 fleet sweep,
  and `spoke-lane-env.yml` is deprecated and must not grow a new caller-facing
  contract.

- **`js-bazel-package.yml`: `runner_mode: hosted` and
  `publish_mode: hosted_exception` are retired and now REJECTED** with a
  migration error, not silently re-routed. All 30 current publish call-sites in
  the sweep pass `hosted_exception`, so this is the break that forces the MAJOR
  on its own. Rejecting rather than aliasing is deliberate: a token-bearing
  publish job changing which machine it executes on is a security-relevant
  change and should be an edit the caller makes, not one that happens to them.

  **Read this before bumping a package pin:** the publish step only passes
  `npm publish --provenance` when `runner.environment != 'self-hosted'`. That
  guard is unchanged, but publishes are now always self-hosted, so
  `npm_publish_provenance` is **inert and npm provenance is no longer
  requested**. The job now emits a `::warning::` rather than dropping the
  supply-chain claim silently. A package whose policy requires provenance
  should not bump its pin until a provenance-capable self-hosted path exists.

### Fixed

- **`npm-publish.yml` requested `npm publish --provenance` unconditionally on a
  job TIN-3914 had just moved to a self-hosted runner** — which does not merely
  drop an attestation, it **fails the publish**. npm validates provenance
  server-side by comparing the Runner Environment extension in the Fulcio
  signing certificate against an allow-list that excludes `self-hosted`; the
  OIDC token is obtainable there, the attestation is still rejected. The step is
  now gated on `runner.environment == 'github-hosted'` and emits the same
  `::warning::` as `js-bazel-package.yml`. `docs/npm-publish.md` had claimed the
  guard already existed "the same way `js-bazel-package.yml`'s does"; it did
  not, and the sentence is replaced with what the file actually does. Both
  provenance guards now fail **closed**: they test for `github-hosted` rather
  than `!= self-hosted`, so an empty or unexpected value takes the
  no-provenance path instead of attempting a publish that would be rejected.

- **`schemas/lanes.schema.json` still sanctioned a GitHub-hosted label straight
  into `runs-on`.** `runnerClass` carried `{"const": "ubuntu-latest"}` with a
  description blessing it "for jobs whose entire purpose is a `gh api` call".
  That was the last sanctioned hosted path in the estate and none of the new
  gates could see it, because it is **consumer data**: `lanes-load` validates a
  spoke's `lanes.json` against this schema, and `spoke-ci.yml` resolves
  `flywheel-build` / `flywheel-test` `runs-on` through
  `matrix.lane.runner_class` on the default path. `lint-runs-on.rb` reads
  workflow text; the textual backstop read `.github/` only. The const arm and
  its description clause are gone, and new `just lanes-schema-runner-class-check`
  proves the point **semantically** rather than textually: it executes every
  accept-arm of the schema against 9 hostile labels (mixed case included) and 6
  capability classes, so an arm that re-opens the hole in a new spelling fails
  even if it never writes a hosted label down — and an arm tightened until it
  drops tenant-org classes fails too. `schema_version` stays `1` deliberately:
  bumping it would invalidate every consumer's `lanes.json` over a restriction,
  a far larger break than the restriction itself. No surveyed consumer used a
  hosted `runner_class`, so this closes a hole rather than breaking callers.

- **The linter silently PASSed an expression that resolved only some of its
  arms.** An arm resolving to nothing pushed no result, so
  `${{ github.event_name == 'push' && 'tinyland-nix' || vars.FALLBACK_RUNNER }}`
  returned **`:pass`** — not even WARN — while handing the consumer an unaudited
  runtime path to any label, hosted included. The header's "unresolvable forms
  WARN" promise had excluded the mixed shape, which is the easy one to write.
  A surviving context reference now **floors the verdict at `:warn`**. Floored,
  not failed: this guard's core promise is that it never FAILs a `runs-on` it
  cannot statically resolve, and escalating would break every legitimate
  repo-variable routing shape in the estate and bury the real hosted FAILs in
  noise. Flooring only raises `:pass` to `:warn` and never lowers a `:fail`.
  Comparison operands are now consumed whole, so a dynamic *condition*
  (`vars.X == 'true' && 'a' || 'b'`) stays a clean PASS — only a dynamic *value*
  arm warns. Two pre-existing oracles flip `:pass` → `:warn` and are relabelled
  in place; five new cases pin the rule. Oracle 70 → 75.

- **`no-hosted-runners-check` was a substring grep, and its effective policy was
  decided by spelling.** It was case-blind, so `Ubuntu-Latest` — which schedules
  on GitHub's fleet, since runner labels are case-insensitive — walked straight
  past it. And it failed `blacksmith-4vcpu-ubuntu-2204` (which merely *embeds*
  `ubuntu-2`) while passing `namespace-profile-default`: two labels in the same
  third-party fleet, opposite verdicts, contradicting the documented "third-party
  fleets WARN" policy the linter correctly implements. Replaced by
  `scripts/no-hosted-runners.rb`, which tokenizes whole labels and classifies
  them through the shared taxonomy (so it is case-insensitive by construction
  and agrees with `lint-runs-on.rb` on third-party fleets), and which now scans
  `schemas/*.json`, `tinyland.repo.json`, and `bazelrc/*` as well as
  `.github/` — the scope gap that hid the lanes-schema hole. 19-case self-test
  covering mixed case, both third-party fleets, schema consts, and comment-only
  prose.

- **`js-bazel-package.yml`'s hosted-label rejection named the wrong input.**
  `reject_hosted` ran once on the *selected* label list with a hardcoded
  `"runner_labels_json"`, but in `shared` mode that list *is*
  `shared_runner_labels_json` — so a `shared`-mode caller was told to fix an
  input they never set, during a MAJOR migration. Both lists are now checked
  under their own names, before selection, which also makes the docs true where
  they say every mode rejects hosted labels in both inputs.

- **`docs/rust-bazel-application.md` documented `v3.0.0` behavior while telling
  consumers to pin `@v2.14.0`** — a reader copying the example would have got
  `runs-on: ubuntu-24.04`. Consumer example bumped; the distinction between the
  consumer pin and the workflow's internal `@v2.14.0` composite refs (which stay,
  and are the immutability contract) is now stated.

- **`Justfile`'s `runner-group-contract-check` comment** — the text operators
  read from `just --list` — still described the pre-TIN-3914 world ("the
  pre-TIN-3902 value", "the four self-hosted jobs", "the `ubuntu-latest` jobs
  never do"). The script's own header had been updated; this had not.

- **`SPECS["spoke-ci"][:legacy_sha256]` re-recorded** (`7595e406…` →
  `656e8c69…`) for the `runner_group` addition above, and the restricted
  contract's input normalization now restores the legacy declaration for a
  routing input the legacy workflow also declares (instead of dropping it), so
  `spoke-ci-restricted.yml`'s required-and-defaultless `runner_group` is still
  compared against the rest of the inputs surface structurally. The default-off
  proof the digest pins is unchanged and is now additionally machine-checked by
  `runner-group-contract-check`. (TIN-3914, above, re-recorded this same digest
  a second time within this release — `656e8c69…` is an intermediate value, not
  what `v3.0.0` ships.)

### Added

- **`.github/actionlint.yaml`** declaring the six shared capability labels, so
  actionlint stops reporting every migrated job as an unknown `runner-label`
  (14 findings → 0, including 3 that pre-dated this change). It is a
  declaration, not a suppression: a typo'd or repo-shaped label still reports,
  and `scripts/lint-runs-on.rb` remains the authority on admissibility.

- **`docs/migration-v2-to-v3.md`** — the consumer migration required by
  `RELEASING.md` for a MAJOR: per-workflow before/after, the two retired
  `js-bazel-package.yml` input values with diffs, the `lanes.json`
  `runner_class` tightening, the npm-provenance consequence, the "queued
  forever, never degrades" failure mode, ARC capacity numbers for the added job
  classes, and the MAJOR-vs-MINOR argument.

  It now also carries a **"what will fail after you bump"** section separating
  the two timelines, because conflating them either panics or under-prepares a
  migrant. *Immediately on the pin bump:* the retired input values, the
  `lanes.json` schema tightening, an unserved capability class (which queues,
  never falls back), and the provenance loss. *Later, on first wiring the
  `runs-on` gate:* the fleet numbers. `lint-runs-on` is a composite action that
  **no reusable workflow here invokes** and no consumer invoked as of the sweep,
  so the tightened linter does not retroactively fail anyone on a bump — which
  is precisely why the blast radius is published rather than discovered one repo
  at a time. Measured over the 50 local checkouts referencing this repo:
  **4 FAIL across 2 repos at `v2.14.0` → 99 FAIL across 21 repos at `v3.0.0`,
  i.e. 95 new FAILs across 20 repos (40% of consumers; ~75 of ~190 extrapolated)**.
  Per-repo table plus all three failure classes with a diff for each: bare hosted
  literal (75, all new), hosted label baked into a `fromJSON` fallback (20, all
  new — the previously-blessed "graceful degradation" shape), and non-canonical
  self-hosted arrays (4, none new — these already failed at `v2.14.0`). There is
  no long tail; those three classes are all 99.

  **Capacity (from the 2026-08-19 sweep's ARC facts):** `tinyland-nix` is
  `min 0 / max 10`, `great-falls-tool-bus-nix` is `min 0 / max 4`. Added job
  classes: 3 short `spoke-ci` jobs per run × 4 live spokes; 4 short
  `spoke-lane-env` jobs per PR event × 2 spokes (deprecated lane); and
  `js-bazel-package`'s `resolve-runner`, one short job on the critical path of
  **every** invocation across 68 call-sites (62 of them SHA-pinned to a
  2026-05-27 commit, so they arrive only as pins are bumped). `resolve-runner`
  is the one to watch — raise the `tinyland-nix` `AutoScalingRunnerSet` max and
  stage the bumps before a fleet-wide pin bump. `npm-publish.yml`,
  `spoke-deploy-cloudflare-pages.yml`, `spoke-public-preview.yml`, and
  `rust-bazel-application.yml`'s `trust-gate` have zero callers and add no
  immediate load.


- **TIN-3902: optional `runner_group` input on `spoke-ci.yml`** — lets a spoke
  express GitHub's structured `runs-on: { group: <g>, labels: <class> }` for
  every job that today resolves through `default_runner_class` /
  `heavy_runner_class` / `kvm_runner_class` / `runner_labels_json`, so an owner
  can bind spoke CI to an org-level runner group without leaving the shared
  template. **Default `""` = today's label-only behavior** (rule 2,
  `AGENTS.md`): the new expression is `inputs.runner_group != '' && <group
  mapping> || <the byte-identical pre-TIN-3902 arm>`, so an unset group
  short-circuits straight into the old value for all ~190 consumers.

  When set, `flywheel-build`, `flywheel-test`, `bazel-graph`, and `playwright`
  emit the mapping with **the same labels they resolve today** — the labels are
  carried through `toJSON`, preserving `runner_labels_json`'s array shape and
  the `runner_labels_json` → `matrix.lane.runner_class` → `default_runner_class`
  precedence. Jobs whose `runs-on` is a plain literal in the pinned baseline are
  never group-routed. As shipped in this same release, TIN-3914 (above) retired
  the hosted-job class those three jobs belonged to, so `secrets-scan`,
  `lanes-load`, and `repo-manifest` now route through `default_runner_class` and
  are group-routed too — all seven jobs are. Nothing here assumed
  `ubuntu-latest` would survive: the gate derives the never-group-routed set
  from "literal `runs-on` in the baseline", so absorbing TIN-3914 needed only a
  deliberate re-record, not a rewrite.

  A group mapping *narrows*: GitHub schedules only onto a runner that is in the
  group **and** carries the labels, so the group must already exist, select the
  calling repository, and serve the capability label — which is why this is
  opt-in per spoke. It adds routing only, not trust: a private repo that needs
  the fail-closed group+capability trust gate still uses
  `spoke-ci-restricted.yml`, where `runner_group` is required.

  New `just runner-group-contract-check` (+ `-selftest`, five negative oracles)
  renders both paths over a scenario grid — scaffold defaults, the GFTB
  org-scope overlay, a per-lane `runner_class`, and a `runner_labels_json`
  array — and fails if the default path ever stops rendering byte-identically
  or a literal-`runs-on` job starts group-routing (that class is empty after
  TIN-3914, so the self-test keeps the branch executable against a synthetic
  baseline). `scripts/lint-runs-on.rb`
  now evaluates the runtime-composed
  `fromJSON(format('{{"group":{0},"labels":{1}}}', …))` form with the same
  structural semantics as a static `{group, labels}` node (runtime group WARNs;
  a `Default`/`shared`/hosted group or a hosted/repo-shaped label in the mapping
  still FAILs) instead of mistaking the JSON template for a runner label. The
  format template is pinned to that one canonical string: any other template —
  including one with a group or label hardcoded into it — is not this pattern
  and falls back to the ordinary literal scan, which FAILs it.

### Changed

- **TIN-3914: `scripts/lint-runs-on.rb` fails closed on GitHub-hosted labels.**
  A hosted label was PASS; it is now a **FAIL** wherever it can be read
  statically — a bare scalar, any element of a label array (previously
  `[tinyland-nix, ubuntu-latest]` PASSed as "reduces to a shared capability"; it
  does not, GitHub AND-s the labels), a literal arm of a `${{ … }}` ternary, a
  `fromJSON(vars.X || '[…]')` fallback array, a resolved `matrix` value
  including via `matrix.include`, and either arm of a static or
  runtime-composed `{group, labels}` mapping. The previously-blessed "graceful
  degradation to hosted when cluster labels are not reachable" fromJSON shape is
  now a failure: there is nothing left to degrade to. Third-party managed fleets
  (`blacksmith-*`, `depot-*`, `buildjet-*`, …) are neither GitHub's
  infrastructure nor GF cache-fronted, and the ruling named GitHub runners: they
  **WARN**, surfacing for a deliberate decision instead of passing silently.
  `runner_label_taxonomy.rb` splits `hosted_label?` into
  `github_hosted_label?` (FAIL) and `third_party_hosted_label?` (WARN). The
  self-test oracle grew 52 → 75 cases (70 for the hosted rules, then 5 more
  for the mixed-resolvability floor below), every previously-passing hosted case
  flipped in place with its old verdict recorded in the case label. Fleet
  dogfood (`just lint-runs-on-check`) is 0 FAIL.

- **TIN-3914: `just runner-group-contract-check` covers all seven `spoke-ci.yml`
  jobs, and `LEGACY_RUNS_ON` was re-recorded.** The pinned baseline was the
  pre-TIN-3902 expression set, in which the three utility jobs were literal
  `ubuntu-latest`; it is now the post-TIN-3914 label-only routing. What the pin
  proves is unchanged and is the whole point: `runner_group` stays default-off,
  rendering byte-identically over the scenario grid with the input unset. The
  literal-`runs-on` class is now empty, so the "a literal job never gains a
  group mapping" branch is kept executable by two new negative oracles against a
  **synthetic** baseline that declares one — the invariant stays proven rather
  than merely asserted, and a future literal-`runs-on` job lands on a tested
  rule. Job/class derivation is unchanged: nothing names `ubuntu-latest`.

- **TIN-3914: both `legacy_sha256` digests in
  `scripts/restricted-workflow-contract.rb` were re-recorded**, with the reason
  written at each pin. `spoke-ci.yml`
  `656e8c69…` → `a312785b…`; `spoke-lane-env.yml` `8e7e444f…` → `c238ab59…`.
  These digests are a tripwire on the **legacy** bytes so that adding or
  changing the restricted variant cannot silently move the shared lane — not a
  claim that the legacy files never change on purpose. The accompanying
  default-off proof is `just runner-group-contract-check`.

- **TIN-3914: `runner_mode`/`publish_mode`/label validation fails closed in
  every mode.** `js-bazel-package.yml`'s `resolve-runner` and its inline
  workflow-contract step now reject a GitHub-hosted label in
  `runner_labels_json` / `shared_runner_labels_json` in **all** modes, including
  `compat`, where labels were previously unvalidated. `runner_labels_json`'s
  declared default changes from `'["ubuntu-latest"]'` to `""`, resolving to
  `["tinyland-nix"]`; the `runner_mode=repo_owned` explicitness check now tests
  for an empty value instead of comparing against the retired hosted sentinel.

- **TIN-3914: `scripts/validate-ci-templates.py` forbids the hosted label
  families, not three `-latest` aliases.** `rust-bazel-application.yml`'s
  forbidden-snippet list was `ubuntu-latest` / `macos-latest` / `windows-latest`
  — which is why its own `runs-on: ubuntu-24.04` slipped past it. It is now
  `ubuntu-` / `macos-` / `windows-`, and the required snippet is
  `runs-on: tinyland-nix`. The deny-list gap is the smaller half of the story:
  `runs-on: ubuntu-24.04` was in the same file's **required**-snippet list, so
  the validator did not merely tolerate a GitHub-hosted runner, it *mandated*
  one and would have failed the build for removing it. "We required the thing
  we now forbid" is the strongest single argument for the MAJOR bump.

- **TIN-3900: `secrets-scan` gitleaks pin 8.21.2 → 8.30.1, so repo
  `[[allowlists]]` actually apply.** Gitleaks added the plural `[[allowlists]]`
  table in 8.25.0. `8.21.2` loads a config containing it without any error or
  warning and then **silently ignores every entry** — proven with a positive
  control: a `ghp_` literal in a path covered by an `[[allowlists]].paths` entry
  is reported by 8.21.2 (1 leak) and suppressed by 8.30.1 (0 leaks), while the
  same fixture with the allowlist removed is reported by both. Every Tinyland
  `.gitleaks.toml` — this repo's, `site.scaffold`'s, and every spoke spawned
  from it — uses `[[allowlists]]` exclusively, so no spoke allowlist has been in
  force in CI. `gitleaks-version` now defaults to `8.30.1` and `gitleaks-sha256`
  to `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`
  (`gitleaks_8.30.1_linux_x64.tar.gz`, from the release's
  `gitleaks_8.30.1_checksums.txt`). The download/verify/extract sequence, the
  reviewed step list, and the `detect --source . --report-format json` scan
  invocation are unchanged; `scripts/restricted-workflow-contract.rb` carries
  the matching `expected_scanner_defaults` and composite-document digest.

  **Spoke migration note.** Nothing to do if your `.gitleaks.toml` already uses
  only `[[allowlists]]` (the scaffold default) — your allowlists simply start
  being honored. Two checks otherwise:

  1. **Never mix singular and plural.** 8.30.x **fails closed** when a config
     declares both `[allowlist]` and `[[allowlists]]`:
     `Failed to load config error="[allowlist] is deprecated, it cannot be used
     alongside [[allowlists]]"`. If your spoke still has a lone `[allowlist]`,
     convert it to a single `[[allowlists]]` entry; do not keep both.
  2. **Re-check `.gitleaksignore`.** Fingerprints added to work around an
     allowlist that 8.21.2 was ignoring are now redundant. They stay harmless,
     but prune the ones an allowlist now covers so the ignore file documents
     only real, reviewed exceptions.

  Scanned clean under 8.30.1 with the action's exact invocation: this repo,
  `greatfallstoolbus.org`, `site.scaffold`, and the GFTB acceptance tree
  carrying the runtime-assembled `ghp_` fixture plus its `.gitleaksignore`.

## [2.14.0] — 2026-08-18

### Fixed

- **Rust+Bazel native jobs now own all local Bazel state** — the release-vendored
  driver binds `XDG_CACHE_HOME` and Bazel's `--output_user_root` to the fresh
  per-job root under `RUNNER_TEMP`. Persistent native runners can no longer
  inherit a user-level XDG cache or write action/output state into another
  job's Bazel tree.

### Added

- **Opt-in native Rust+Bazel application workflow** — add
  `rust-bazel-application.yml` and its dependency-free finite-target contract
  for the Prompt Pulse Bazel 9 canary. The workflow defaults disabled and takes
  a caller-supplied native Darwin/Linux matrix and Bazel platform facts. A
  hosted no-checkout/no-secret preflight rejects public and fork events, while
  its owner-group contract rejects hosted/repo-shaped native labels, wildcard
  targets, and invalid matrices before private-runner scheduling. Lane
  validation verifies tracked `.bazelversion`, Bzlmod, Cargo, and crate-universe
  lock authority and runs exact Bazel rustfmt, clippy, build, unit, integration,
  and package targets through immutable action references. GloriousFlywheel cache
  attachment is a second default-off input: read and write credentials are
  separate, pull requests can receive only server-enforced read authority, and
  write materialization additionally requires explicit caller approval, a push
  event, and GitHub's protected-ref signal on the configured main branch or
  release tag. All Bazel invocations ignore caller rc files, then apply the
  complete cache-only policy explicitly. Before caller checkout, a dedicated
  custody action validates an operator-projected, root-owned raw Bazelisk
  Nix-store path and refuses PATH, symlink, or mutable substitutes. Run-scoped
  Bazelisk state, an exact validated version, wrapper suppression,
  `.bazeliskrc` refusal, and scrubbing of every rules_rust 0.73
  repin/generator override prevent caller or cross-run binary/dependency
  substitution. Job-scoped XDG and Bazel output roots also prevent local
  action/output state from escaping into a persistent runner-user cache. No
  endpoint, package publish, or four-platform claim is baked into the template.

- **Opt-in tokenless Attic read degrade** — `nix-setup`, `nix-build`, and
  `greedy-cache` previously gated the Attic substituter
  (`extra-substituters` / `extra-trusted-public-keys`) on `ATTIC_TOKEN`
  being present, so a tokenless consumer got zero substituter and silently
  ate a 100% cache miss. New input `attic-public-read` on all three,
  **default `"false"`** — with it unset, execution is byte-identical to the
  pre-existing behavior (rule 2, `AGENTS.md`): no fallback endpoint, no new
  `nix.conf` writes, no new env exports, no new warnings beyond the
  pre-existing ones.

  Set `attic-public-read: "true"` to opt in: when no `attic-server` input
  and no auto-detected `ATTIC_SERVER` resolves, `nix-setup` falls back to
  the tinyland-inc public-read `main` cache
  (`https://nix-cache.tinyland.dev`,
  `main:eaUydxuDu7xBoy5cCo3MdknYAkVyTIASQ7DGuwxa+XA=`) and configures it as
  an anonymous, tokenless, **read-only** substituter — this fallback never
  exports `ATTIC_SERVER`, so it cannot flip `nix-build`'s
  token+server-gated push step from skipped to firing for a spoke that has
  `ATTIC_TOKEN` set but no configured push destination. The new
  `attic-public-key` input (also default `""` on all three) lets a caller
  pin a key for their own tenant `attic-server` under the same opt-in; the
  baked tinyland-inc key is only ever used for the tinyland-inc default
  itself, never baked in for an arbitrary server. `ATTIC_TOKEN` continues
  to gate the authenticated push/login half exactly as before in
  `nix-build` and `greedy-cache`; absent, under the opt-in, with a
  read-only substituter actually configured, both emit a loud
  `::warning::Attic token absent — anonymous public read only, pushes
  disabled` (skipped when the caller passed `push-cache: false`) instead of
  a hard failure or a silent no-op.

### Removed

- **TIN-489: zero-caller TTL half of the deprecated lane family evicted from
  `main`** — `spoke-lane-ttl-reap.yml`, the `lane-ttl-reap` composite action,
  and `schemas/lane-ttl-reap-dispatch.schema.json` (the composite was its only
  consumer; GFTB, transfemme-tailoring, and blahaj vendor their own copies).
  Estate-wide code search (tinyland-inc + Jesssullivan + Great-Falls-Tool-Bus,
  positive-controlled against known `spoke-ci.yml` callers) found zero
  workflow callers for any of the three; the blahaj receiver they dispatched
  to was already evicted (blahaj #1255). Released tags retain the files, so
  pinned callers are unaffected. **Kept on `main`**: `spoke-lane-env.yml`,
  `spoke-lane-env-restricted.yml`, `lane-dispatch`, `lane-reap` —
  `darkmap.phasi.space` still calls `spoke-lane-env.yml@v2` (a moving major
  tag), so evicting that half before the spoke-side sender cleanup would break
  it at the next `v2` re-point. Do not re-point `v2` past a future eviction of
  that half until the darkmap sender is retired.

### Fixed

- **`spoke-lane-env` default-off digest re-recorded (TIN-3903)** — the
  TIN-489 deprecation banner added to `.github/workflows/spoke-lane-env.yml`
  (#122) changed the file's bytes without re-pinning
  `SPECS["spoke-lane-env"][:legacy_sha256]` in
  `scripts/restricted-workflow-contract.rb`, so `just check` failed on a clean
  `main` with `legacy workflow bytes changed (8e7e444f…); default-off proof
  invalid` — a fleet-wide gate, not a local one. Re-recorded the pin
  `759ebf6d…` → `8e7e444f…`. The #122 edit is six leading `#` comment lines
  and nothing else: the diff of both revisions with comment and blank lines
  stripped is empty (157 significant lines on each side), and the parsed YAML
  documents compare equal — identical `on:` / `workflow_call` inputs and
  secrets, `permissions`, `concurrency`, the same six jobs in the same order,
  and byte-identical `if:` guards. The default-off proof the digest anchors is
  therefore unchanged; only the bytes it is taken over moved. The `spoke-ci`
  pin was verified still current and is untouched.

## [2.13.0] — 2026-08-06

### Deprecated

- **Docs-only (TIN-489): PR-env producer routing points at the owner overlay** —
  `spoke-lane-env.yml` and `spoke-lane-env-restricted.yml` now carry
  DEPRECATED headers; the README quick start, composite-action and workflow
  tables, `docs/migration-v0-to-v1.md`, and `docs/restricted-private-runners.md`
  mark the Blahaj-dispatch PR-env path retired-era. The PR-env lifecycle
  producer is the product's owner-overlay repository — see site.scaffold
  `docs/patterns/owner-overlay-apply-plane.md`. The vendored
  `schemas/blahaj-dispatch.schema.json`,
  `schemas/lane-ttl-reap-dispatch.schema.json`, and
  `schemas/public-preview-dispatch.schema.json` are marked retired-era
  historical artifacts (the scaffold #119 recut deleted their upstream
  sources): each schema's top-level `description` now opens with a
  RETIRED-ERA HISTORICAL ARTIFACT note pointing at the owner-overlay
  producer (`description` is a non-validating annotation, so validation
  behavior is unchanged). The "pending scaffold #119 recut" phrasing is
  corrected repo-wide: #119 merged 2026-08-06 (`8862f359`). Zero
  behavioral diff: released action/workflow behavior is untouched and
  everything stays callable.

- **Docs-only (TIN-3066): blahaj receiver path marked retired-era** — README,
  the `lane-dispatch` / `lane-reap` / `lane-ttl-reap` / `public-preview-dispatch`
  action descriptions, the `spoke-lane-env` / `spoke-lane-ttl-reap` /
  `spoke-public-preview` workflow headers, `docs/roadmap.md`, and
  `docs/spec/dev-remote.md` now carry a Superseded (2026-08-05) banner: the
  blahaj receiver path was evicted (blahaj #1255); lane lifecycle belongs to
  the app owner overlay — see site.scaffold
  `docs/patterns/owner-overlay-apply-plane.md` and the scaffold #119 recut
  (merged 2026-08-06, `8862f359`). Zero behavioral diff: released
  action/workflow behavior is untouched (spokes pin immutable tags); the
  behavior recut ships via the versioned release train.

## [2.12.2] — 2026-08-04

### Fixed

- **`gf-credhelper-install` authenticated asset supply path (TIN-3066)** — the
  action fetched the release binary from the public
  `github.com/<repo>/releases/download/...` URL, which 404s unconditionally now
  that `tinyland-inc/GloriousFlywheel` is private, breaking every consumer of
  the non-Nix credhelper distribution channel. A new optional `token` input
  resolves the asset by name through `GET /repos/{repo}/releases/tags/{tag}`
  and downloads it from the per-asset REST endpoint with
  `Accept: application/octet-stream`. The public path is byte-for-byte
  unchanged when no token is supplied, and both paths still sha256-verify the
  fetched bytes against the caller-supplied pin before `chmod`/PATH exposure.

## [2.12.1] — 2026-07-31

### Fixed

- **Restricted workflow transitive immutability (TIN-3209)** — close the full
  `spoke-ci-restricted.yml` / `spoke-lane-env-restricted.yml` dependency graph:
  self-actions use exact `v2.12.1` refs, verified `actions/checkout` v6.1.0 and
  Determinate Nix use full commit SHAs, the cache attachment contract runs from
  a release-vendored composite, and TruffleHog/Gitleaks release archives are
  downloaded without pipe-to-shell and SHA-256 verified before exact-member
  extraction. The offline restricted-workflow validator now traverses and pins
  the exact action closure, proves the cache composite's exact input/env/path/
  label-export/strict-execution sequence, and permits only one exact scanner
  download/checksum/extract/install sequence. Negative controls reject missing,
  conditional, alternate, duplicate, decoupled, or reordered execution paths.

## [2.12.0] — 2026-07-31

### Added

- **Default-off private-group spoke workflows (TIN-3209)** — add
  `spoke-ci-restricted.yml` and `spoke-lane-env-restricted.yml` as explicit
  private-repository opt-ins. Every directly defined job uses a required owner
  `-infra` runner group plus an exact reviewed capability label; fork and
  untrusted `pull_request_target` execution is rejected before checkout. The
  job-level pre-scheduling condition also admits only the reviewed
  `tinyland-infra` group and exact role labels, so Default/shared/hosted/wrong
  caller routes skip before any runner assignment. The
  original spoke workflows are checksum-pinned byte-for-byte, so existing
  consumers remain unchanged. The operator guide records the owner-overlay →
  immutable ci-templates release → pinned app-caller sequence and makes clear
  that source intent is not live runner-group proof or application authority.

### Fixed

- **No implicit hosted release jobs (TIN-3209)** — retire the repository-local
  PR/main release workflow and stop `npm-publish.yml` from auto-running on
  ci-templates tags or manual dispatch. Immutable library releases are now an
  attended signed-tag/GitHub-release transaction; the existing hosted npm
  workflow remains callable only by already pinned consumers.

- **Structured `runs-on` linting** — teach `lint-runs-on.rb` to inspect GitHub's
  `{group, labels}` form as a mapping, reject missing/generic groups and hosted
  labels inside group mappings, hard-fail forbidden literal fallbacks such as
  `inputs.runner_group || 'Default'`, and retain fail-closed capability-label
  checks instead of stringifying the mapping.

## [2.11.0] — 2026-07-10

### Added

- **`gf-credhelper-install` composite action** — installs the released
  `gf-reapi-credhelper` binary for the current runner platform from a pinned
  GloriousFlywheel release, verifies a caller-supplied SHA-256 before the binary
  reaches `PATH`, and exports `GF_REAPI_CREDENTIAL_HELPER_BIN` for
  `flywheel-github-oidc-profile.sh` plus the compatibility alias
  `GF_REAPI_CREDENTIAL_HELPER`. This is the reusable non-Nix consumer surface
  for the TIN-2724 enforce-cell `:8980` proof path.

- **`authorities.artifact_registry` manifest key** — new optional string
  authority in `schemas/tinyland-repo-manifest.schema.json`, distinct from
  `authorities.package_registry`. `package_registry` keeps its Bzlmod
  source-dependency-registry meaning (`tinyland-inc/bazel-registry`);
  `artifact_registry` names the published-artifact serving/gating surface (the
  Pulp registry — signed, versioned RELEASE artifacts over dnf/podman/https).
  Additive + optional (manifests without it still validate); resolves the
  long-standing `package_registry` naming overload before any consumer sets a
  value. Anchors the Cordillera registry charter (TIN-2718). The value lands
  separately in `rockies/tinyland.repo.json`.

### Fixed

- **Org-namespaced Flywheel runner guards** — `flywheel-bazel` and the
  cache-attachment contract now consume the same TIN-2353 runner-class grammar
  as `nix-setup` / `lanes.schema.json`, so tenant pools such as
  `great-falls-tool-bus-nix` and `medical-massage-specialists-docker` are
  treated as real cluster classes instead of being rejected by stale
  tinyland-only downstream guards.

- **Cloudflare Pages wrapper docs** — the consumer example now matches the
  first live downstream adoption (GFTB PR #28): callers pass job-level
  `contents: read` / `deployments: write`, use `secrets: inherit`, and do not
  duplicate the reusable workflow's `cloudflare-pages-${{ github.ref }}`
  concurrency group. Duplicating that group deadlocks the caller against the
  called `deploy` job before any build step runs.

## [2.10.0] — 2026-07-03

### Added

- **`spoke-deploy-cloudflare-pages.yml` reusable workflow** — a sanctioned,
  opt-in Cloudflare Pages deploy lane that DRYs the hand-rolled CF-Pages
  publisher copied into ≥3 spokes: GFTB `greatfallstoolbus.org`
  (`.github/workflows/deploy-pages.yml`), `transscendsurvival.org`
  (`cloudflare-pages-shadow.yml`), and the `site.scaffold`
  `docs/deploy/cloudflare-pages.md` template block. It builds the adapter-static
  `build/` via `nix develop --command just setup/check/build` (with
  `setup_command` / `check_command` / `build_command` inputs defaulting to
  `just setup` / `just check` / `just build`), exposes declared host
  `node_version` / `pnpm_version` inputs for the Cloudflare action environment,
  resolves `project_name`
  (input; defaults to the slugified repo name) and the deploy branch (from
  `github.head_ref || github.ref_name`, lowercased/sanitized), credential-skips
  with a `::notice::` when `CLOUDFLARE_API_TOKEN` / `CLOUDFLARE_ACCOUNT_ID` are
  absent, and never deploys or mutates on PR events. `secrets:` are declared
  `required: false`; `permissions:` are `contents: read` + `deployments: write`.
  This is the CF-Pages opt-in — it does **not** replace the scaffold default
  GitHub-Pages lane. GFTB and transscendsurvival can adopt it in follow-ups by
  collapsing their inline copies into a thin `uses:` wrapper.

## [2.9.1] — 2026-07-03

### Added

- **`flywheel-reapi-proof` pending-cancel retry** — callers may opt into
  `retry_cancelled_before_start: true` (with `max_attempts`, default `3`) so a
  GF proof dispatch cancelled before GitHub assigns a job can be retried with a
  fresh request id. This targets GitHub Actions concurrency pending-slot eviction
  only; existing callers are byte-identical unless they opt in.

## [2.9.0] — 2026-07-02

### Added

- **`heavy_runner_class` / `kvm_runner_class` spoke-ci inputs** — the `bazel-graph`
  and `playwright` jobs hard-coded `tinyland-nix-heavy` / `tinyland-nix-kvm`, labels
  only the tinyland-inc pool publishes. Org-scope ARC tenancies riding the TIN-2299
  sense-3 overlay serve a single capability label (e.g. Great-Falls-Tool-Bus serves
  only `tinyland-nix`), so both jobs queued forever on any spoke in such an org
  (observed live: greatfallstoolbus.org PR #2, run 28607136454). Two new optional
  inputs default to the previous hard-coded values — pinned consumers are
  byte-identical until they opt in.

## [2.8.0] — 2026-06-30

### Added

- **`scaffold_tag` in the repo-manifest schema (TIN-2229)** — optional, additive
  top-level string property recording the `site.scaffold` release tag a repo was
  spawned from. `site.scaffold`'s `rebrand.sh` stamps it; `tinyland-scaffold-doctor`
  Layer 2 reads it for the version-drift diff. Backward-compatible — manifests without
  it still validate. The floating `@v2` tag needs a new `v2.x` release to ship it.

### Fixed

- **Release workflow floating-major tag movement** — release automation now
  captures the current remote `vMAJOR` tag object before retagging and pushes the
  floating major tag with an explicit lease. This prevents the partial-release
  failure seen during `v2.7.0`, where the immutable tag was created but moving
  `v2` failed with stale tag state.

## [2.7.0] — 2026-06-23

### Added

- **Flywheel profile-state propagation for cache-backed enrollment (TIN-2130)** —
  cache-backed `js-bazel-package.yml` and `spoke-ci.yml` lanes now export
  `GF_FLYWHEEL_PROFILE_STATE` from the manifest-driven substrate mode, and the
  fail-closed cache attachment contract rejects contradictory profile states.
  This gives consumer `flywheel-doctor` / `flywheel-verify` tooling the same
  machine-readable attachment state as CI without minting tokens or changing the
  cache-first/no-executor boundary.

### Fixed

- **Flywheel advertised-path executor config for fresh-repo proofs
  (TIN-2162)** — the `flywheel-executor` template now forces remote executor
  mode without exposing a consumer-visible platform repository, and release
  validation asserts the template stays executor-backed. This keeps
  enroll/doctor/verify consumers on the advertised GloriousFlywheel path instead
  of requiring repo-local Bazel platform wiring.

## [2.6.0] — 2026-06-14

### Added

- **Opt-in shared-cache enrollment gate for `spoke-ci.yml` (TIN-2119)** — the
  SvelteKit spoke wrapper gains two operator inputs, `cache_backed` (boolean,
  default `false`) and `substrate_mode` (string, default `""`), plus a
  `cache_backed_targets` input (default the SvelteKit flywheel-eligible CAS
  surface `//:node_modules //:sveltekit_types //:svelte_check_test`). When
  `cache_backed=true`, the `flywheel-build` and `bazel-graph` jobs additionally:
  (a) switch their Nix setup from `setup-nix@v2` (install-only) to
  `nix-setup@v2`, which probes cluster DNS and exports `BAZEL_REMOTE_CACHE` /
  `ATTIC_SERVER` — the spoke wiring fix, since `setup-nix` does not export the
  cache endpoint; (b) validate `tinyland.repo.json` via `repo-manifest-validate@v2`
  and assert shared-cache attachment with the reused
  `scripts/cache-attachment-contract.sh --strict` (manifest-driven expected mode
  `enrollment.substrateMode` > `substrate_mode` input > `shared-cache-backed`
  default; fail-closed on missing/invalid endpoint, non-grpc/http scheme, and
  hosted / repo-shaped runner fallback); and (c) run a cache-backed Bazel build
  of the flywheel-eligible targets with
  `--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
  --remote_upload_local_results=false`, reading the shared Bazel cache.
  CACHE-FIRST only (TIN-1997 Option D): no remote executor is wired. The default
  path (`cache_backed=false`) is byte-identical for the ~34 non-opted spoke
  consumers — all new steps are conditional and the existing setup/build steps are
  unchanged. Reuses the v2.5.1 contract, manifest schema, validator, and
  hosted-runner rejection verbatim (no fork). An opted spoke must also set
  `flywheel_config: flywheel` so `flywheel-bazel` forwards the remote cache.

## [2.5.1] — 2026-06-14

### Fixed

- **`repo-manifest-validate` runs without `jsonschema` or `nix` (TIN-2109)** —
  the action now validates via a bundled, dependency-free stdlib validator
  (`scripts/manifest-schema-validate.py`) that prefers the authoritative
  `jsonschema` package when importable and otherwise falls back to a faithful
  JSON-Schema-2020-12 subset validator. The previous `nix develop --command
  python3` fallback failed on nix self-hosted cluster runners (a cold
  `nix develop` hits an `opening lock file ".../big-lock": Permission denied`),
  which made the v2.5.0 cache-backed manifest-validation gate fail closed for the
  wrong reason. No network; fail-closed semantics unchanged.

## [2.5.0] — 2026-06-14

### Added

- **First-class enrollment manifest fields (TIN-2109)** —
  `schemas/tinyland-repo-manifest.schema.json` gains an optional, additive
  `enrollment` object promoting the four GloriousFlywheel enrollment dimensions
  (`forgeScope`, `operatorOverlay`, `executionPool`, `substrateMode`) from
  `supply_chain.sbom.notes` prose to validated fields. `substrateMode` is an enum
  (`compatibility-local-only` | `shared-cache-backed` | `executor-backed`). The
  object is back-compatible: existing manifests without it still validate, and it
  is not globally required.
- **Manifest-driven, fail-closed enrollment gate (TIN-2109)** — when
  `cache_backed: true`, `js-bazel-package.yml` now (1) validates the consumer's
  `tinyland.repo.json` against the vendored schema and **fails closed** on an
  invalid manifest; (2) reads `enrollment.substrateMode` as the **authoritative**
  expected mode fed to `cache-attachment-contract.sh --strict` (a manifest
  declaring `shared-cache-backed` while no cache attaches fails closed, instead
  of the previous hard-coded workflow default); and (3) feeds the runner labels
  so the contract **rejects hosted (`ubuntu-*`) / bare `self-hosted` /
  repo-shaped (`<name>-nix*`) runner fallback** — a missing substrate is a
  deterministic failure, never a silent degrade to a GitHub-hosted build. All new
  steps live inside the opt-in `cache_backed` path; the default
  `bazelisk build … --verbose_failures` step is byte-identical for non-opted
  consumers.
- **`substrate_mode` workflow input** — optional operator override for the
  cache-backed lane's expected mode, used only when the consumer manifest does
  not declare `enrollment.substrateMode` (which remains authoritative). No effect
  on the default path.
- **Executor-backed contract DEFINED + ENFORCED (cache-first, never selected)** —
  `scripts/cache-attachment-contract.sh` now requires the full executor contract
  (remote executor endpoint + `BAZEL_REMOTE_CACHE` + a cluster runner class for
  platform identity + a digest-pinned REAPI proof image via
  `GF_BAZEL_REAPI_PROOF_IMAGE_DIGEST`) whenever the declared/effective mode is
  `executor-backed`, failing closed if any piece is missing. No current repo
  selects executor-backed (TIN-1997 Option D / cache-first); the contract is
  defined so the gate is enforceable the moment a repo declares it. The workflow
  remains executor-free (no `--remote_executor` / `BAZEL_REMOTE_EXECUTOR` /
  `--config=executor-backed`), keeping the `cache-backed-optin-contract` guard
  green.

### Changed

- **Pinned the cache-attachment-contract fetch fallback** in
  `js-bazel-package.yml` from the floating `CI_TEMPLATES_REF=v2` major tag to the
  immutable releasing tag `v2.5.0`, so pure-consumer spokes that have not
  vendored the script get a reproducible fetch.
- **`just check` / `validate-ci-templates.py cache-backed-optin-contract`** now
  additionally asserts the manifest-validation step, manifest-driven expected
  mode, runner-label rejection wiring, the pinned (non-floating) fetch fallback,
  and the contract script's hosted-runner + executor-backed enforcement.

## [2.4.0] — 2026-06-14

### Added

- **`lint-runs-on` composite action + `scripts/lint-runs-on.rb` runs-on guard** —
  a portable, Ruby-only (zero Python/PyYAML/nix) author-time guard that fails any
  workflow `runs-on` using a repo-shaped / project-identity self-hosted label
  (e.g. `jesssullivan-nix-heavy`, `chapel-nix`), bare `self-hosted`, or drift
  baked into a `fromJSON()` fallback — while passing shared `tinyland-*`
  capability labels, GitHub-hosted labels, and runtime-dynamic indirection
  (which WARNs, never FAILs). Adopt with one line:
  `- uses: tinyland-inc/ci-templates/.github/actions/lint-runs-on@v2` (after
  `actions/checkout`). The label taxonomy (`scripts/runner_label_taxonomy.rb`)
  is a faithful, self-test-pinned port of GloriousFlywheel
  `scripts/validate-arc-runner-taxonomy.py::label_errors()`; the guard is the
  first semantic workflow-yaml lint in the repo and is wired into `just check`
  (`lint-runs-on-selftest` + `lint-runs-on-check`). First guardrail of the
  GloriousFlywheel enrollment paradigm (P0 #2 — kills the `runs-on: <repo>-nix`
  mistake at author time). (Landed just after the v2.3.0 cut.)

## [2.3.0] — 2026-06-14

### Added

- **`js-bazel-package.yml` opt-in `cache_backed` shared-cache lane (TIN-2110)** —
  a new boolean input (default `false`). When `true`, Bazel target validation
  runs a fail-closed cache-attachment contract step and then
  `--config=ci-cached --remote_cache=$BAZEL_REMOTE_CACHE
  --remote_upload_local_results=false`, reading the shared Bazel cache
  (cache-first, TIN-1997 Option D / GF#889). When `false`/unset the existing
  `bazelisk build … --verbose_failures` path runs **byte-identically** — zero
  behavior change for the ~190 non-opted consumers. The lane is cache-first only
  and never wires a remote executor.
- **`scripts/cache-attachment-contract.sh`** — shared fail-closed classifier
  generalized from MassageIthaca, aligned to TIN-2108 naming
  (`GF_BAZEL_SUBSTRATE_MODE`; modes `compatibility-local-only` /
  `shared-cache-backed` / `executor-backed`). Rejects unexpanded `${...}`
  placeholders, non-`grpc`/`http` endpoints, localhost without explicit proof,
  executor-without-cache, and executor≠cache mismatches.
- **`bazelrc/ci-cached.bazelrc`** — endpoint-free `--config=ci-cached`,
  `cache-readonly`, and `no-remote-cache` behavior for consumer `.bazelrc`
  files; read-only by default and never executor-selecting.
- **`AGENTS.md`** — agent/operator guide documenting the shared-surface golden
  rules and the cache-first Bazel enrollment doctrine (closes the missing-AGENTS
  AX gap).
- **`just ci-cached-endpoint-free-check` + `just cache-backed-optin-contract-check`**
  — repo-local guards asserting `bazelrc/ci-cached.bazelrc` stays endpoint-free
  and the `cache_backed` lane stays default-off and cache-first (no executor
  wiring in the workflow).

## [2.2.1] — 2026-06-01

### Fixed

- **`secrets-scan` installs both scanners to a job-writable dir** — the v2.2.0
  TruffleHog binary install (and the pre-existing gitleaks install) wrote to
  `/usr/local/bin`, which is not writable by the runner user on the nix
  self-hosted pool (`install: cannot create regular file ...: Permission
  denied`). Both now install into `$RUNNER_TEMP/secrets-scan-bin` and prepend
  it to `$GITHUB_PATH`. The gitleaks write was latently broken on these runners
  too — it just never ran because the Docker-based TruffleHog step failed first.

## [2.2.0] — 2026-06-01

### Changed

- **`secrets-scan` runs TruffleHog as a pinned binary, not a Docker action** —
  `trufflesecurity/trufflehog@main` is a container action and fails on
  Docker-less self-hosted runners ("failed to connect to the docker API at
  unix:///var/run/docker.sock"), e.g. the tinyland nix compute pool, taking the
  whole `secrets-scan` lane (and its downstream `needs:` jobs) red. The action
  now installs a pinned `trufflehog` binary (new optional `trufflehog-version`
  input, default `3.95.3`) and scans git history directly, mirroring the
  gitleaks binary install in the same action. The gitleaks half and the
  `findings_count` output are unchanged.

## [2.1.0] — 2026-06-01

### Changed

- **`js-bazel-package.yml` npmjs policy is explicit** — adds
  `npm_publish_mode=required|optional|disabled`. The default remains
  `required` for existing consumers, while Bazel-first packages can make
  npmjs best-effort or disabled when GitHub Packages and the Tinyland Bazel
  registry are the release authority.
- **`js-bazel-package.yml` shared runner labels are guarded** —
  `runner_mode=shared` now rejects an explicitly empty
  `shared_runner_labels_json`, catching missing caller repo variables before the
  workflow silently falls back to the default shared runner class.
- **`js-bazel-package.yml` repo-owned mode uses capability labels** —
  `runner_mode=repo_owned` now requires explicit runner labels that include a
  Tinyland capability class, and docs clarify that repo ownership is a
  registration/trust boundary rather than permission to mint repo-shaped labels.
- **`flywheel-reapi-proof` run correlation is request-id based** — the
  composite now dispatches GloriousFlywheel proof runs with a unique request
  id and resolves the matching child run by run name instead of timestamp-only
  "latest run" selection, so concurrent browser/RBE proof requests cannot watch
  a sibling run.

## [2.0.0] — 2026-05-20

### Added

- **`inherit-scaffold-skills` composite** — pulls
  `plugins/scaffold-core` from `tinyland-inc/site.scaffold` at a pinned tag or
  commit SHA, dereferences skill symlinks, and can materialize
  `.agents/skills` plus `.claude/skills` in consumer spokes. Branch refs such
  as `main` are rejected by default so inherited AX contracts do not drift
  silently.
- **v1 to v2 migration guide** — documents endpoint-free Flywheel behavior,
  scaffold skills inheritance, v2 internal refs, and rollback posture.
- **`public-preview-dispatch` composite + `spoke-public-preview.yml`** —
  reusable dispatch path for explicit public/client review aliases. The payload
  is schema-validated and carries source repo, PR, commit, lane, origin host,
  preview hostname, TTL, and Cloudflare Access allowlist. Spokes request the
  alias; Blahaj owns DNS, Access, Tunnel ingress, and cleanup.
- **`lane-ttl-reap` composite + `spoke-lane-ttl-reap.yml`** — reusable
  scheduled TTL backstop dispatcher. Blahaj owns listing and idempotent
  destruction of expired lane environments.
- **`flywheel-reapi-proof` composite** — reusable dispatcher for
  GloriousFlywheel executor-backed proof workflows. The composite does not
  promote target classes by itself; GF proof artifacts remain authoritative.
- **Public preview and TTL reap schemas** — vendored from the site.scaffold
  contract alongside the existing lane schemas.
- **`repo-manifest-validate` composite + repo manifest schema** — reusable
  validation for `tinyland.repo.json`, including optional role gating such as
  `static-spoke,static-spoke-scaffold`.
- **Repo-local validation contract** — adds `Justfile`, `flake.nix`, and
  `tinyland.repo.json` so this template repo can validate itself the same way
  consuming repos do. `just check` now parses workflow/action YAML, parses
  vendored schemas, validates the repo manifest, checks v2 internal refs, and
  enforces endpoint-free Flywheel defaults plus the canonical Tinyland gitleaks
  working-tree scan.

### Changed

- **Flywheel Bazel binding is endpoint-free** — `bazelrc/flywheel.bazelrc`
  no longer hard-codes `remote_cache`, `remote_executor`, or cache upload
  authority. `flywheel-bazel` now passes `--remote_cache` and
  `--remote_executor` from runtime env/action inputs and fails fast when the
  required endpoint is absent.
- **Reusable workflow internal refs target v2** — v2 workflows and nested
  composites call sibling ci-templates actions through `@v2`, not `@v1`, so a
  `spoke-ci.yml@v2.0.0` consumer receives the endpoint-free Flywheel and
  manifest-validation behavior from the same major release.
- **Internal action refs no longer use `@main`** — nested ci-templates action
  calls now use the current floating major tag, and consumer docs point at
  immutable release tags.
- **Schema validators can fall back to the consumer Nix dev shell** —
  `lanes-load` and `repo-manifest-validate` use host Python when `jsonschema`
  is available and otherwise route through `nix develop --command python3`.
- **`spoke-ci.yml` now validates repo manifests when present** — pre-manifest
  consumers continue with a notice; repos that ship `tinyland.repo.json` must
  declare `static-spoke` or `static-spoke-scaffold` for the spoke workflow.
- **Release PRs may carry an empty Unreleased section** — `release: vX.Y.Z`
  PRs are allowed through the changelog gate when branch protection blocks the
  workflow-driven direct push release path.

### Fixed (v1.1.5)

- **`lane-status-check` composite — use `curl` instead of `gh api`** —
  the action posted per-lane commit statuses via `gh api`, which
  requires the GitHub CLI on the host PATH. On runners where `gh`
  only lives inside the spoke flake's devShell, the call failed with
  `gh: command not found` (exit 127) and turned successful builds
  into fake job failures. Surfaced by darkmap PR #86 / TIN-1414 —
  the `flywheel-build` step's underlying `bazelisk build` succeeded
  (`state: "success"` payload was even emitted), but the `gh api`
  POST that followed killed the job.
  Fix: replaced `gh api` with `curl -X POST` calling the same
  `/repos/{owner}/{repo}/statuses/{sha}` endpoint directly. `curl`
  is ubiquitous on Linux runners and doesn't need a flake devShell.
  Also bumped the `lane-status-check@v1.0.0` pin in `spoke-ci.yml`
  to `@v1.1.5`.

### Fixed (v1.1.4)

- **`flywheel-bazel` composite — route bazelisk through `nix develop`
  when not on host PATH** — the action invoked `bazelisk` directly,
  assuming it lives on the runner's system PATH. On runners that
  declare bazelisk inside the spoke flake's devShell (the Tinyland
  default — every spoke flake adds `bazelisk` to `buildInputs`), the
  bare invocation failed with `bazelisk: command not found` in ~1
  second. Surfaced by darkmap PR #86 / TIN-1407.
  Fix: probe `command -v bazelisk`; if found, invoke directly
  (backward-compatible for runner images that preinstall bazelisk
  system-wide). If absent and `flake.nix` is present, route the call
  via `nix develop --command bazelisk ...`. If neither path is
  available, fail loudly with a clear error.
  Also bumped the `flywheel-bazel@v1.0.0` pin in `spoke-ci.yml` to
  `@v1.1.4` so the wrapper workflow picks up the new behavior.

### Fixed (v1.1.3)

- **`setup-nix` composite — ensure `nixbld` group/users + start the
  daemon if needed** — v1.1.2 introduced `setup-nix` but only handled
  install/detect/feature-flags. On Tinyland self-hosted runners the
  daemon socket wasn't reachable, so `nix develop` fell back to direct
  DB access and the runner user got `error: opening lock file "/nix/var/nix/db/big-lock": Permission denied`.
  Surfaced by darkmap PR #86 (the symptom that v1.1.2 was supposed to
  fix re-appeared at the next step).
  Fix: added the missing pair of steps from
  `GloriousFlywheel/.github/actions/nix-job`:
    1. Create the `nixbld` group and `nixbld1..nixbld32` build users if
       absent (multi-user nix prerequisite).
    2. `nix store ping`; if it fails, `sudo -b $(command -v determinate-nixd) daemon`
       (or `nix-daemon --daemon` as fallback) and wait up to 15 s for
       the socket to come up.
  No behavior change for callers — same workflow inputs, same actions
  block in spoke-ci.yml + spoke-lane-env.yml. Ships as v1.1.3.

### Added

- **`.github/actions/setup-nix/action.yml`** — new composite action that
  detects an existing Nix installation (probes
  `/nix/var/nix/profiles/default/bin` + `$HOME/.nix-profile/bin`,
  then `command -v nix`). When Nix is preinstalled, adds it to PATH
  and writes a per-user `~/.config/nix/nix.conf` with the requested
  flags. When absent, falls through to
  `DeterminateSystems/determinate-nix-action@v3`. Replaces all 8 use
  sites of `cachix/install-nix-action@v31` in `spoke-ci.yml` (5) and
  `spoke-lane-env.yml` (3).

### Fixed

- **All cachix/install-nix-action call sites** — the cachix action
  aborts hard with `Aborting: Nix is already installed at /nix/var/nix/profiles/default/bin/nix`
  on self-hosted runners that have Nix preinstalled (the case for
  the Tinyland `tinyland-nix*` runner classes). Subsequent
  `nix develop` then failed with `error: opening lock file "/nix/var/nix/db/big-lock": Permission denied`
  because the runner user wasn't granted access to the daemon
  database that the preinstalled multi-user nix relied on.
  Surfaced by darkmap PR #86 / TIN-1402 (every flywheel-build and
  flywheel-test matrix job failed in ~9 seconds).
  Fix: route all callers through the new `setup-nix` composite,
  which handles both the preinstalled-nix case and the
  no-nix-installed case uniformly.

### Fixed

- **`spoke-ci.yml` — strip literal `${{ ... }}` expressions from
  `inputs.runner_labels_json.description`** — GitHub evaluates
  `${{...}}` inside workflow-level `description:` text at PARSE time
  and rejects expressions that reference contexts not available there
  (`vars`, `secrets`, etc.). v1.1.0 shipped two example expressions
  inside the description, which caused every caller to fail in 0
  seconds with no jobs created. Replaced the embedded expressions with
  plain-text guidance pointing to the README / release notes.
- **`spoke-lane-env.yml` — remove invalid `if-skip:` job key on
  `tailnet-qa`** — `if-skip` is not a valid GitHub Actions keyword.
  Workflow parser rejects with `unexpected key "if-skip" for "job"
  section`. The step-level `if: matrix.lane.e2e` on line 164 already
  handles per-lane gating.

Both bugs surfaced during darkmap M3-completion PR #86 (TIN-1398).
Together they made v1.1.0 unusable for any spoke that calls
`spoke-ci.yml@v1.1.0` or `spoke-lane-env.yml@v1.1.0` directly. Ships
as v1.1.1.

### Changed

- **`spoke-lane-env.yml` — `BLAHAJ_DISPATCH_TOKEN: required: false`** —
  loosen the secret contract so spokes can keep the `pull_request:`
  trigger enabled before Blahaj is installed on the repo. New
  internal `check-blahaj-token` job runs first and gates every
  downstream job's `if:` on token presence — empty token = whole
  pipeline skips cleanly with a `::notice::`, NOT a workflow-file
  parse failure.

  Surfaced by darkmap M6 validation
  ([test PR #82](https://github.com/Jesssullivan/darkmap.tinyland.dev/pull/82)):
  GitHub resolves required secrets at workflow-call PARSE time,
  before the job-level `if:` evaluates. So `required: true` +
  empty caller secret = parse-time failure, and the gate never gets
  a chance to short-circuit. Reversing to `required: false` lets the
  job-level gate actually do its job. Backward-compatible: callers
  that DO have the secret continue to work identically.

### Added

- **`spoke-ci.yml` — new `runner_labels_json` optional input** —
  JSON-array expression evaluated via `fromJSON()` to set the
  per-lane matrix jobs' `runs-on`. When set (non-empty), takes
  precedence over `matrix.lane.runner_class` and
  `default_runner_class`.

  Enables spokes with dynamic runner-class fallback (e.g.
  `runs-on: ${{ fromJSON(vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '["ubuntu-latest"]') }}`)
  to adopt the `spoke-ci.yml` wrapper without losing graceful
  degradation when cluster labels aren't reachable.

  Surfaced by darkmap M3 partial (TIN-1384). Without this input,
  spokes with their own runner-routing logic (darkmap, MassageIthaca)
  couldn't replace their hand-rolled `ci.yml` with the wrapper.
  Now they can. Backward-compatible: existing callers that leave
  this unset see no behavior change.

## [1.0.1] — 2026-05-18

### Changed

- **`RELEASING.md` § Release flow** — documented the manual-tag
  fallback (step 3b) for environments where the workflow-driven
  release path (step 3a) doesn't hold. Specifically:
  - Local agent safety hooks blocking direct push to `main` and
    `release/*` branch patterns.
  - GitHub rebase-merge silently dropping empty commits — a
    `release: vX.Y.Z` empty commit landed via rebase-merge leaves
    `main` HEAD with a non-release subject, so `release.yml`'s
    `tag-on-release-commit` job never fires.
  Manual fallback cuts the immutable tag, moves the floating major
  tag, and creates the GH Release with the same CHANGELOG-extracted
  notes the automation would have produced. Surfaced during darkmap
  M1-M6 pilot (`Jesssullivan/darkmap.tinyland.dev` TIN-1381).

### Added

- **`docs/spec/dev-remote.md`** — full design spec for the v1.1+
  `lane-preview-tunnel` composite. Codifies the non-REAPI pathway
  (Blahaj K8s Deployment + tailscale-operator Service), the new
  `<spoke>-dev-env` event_type, the wire schema, lifecycle, auth
  model, and open questions to resolve before v1.1.0. Cross-linked
  from `docs/roadmap.md`. Doc-only — no behavior change.
- **`docs/release-checklist-v1.0.0.md`** — operator-facing
  step-by-step checklist for cutting the v1.0.0 release per
  `RELEASING.md`. Documents the merge → `release: v1.0.0` commit →
  `release.yml` auto-tag sequence, plus the companion-repo
  coordination (site.scaffold, GloriousFlywheel scoped tag,
  `.github` org ruleset application). Doc-only.

## [1.0.0] — 2026-05-17

First versioned release. All prior consumers were on `@main` and are
treated as v0.x retroactively (see `v0.4.0` below).

### Added

- **Workflow `release.yml`** — two-mode: on PR, assert `## [Unreleased]`
  is non-empty (forces CHANGELOG discipline); on push to `main`, if the
  head commit is `release: vX.Y.Z` then cut the immutable `vX.Y.Z` tag,
  move the floating `@vX` major tag, and create a GitHub Release with
  notes extracted from this CHANGELOG. Does NOT auto-tag arbitrary
  merges — matches the RELEASING.md flow.
- **Composite action `flywheel-bazel`** — wraps `bazelisk` with
  `--config=flywheel` (cache-only) or `--config=flywheel-executor`
  (cache + REAPI executor). Refuses executor mode on non-cluster runners.
  Ships embedded `bazelrc/flywheel.bazelrc`.
- **Composite action `lanes-load`** — reads + JSON-Schema-validates
  `.github/lanes.json`, outputs `lanes_json` (for matrix), `styles_json`,
  `lane_count`, `schema_version`, `spoke_name`, `spoke_domain`. Fixes the
  MassageIthaca lane-name duplication bug.
- **Composite action `lane-dispatch`** — constructs + emits the
  `<spoke>-lane-env` `repository_dispatch` to Blahaj (operation:
  `provision`). Validates payload against
  `schemas/blahaj-dispatch.schema.json`. Honors `lane-ttl/<N>d` PR labels.
  Supports `dry_run: true`.
- **Composite action `lane-reap`** — same shape with operation:
  `destroy`. Idempotent.
- **Composite action `lane-status-check`** — posts `ci/lane/<name>`
  GitHub commit status so branch protection can require per-lane checks.
- **Composite action `pulse-ingest-validate`** — wraps the
  `static-projection-snapshot.mts` script so spokes drop the local copy.
- **Reusable workflow `spoke-ci.yml`** — canonical spoke CI:
  secrets-scan → lanes-load → flywheel-bazel-build (per-lane matrix) →
  flywheel-bazel-test (per-lane matrix) → bazel-graph → optional
  playwright. Posts per-lane status checks.
- **Reusable workflow `spoke-lane-env.yml`** — canonical PR-env workflow:
  publish-image (per-lane matrix) → dispatch-apply (single
  `lane-dispatch` call carrying full lanes array) → optional tailnet-qa
  (per-lane matrix filtered to `e2e: true`) → destroy-lanes on PR close.
- **Reusable workflow `spoke-pulse-ingest.yml`** — generalized
  pulse-ingest workflow that opens snapshot-refresh PRs.
- **`schemas/lanes.schema.json`** + **`schemas/blahaj-dispatch.schema.json`** —
  vendored from `tinyland-inc/site.scaffold/docs/schemas/`. Composite
  actions validate inputs/outputs against these.
- **`bazelrc/flywheel.bazelrc`** — embedded Flywheel bazelrc fragment.
  `flywheel-bazel` action installs it to `.bazelrc.flywheel` at run time;
  spokes also vendor a copy and refresh via `just sync-flywheel-bazelrc`.
- **`docs/roadmap.md`** — v1.1+ items including `lane-preview-tunnel`
  (dev-server-on-cluster).
- **`RELEASING.md`** — release flow + SemVer policy.

### Changed

- **`nix-setup`** — added outputs `runner_class`, `attic_reachable`,
  `bazel_cache_reachable` consumed by `flywheel-bazel` for cluster
  detection. Bazel-cache DNS probe added (matching the existing Attic
  probe). Behavior-compatible with v0.x.
- **`secrets-scan`** — added input `extra_paths` (default `""`) for
  per-spoke `.gitleaks.toml` lookups outside the repo root; added
  output `findings_count` parsed from the gitleaks JSON report;
  added a `Secrets scan` block to `GITHUB_STEP_SUMMARY`. Behavior-
  compatible.
- **`nix-build`**, **`greedy-cache`** — internal `@main` self-references
  bumped to `@v1`.
- **`README.md`** — rewritten with v1.0.0 quick-start + pin banner.

### Migration from `@main`

See [`docs/migration-v0-to-v1.md`](docs/migration-v0-to-v1.md).
TL;DR: `grep -rn 'tinyland-inc/ci-templates.*@main' .github/` and
replace each `@main` with `@v1.0.0`. The four pre-existing composite
actions remain behavior-compatible; new spokes additionally consume
the reusable workflows.

## [0.4.0] — 2026-05-17 (retroactive baseline)

Snapshot of `@main` at the SHA preceding the v1.0.0 cut. Provided so
consumers on `@main` have a SemVer tag to pin against during migration.
No code changes from the pre-tag `@main` state.

### Pre-existing

- Composite actions `nix-setup`, `nix-build`, `greedy-cache`,
  `secrets-scan`.
- Reusable workflows `js-bazel-package.yml`, `npm-publish.yml`.

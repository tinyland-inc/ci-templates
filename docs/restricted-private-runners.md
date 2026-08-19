# Restricted private-repository workflows

> **`spoke-lane-env-restricted.yml` is deprecated (TIN-489, post-#1255)**:
> it inherits `spoke-lane-env.yml`'s Blahaj-`repository_dispatch` PR-env
> routing, which Blahaj (cluster substrate only, post-#1255) no longer owns.
> PR-env create+destroy+TTL is the application's owner-overlay repository's
> capability now — see the ci-templates README's PR-env lifecycle producer
> note and `tinyland-inc/site.scaffold`
> `docs/patterns/owner-overlay-apply-plane.md`. It is kept callable, unchanged,
> only so existing callers don't break; do not point a new private spoke at
> it. `spoke-ci-restricted.yml` (CI, not PR-env) is unaffected by this note.

`spoke-ci-restricted.yml` and `spoke-lane-env-restricted.yml` are explicit
opt-in variants of the existing spoke workflows. They preserve the legacy
behavior, matrices, permissions, cache-first behavior, and lane lifecycle, but
every directly defined job routes through both:

- a required GitHub runner group owned by the caller's `-infra` overlay; and
- a required, reviewed GloriousFlywheel capability label.

The legacy `spoke-ci.yml` and `spoke-lane-env.yml` files remain
behaviorally unchanged for every caller that does not opt in, and their bytes
stay pinned by `SPECS[…][:legacy_sha256]` in
`scripts/restricted-workflow-contract.rb`. `spoke-ci.yml`'s optional
`runner_group` input (TIN-3902) is *not* this surface: it adds group routing
with no trust gate, is default-off (unset renders the pinned label-only
baseline byte-for-byte, proved by `just runner-group-contract-check`), and
admits any non-generic group the caller names. A private repo that needs the
fail-closed, reviewed group+capability contract — required inputs, no defaults,
fork and pre-scheduling trust gate — still uses the restricted variants here.

**TIN-3914 (v3.0.0) changed the legacy files, not this surface.** Both
`legacy_sha256` pins were re-recorded because the no-GitHub-hosted-runners
ruling moved the legacy lanes' hosted jobs onto self-hosted capability classes
(`spoke-ci.yml`'s three utility jobs through `default_runner_class`,
`spoke-lane-env.yml`'s four through a literal `tinyland-nix`). Those digests are
a tripwire on the legacy bytes so that adding or changing the restricted variant
cannot silently move the shared lane — they are not a claim that the legacy
files never change on purpose. The restricted variants needed **no** edit and
remain a strict subset: `validate_restricted` normalizes each job's `runs-on`
back to the legacy node before the structural comparison, so a legacy routing
change cannot widen the restricted contract. The restricted lanes were already
the "can never resolve to a hosted runner" variants; TIN-3914 simply removed the
gap between them and the shared lanes.
The restricted variants additionally close their dependency graph: internal
actions use exact `@v2.12.1` refs, third-party Actions use full commit SHAs
(`actions/checkout` is the verified v6.1.0 commit), the cache contract executes
from the release-vendored composite through one exact fail-closed strict step,
and both scanner archives bind the expected digest to the downloaded file in
their single allowed download/checksum/extract/install sequence. Alternate or
conditional contract execution and any additional scanner download, extraction,
or binary-execution path fail the source contract. `v2.12.0` does not provide
that transitive guarantee and must not be used as an immutability receipt for
this lane.

## Authority and sequencing

Adopt this surface in this order:

1. The owner `-infra` overlay creates or adopts a non-default runner group,
   limits it to the selected private repositories, and proves the live group,
   repository selection, and served capability labels. This is infrastructure
   ownership; it does not move application ownership into GloriousFlywheel or
   ci-templates.
2. ci-templates publishes an immutable release containing the restricted
   workflow. A branch, pull request, or workflow file is source intent, not a
   live runner-group receipt.
3. The private application repository pins that immutable release and requests
   the exact group and capabilities. Do not use `@main` or treat floating `@v2`
   as the initial acceptance proof.
4. Acceptance requires a fresh job receipt whose `runner_group_name` and runner
   labels match the requested group+capability. A green job in `Default`,
   `default`, `GitHub Actions`, a GitHub-hosted pool, or a generic shared group
   does not count.

Public repositories cannot use a private-only group as a substitute for a
separately reviewed public-PR trust design. Personal-account repositories need
an explicit organization/ownership decision; they must not invent a personal
or generic shared group to bypass this boundary.

The current source allowlist admits only `tinyland-infra`. A different owner
group requires an explicit review and new immutable ci-templates release. The
caller cannot widen this allowlist by supplying another `*-infra` string.

## Caller examples

Pin the first release with the enforced transitive closure:

```yaml
jobs:
  ci:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci-restricted.yml@v2.12.1
    with:
      runner_group: tinyland-infra
      nix_runner_label: tinyland-nix
      heavy_runner_label: tinyland-nix-heavy
      kvm_runner_label: tinyland-nix-kvm
      flywheel_config: flywheel
    secrets: inherit
```

```yaml
jobs:
  lane-env:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-lane-env-restricted.yml@v2.12.1
    with:
      runner_group: tinyland-infra
      nix_runner_label: tinyland-nix
      dind_runner_label: tinyland-dind
      kvm_runner_label: tinyland-nix-kvm
      spoke: my-private-spoke
    secrets:
      BLAHAJ_DISPATCH_TOKEN: ${{ secrets.BLAHAJ_DISPATCH_TOKEN }}
```

The group and capability inputs are intentionally exact. The trust job's
job-level `if` admits only `tinyland-infra` plus the reviewed `tinyland-nix`,
`tinyland-nix-heavy`, `tinyland-nix-kvm`, and `tinyland-dind` roles used by the
respective workflow. GitHub evaluates that condition before assigning the job
to a runner; the shell checks are defense in depth, not the admission gate. All
other jobs directly depend on the trust job and may not use `always()` to bypass
a skipped dependency. Default/shared/hosted/repo-shaped/wrong-capability
routes, fork or untrusted `pull_request_target` heads, and non-private callers
therefore skip before assignment and before checkout. Since TIN-3914 a hosted
route is doubly unreachable here: the trust gate rejected it before scheduling
already, and `scripts/lint-runs-on.rb` now FAILs a GitHub-hosted label in either
arm of a `{group, labels}` mapping at author time.

These workflows add no provider credentials, Tofu state, plan/apply authority,
production promotion policy, or app deployment ownership. `spoke-lane-env`'s
existing bounded image-and-Blahaj-dispatch behavior is copied unchanged; the
restricted variant changes only runner routing and pre-checkout trust gating.

# GitOps Stack Chassis (TIN-2597) — DRAFT, not yet released

Status: **proposal**. Authored 2026-08-13 under the operator-ratified
extract-and-promote posture (R172-R174) as part of the MMS-lineage
condensation sweep (site.scaffold -> GFTB -> MMS). Not tagged, not wired to
any real caller. Held for operator + mms-peer review before either GFTB or
MMS migrates.

## Source read

Five near-identical GitHub Actions workflows in
`Great-Falls-Tool-Bus/great-falls-tool-bus-infra`:

| File | k8s dir | just prefix | protected env | secret (+ alias) | health gate |
|---|---|---|---|---|---|
| `mail-crs.yml` | `k8s/mail` | `mail-cr` | `mail` | `MAIL_APPLY_KUBECONFIG_B64` (+ `GFTB_MAIL_KUBECONFIG_B64`) | no |
| `list-crs.yml` | `k8s/list` | `list-stack` | `mail` | `MAIL_APPLY_KUBECONFIG_B64` (+ `GFTB_MAIL_KUBECONFIG_B64`) | no |
| `form-crs.yml` | `k8s/form` | `form-stack` | `mail` | `MAIL_APPLY_KUBECONFIG_B64` (+ `GFTB_MAIL_KUBECONFIG_B64`) | no |
| `archive-stack.yml` | `k8s/archive` | `archive-stack` | `mail` | `MAIL_APPLY_KUBECONFIG_B64` (+ `GFTB_MAIL_KUBECONFIG_B64`) | no |
| `web-stack.yml` | `k8s/web` | `web-stack` | `web-apply` | `WEB_APPLY_KUBECONFIG_B64` (no alias) | yes |

Diffed 2026-08-13: `mail-crs.yml`, `list-crs.yml`, `form-crs.yml` and
`archive-stack.yml` are the **same file** with four strings swapped (stack
display name, `k8s/<dir>` path-trigger glob, just-recipe prefix, and the
irregular `mail-cr` vs `<x>-stack` prefix on the mail-CR file). Zero other
deltas — same two-job shape (`validate` always, `server`/`apply` gated on
`workflow_dispatch` + the protected `mail` environment), same fail-closed
secret-presence check, same materialize-then-optional-in-cluster-rewrite
step, same `GF_CORE_REF` pin-and-verify pair.

`web-stack.yml` is the same two-job chassis with three additive
capabilities: a typed fail-closed `confirm=apply` sentinel (no
required-reviewer branch protection on this org's free plan, so the
sentinel + protected environment IS the apply gate), a resolved-image input
normalized across its two trigger shapes (manual `workflow_dispatch` and a
`repository_dispatch` CD signal from the site repo's green `ci.yml`), and an
in-cluster health gate published to the step summary after apply.

Cross-checked against Medical-Massage-Specialists' own apply chassis
(`application-apply-ceremony.yml`, `pr-env-lifecycle.yml`): heavier
(lease-acquire/init/plan/record/verify/reverify/apply/lease-release, a
two-authority gate — reviewed-producer readiness AND a separate sha-bound
operator activation word — plus GitHub-App token minting for scoped
readback/check-publish grants). That is a different, higher-ceremony tier
(tofu-plan-bound production apply with a reviewed plan artifact, not a
kubectl-apply GitOps overlay) and is **not** what this chassis condenses.
Its relevant contribution here is confirming the *shape* of the two-authority
fail-closed gate as the pattern this chassis's single-authority credential
gate will eventually compose with, once the TIN-2609 controller exists (see
"Controller re-point" below) — not a fourth artifact to build now.

## What's proposed

Three new files, all under `.github/`:

1. **`.github/workflows/spoke-gitops-stack.yml`** — the ONE reusable
   `workflow_call` workflow. Two jobs (`validate`, `apply`), matching the
   four-file chassis exactly in its default path; `web-stack.yml`'s three
   additions become opt-in inputs (`require_confirm_sentinel`,
   `apply_image`/`apply_replicas`, `has_health_gate`) so it is the superset
   shape, not a sixth divergent file.
2. **`.github/actions/gitops-credential-gate/`** — the fail-soft (legibly
   diagnosed) / fail-closed (never proceeds without the secret) kubeconfig
   gate: primary secret name + optional compat alias, masked decode to a
   0600 temp file, optional in-cluster server-URL rewrite. Generalizes the
   `MAIL_APPLY_KUBECONFIG_B64` / `GFTB_MAIL_KUBECONFIG_B64` pair pattern
   without hard-coding it.
3. **`.github/actions/gitops-manifest-validate/`** — the templated
   `validate-*-stack.sh` shape. `lib.sh` extracts the
   `fail`/`require_file`/`field`/`assert_eq` quartet and the two universal
   invariants (digest-pinned images, `kubectl kustomize` renders clean)
   every one of the five `scripts/validate-*.sh` files in
   great-falls-tool-bus-infra already implements byte-identically. The
   composite sources `lib.sh` then runs a **caller-authored** assertions
   script for the tenant-specific CR/manifest field checks — the one part
   of each validator that must never be templated away (see "Substrate
   seam" below).

Plus a worked example: `docs/gitops-stack-chassis-example-mail-crs.yml`
(this doc's sibling), showing `mail-crs.yml` shrunk from ~154 lines to a
~25-line thin caller.

## What's deliberately NOT proposed here

- **No change to any GFTB or MMS repository file.** This PR lives entirely
  in `tinyland-inc/ci-templates`. Migrating a GFTB workflow to call
  `spoke-gitops-stack.yml`, or migrating a `validate-*.sh` script to source
  `gitops-manifest-validate/lib.sh`, is each repo's own follow-up PR, on its
  own review cycle, opt-in stack by stack. The four/five identical files
  keep working unmodified either way.
- **No merged validator.** `gitops-manifest-validate` does not know what a
  `MailAccount` or a `Deployment` replica count should be for any tenant.
  Templating that away would be exactly the anti-pattern R172-R174 rules
  out — it would absorb tenant content into a shared module instead of
  expressing the shared shape around it.
- **No controller call.** `spoke-gitops-stack.yml`'s apply step still runs
  `just <prefix>-apply` (an overlay-owned Justfile recipe), identically to
  today. See "Controller re-point" below for why that is the point, not a
  gap.

## Substrate seam: express vs. absorb

| Stays tenant-owned (expressed, not absorbed) | Becomes shared (this proposal) |
|---|---|
| What a stack's manifests must assert (MailAccount fields, Deployment replica counts, NetworkPolicy shape) | The assertion *vocabulary* (`fail`, `require_file`, `field`, `assert_eq`) and the two invariants true of every stack (digest pins, kustomize renders) |
| Which `just` recipes exist and what they do | The calling convention that invokes `<prefix>-validate` / `-server-dry-run` / `-apply` / `-health` uniformly |
| The actual kubeconfig secret value, and which cert-manager/controller mints it | The presence-check + masked-materialize + optional in-cluster rewrite mechanics around it |
| When to fire (push/PR/dispatch/CD-signal triggers) — stays in each stack's thin caller file in its own repo | The two-job validate/apply shape those triggers invoke |
| cert-manager `Certificate` objects, ingress class, DNS — all stay blahaj/overlay substrate | Nothing here touches them; this chassis is entirely inside the apply-mechanics layer, above the substrate |

## Controller re-point (the reason the apply step stays one verb)

`spoke-gitops-stack.yml`'s apply step is intentionally a single delegated
verb: one `nix develop ... -c just "<prefix>-apply"` line, nothing else in
that step. Per the single-authority law (R167) and the ratified apply-gate
posture: the apply step in any chassis is a thin gate that re-points to the
TIN-2609 owner-overlay controller's Accept/Refuse decision once the
controller's typed operand-class union lands, never a second apply
authority growing its own ceremony. Because this chassis never let that
step become more than one delegated verb, the future swap is a one-line
change inside the same step —

```diff
-            nix develop "${GF_CORE_CI_PATH}" -c just "${GF_JUST_RECIPE_PREFIX}-apply"
+            nix develop "${GF_CORE_CI_PATH}" -c gf-controller accept gitops-stack "${GF_JUST_RECIPE_PREFIX}"
```

— not a redesign. The credential-gate composite's output
(`kubeconfig_path`, `credential_source`) stays useful either way: the
controller's executor still needs a materialized, gated kubeconfig; only
who calls it with that kubeconfig changes.

## Open questions for review

1. **Runner label default** (`tinyland-nix`): matches GFTB's current runner
   choice. Confirm this is still correct for cross-repo `workflow_call`
   traffic from `Great-Falls-Tool-Bus/great-falls-tool-bus-infra` — the
   fleet's per-org runner registration is out of scope for this proposal to
   verify.
2. **Golden rule 2 ("default-off, opt-in")** technically does not bind a
   brand-new workflow (there is no existing traffic to keep byte-identical
   to) — but the design still treats every `web-stack.yml`-only capability
   as an opt-in input rather than baking it into the default path, on the
   theory that a chassis two stacks don't need shouldn't run for them. Flag
   if that reasoning should not extend to future stacks.
3. **`gitops-manifest-validate`'s `assertions_script` sourcing model** (the
   composite `source`s the caller's script rather than executing it as a
   subprocess) means the caller's assertions run in the same shell as
   `lib.sh`'s functions and inherit `set -euo pipefail` from it. This
   matches every source validator's own top-of-file `set -euo pipefail`,
   but is worth an explicit second look before any real script is migrated
   to depend on it.
4. **Versioning**: proposing this land as a new `v3` minor once merged
   (additive, no existing consumer touched) rather than folding into the
   current `v2` line immediately — MMS-peer to confirm against
   `RELEASING.md`'s actual cadence rather than this doc guessing it.

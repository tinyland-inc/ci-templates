# ci-templates roadmap

Beyond v1.0.0.

## v1.1+ (planned)

### `lane-preview-tunnel` composite

Dev-server-on-cluster for non-PR developer branches. Mirrors the
`lane-dispatch` shape but provisions a single dev-only env with a
Tailscale tunnel back to the developer's laptop.

**Design**: see [`spec/dev-remote.md`](./spec/dev-remote.md) for the
full 12-section spec. New event_type `<spoke>-dev-env` (distinct from
`<spoke>-lane-env`); keyed by `(dev_id, branch)` not `pr_number`; 8h
default TTL with idle-reap; Tailscale `Service` for tunnel ingress
(tailscale-operator already deployed on the cluster).

**Why not REAPI**: `tinyland-inc/GloriousFlywheel/config/rbe-target-eligibility.json`
explicitly forbids `developer-servers` — REAPI actions must be
bounded, dev servers aren't. Pathway is Blahaj-side K8s Deployment +
tailscale-operator Service, NOT REAPI.

**Implementation status**: design only. Blocking on Blahaj-side
handler (separate repo) + `schemas/blahaj-dev-dispatch.schema.json`
in this repo + the composite + `spoke-dev-env.yml` reusable workflow.
See spec §12 for the implementation order when v1.1 starts.

### Per-lane TTL ceiling overrides

Right now `lane-ttl/keep` pins at the schema max (720h). Some long-lived
QA PRs (e.g. accessibility audits) might warrant a higher ceiling.
Likely: org-level allowlist of repos that may set `lane-ttl/permanent`.

### `flywheel-reapi-proof` composite

Extract MassageIthaca's bespoke `rbe-proof` job pattern into a reusable
composite once a second spoke wants it. Currently spoke-local; promotion
gated on demand.

### Renovate / Dependabot configs

Ship vendored `renovate.json` snippet that spokes can extend to keep
their `@v1.x.y` ci-templates pin current.

## v2.0+ (speculative)

- **lanes.json schema v2**: TBD breaking changes. Possible candidates:
  per-lane `cluster_region` for multi-region spokes; per-lane `traffic_split`
  for canary lanes.
- **Replace `repository_dispatch` with a webhook receiver** if Blahaj
  gains a dedicated HTTPS endpoint (`gh api` round-trip is the simplest
  surface today).

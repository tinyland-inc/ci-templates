# ci-templates roadmap

Beyond v1.0.0.

## v1.1+ (planned)

### `lane-preview-tunnel` composite

Dev-server-on-cluster for non-PR developer branches. Mirrors the
`lane-dispatch` shape but provisions a single dev-only env with a
Tailscale tunnel back to the developer's laptop.

**Blocker**: REAPI explicitly forbids dev-server targets
(`tinyland-inc/GloriousFlywheel/config/rbe-target-eligibility.json` —
`developer-servers` is `status: blocked`). A separate
not-via-REAPI pathway (kubernetes Job + tailscale sidecar) must be
designed first. Likely depends on a Blahaj-side `dev-tunnel-env`
event_type.

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

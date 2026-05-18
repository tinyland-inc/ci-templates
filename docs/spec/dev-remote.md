# dev-remote spec (v1.1+)

> **Status**: Design draft. Not yet implemented. Tracked from
> [`docs/roadmap.md`](../roadmap.md).
>
> **Target release**: ci-templates `v1.1.0`. Requires companion
> Blahaj-side support (separate repo) and a `tailscale-operator`
> module on the cluster (already deployed; see
> `tinyland-inc/GloriousFlywheel/tofu/modules/tailscale-operator/`).
>
> **Reader pre-reqs**: familiarity with `tinyland-inc/site.scaffold/docs/CI-SCHEMA.md`
> §4 (Blahaj dispatch payload schema), §5 (Flywheel binding —
> particularly the *blocked* `developer-servers` target class), and
> §7 (per-PR ephemeral env contract).

---

## 1. Goal

Let a developer push a non-PR branch and ask the cluster to spin up a
`pnpm run dev` (or equivalent) preview environment with a Tailscale
tunnel back to their laptop. The laptop runs only a thin tunnel
client; the actual dev server, hot-reload, and any cluster-resident
state (Tofu, snapshots) live on the cluster.

Motivating use case: a developer working from an underpowered laptop
gets a SvelteKit dev server with full HMR running on
`tinyland-nix-heavy` (or `tinyland-nix-kvm`) and accesses it at
`dev-<developer>-<branch>.<spoke.domain>` via Tailnet. Local
`pnpm run dev` becomes a *fallback* DX, not the primary one.

## 2. Why not REAPI

`tinyland-inc/GloriousFlywheel/config/rbe-target-eligibility.json`
explicitly blocks `developer-servers` (lines 210-217):

```json
{
  "name": "developer-servers",
  "status": "blocked",
  "labels": ["//app:dev"],
  "blockers": [
    "devserver targets are interactive long-running local processes",
    "remote execution proof requires bounded actions with declared outputs"
  ],
  "go_condition": "Do not make devserver targets RBE-eligible; use local/devshell or runner-shaped workflows."
}
```

This invariant is non-negotiable: REAPI actions are *bounded* — they
have declared outputs and a finite runtime. A dev server is
*unbounded* by design.

The non-REAPI pathway: a Kubernetes Job (long-lived Pod, really —
either a Job with no completion or a Deployment scaled to 1) under
Blahaj's control, with a `tailscale-operator`-issued sidecar exposing
the dev port to the developer's tailnet.

## 3. Lifecycle

```
dev-remote invocation                 cluster                       developer
─────────────────────                  ───────                       ─────────
just dev-remote [lane]
  │
  ├─ gh workflow run dev-remote.yml
  │    inputs: { lane, branch, dev_id }
  │
  │                                   spoke-dev-env.yml fires
  │                                     │
  │                                     ├─ lanes-load
  │                                     │
  │                                     ├─ lane-preview-tunnel:
  │                                     │    repository_dispatch to Blahaj
  │                                     │    event_type: <spoke>-dev-env
  │                                     │    operation: provision-dev
  │                                     │
  │                                     │              Blahaj receives →
  │                                     │              create K8s Deployment in
  │                                     │              spoke-<slug> ns running
  │                                     │              image:dev with
  │                                     │              `pnpm run dev`
  │                                     │
  │                                     │              + create Tailscale Service
  │                                     │              + register MagicDNS name
  │                                     │                `dev-<dev_id>-<branch>.<spoke.domain>`
  │                                     │
  │                                     ◄────────── tailnet URL returned
  │                                                  via dispatch_id correlation
  │
  ├─ just dev-remote prints URL ──────────────────────────────────────►  open in browser
  │                                                                     (or use port-forward)
  │
  │  ... developer iterates locally; pushes commits trigger
  │      Blahaj-side `git pull` + `pnpm install` + dev-server reload ...
  │
  └─ just dev-remote stop [lane]
       │
       └─ repository_dispatch operation: destroy-dev
                                          │
                                          └─ Blahaj scales Deployment to 0
                                             and deletes Tailscale Service.
```

### Lifetime semantics

- **No PR association.** Dev envs are keyed by `(spoke, dev_id,
  branch)`, not by `pr_number`.
- **TTL backstop**: 8h default (vs PR-env 72h). Developers re-up via
  `just dev-remote --extend`.
- **Idle reap**: Blahaj scales to 0 after 30 min of no tailnet traffic
  (configurable). Scale-back-up is automatic on next request.
- **Hard ceiling**: 30 days per `(dev_id, branch)`. Past that, manual
  reap + re-provision.
- **Branch deletion** triggers immediate reap (Blahaj watches push
  events).

## 4. Wire contract

### New event_type: `<spoke>-dev-env`

Distinct from `<spoke>-lane-env`. Different semantics warrant different
routing.

### Payload schema

`schemas/blahaj-dev-dispatch.schema.json` (new; ships in v1.1.0). Shape:

```json
{
  "event_type": "<spoke>-dev-env",
  "client_payload": {
    "schema_version": 1,
    "operation": "provision-dev | destroy-dev | extend-dev",
    "spoke": "<spoke-slug>",
    "domain": "<spoke.domain>",
    "dev_id": "<tailscale-identity-or-email-slug>",
    "branch": "feat/foo",
    "commit_sha": "<full-sha-or-empty-for-floating-tip>",
    "image_ref": "ghcr.io/<owner>/<spoke>:dev-<dev_id>-<branch_slug>",
    "ttl_hours": 8,
    "idle_reap_minutes": 30,
    "lane_template": "<lane-name-from-lanes.json>",
    "ports": [
      { "name": "dev", "container": 5173, "scheme": "http" }
    ],
    "tailnet": {
      "magic_dns_name": "dev-<dev_id>-<branch_slug>.<spoke.domain>",
      "share_with": "<tailnet-user-or-group>"
    }
  }
}
```

Key differences from the lane-env payload (CI-SCHEMA §4):

| Field | `lane-env` | `dev-env` |
|---|---|---|
| Keyed by | `pr_number` | `(dev_id, branch)` |
| Lifetime | 72h fixed | 8h with idle reap + extend |
| Lanes | array of N envs | single env, templated from one lane |
| Ports exposed | static-site only (no tunnel needed) | dev port via Tailscale Service |
| Reap trigger | PR closed | branch deleted / explicit stop / TTL |

## 5. Composite action: `lane-preview-tunnel`

`tinyland-inc/ci-templates/.github/actions/lane-preview-tunnel/action.yml`

### Inputs

| Input | Required | Default | Description |
|---|---|---|---|
| `operation` | yes | — | `provision-dev`, `destroy-dev`, `extend-dev`. |
| `spoke` | yes | — | Spoke slug. |
| `domain` | yes | — | Spoke brand domain. |
| `dev_id` | yes | — | Tailscale identity slug (or email-derived slug). |
| `branch` | yes | — | Branch name. |
| `commit_sha` | no | `""` | Empty = follow branch tip. |
| `lane_template` | no | `"default"` | Lane name from `lanes.json` to template the dev env from (theme, snapshot_source). |
| `image_ref` | yes (provision) | — | Built dev image (separate from PR-env image). |
| `ttl_hours` | no | `8` | Provision TTL. |
| `idle_reap_minutes` | no | `30` | Idle reap window. |
| `ports` | no | `[{"name":"dev","container":5173,"scheme":"http"}]` | Ports to tunnel. |
| `blahaj_repository` | no | `tinyland-inc/blahaj` | |
| `dispatch_token` | yes (live) | — | Repo dispatch token. |
| `dry_run` | no | `false` | Print payload, don't dispatch. |

### Outputs

- `tunnel_url` — `https://dev-<dev_id>-<branch_slug>.<spoke.domain>` (echoed; Blahaj actually allocates).
- `dispatch_id` — synthetic correlation key.

### Refusals

- `dev_id` must match `^[a-z][a-z0-9-]{0,30}$` — derive from email
  or tailnet machine name client-side.
- Composite refuses if it detects the *caller* is using the `dev-env`
  flow to build a static-site PR env (i.e., wrong tool for the job).
- Composite never dispatches on a `tag` ref — dev envs are
  branch-only.

## 6. Spoke-side Justfile recipe

The v1.0 `dev-remote` recipe is currently a stub that prints a v1.1+
notice. The v1.1 implementation:

```just
# Spin up a cluster-side dev server with a Tailscale tunnel back to this laptop.
# Requires gh CLI auth + Blahaj App installation on the spoke repo.
dev-remote lane="default":
    @branch=$(git rev-parse --abbrev-ref HEAD); \
    dev_id=$(tailscale status --self --json 2>/dev/null | jq -r '.Self.HostName' | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | sed 's/^-//;s/-$//'); \
    [ -n "$dev_id" ] || { echo "[dev-remote] tailscale not joined; run 'tailscale up' first" >&2; exit 1; }; \
    echo "[dev-remote] spoke=$(jq -r .spoke.name .github/lanes.json) lane={{ lane }} branch=$branch dev_id=$dev_id"; \
    gh workflow run dev-remote.yml -f lane={{ lane }} -f branch=$branch -f dev_id=$dev_id
    @echo "Watch progress: gh run watch"
    @echo "Tunnel URL will appear in the workflow log after Blahaj provisions."

# Tear down a previously-spawned dev env.
dev-remote-stop lane="default":
    @branch=$(git rev-parse --abbrev-ref HEAD); \
    dev_id=$(tailscale status --self --json | jq -r '.Self.HostName' | tr 'A-Z' 'a-z' | tr -c 'a-z0-9-' '-' | sed 's/^-//;s/-$//'); \
    gh workflow run dev-remote.yml -f operation=destroy-dev -f lane={{ lane }} -f branch=$branch -f dev_id=$dev_id
```

The spoke also gains a thin wrapper workflow
`.github/workflows/dev-remote.yml` consuming the new reusable workflow
`spoke-dev-env.yml@v1.1.0`.

## 7. Spoke-side reusable workflow: `spoke-dev-env.yml`

Thin: `workflow_dispatch` only. Builds dev image (cluster runner,
fast — uses Bazel cache), calls `lane-preview-tunnel`.

```yaml
on:
  workflow_dispatch:
    inputs:
      operation: { default: provision-dev }
      lane:      { default: default }
      branch:    { required: true }
      dev_id:    { required: true }
```

Image build target: `bazelisk run //app:devimage` or `docker build`
with a `Dockerfile.dev` (spoke provides this; scaffold ships a
template). Per `developer-servers` invariant, the BUILD action is
fine (bounded, declared outputs); only the `pnpm run dev` *runtime*
is non-REAPI.

## 8. Cluster-side requirements (Blahaj + tailscale-operator)

Out of this repo's scope, but documented for reference:

### Blahaj must:

- Handle the new `<spoke>-dev-env` event_type with the three operations.
- On `provision-dev`: create a `Deployment` (not Job — needs scale-to-0)
  in `spoke-<slug>` namespace, label
  `tinyland.dev/dev-env=<dev_id>-<branch_slug>`, mount the
  `snapshot_source` from the spoke's lane template, run
  `pnpm install && pnpm run dev`.
- Create a Tailscale `Service` referencing the Deployment + a
  `ServiceAccount` granting the developer's tailnet identity
  `share_with` access.
- Run an idle-reap cron loop that scales Deployments to 0 when
  Tailscale Service has had no traffic for `idle_reap_minutes`.
- Watch GitHub push events to reap on branch deletion.

### tailscale-operator must:

- Already deployed (it is, per
  `tinyland-inc/GloriousFlywheel/tofu/modules/tailscale-operator/`).
- Support `Service` CRD with the MagicDNS-name annotation pattern
  Blahaj will use.
- Grant `share_with` semantics via tailnet ACL update — Blahaj
  manages those.

## 9. Auth model

- **Developer → Blahaj**: developer's `gh workflow run` dispatches via
  the spoke's `BLAHAJ_DISPATCH_TOKEN`. Same auth as PR-env flow.
- **Developer → cluster dev env**: Tailscale identity. Developer must
  be on the tinyland tailnet; Blahaj's `share_with` field tells the
  tailscale-operator to grant access to that specific identity.
- **Cluster dev env → cluster state**: a per-spoke ServiceAccount
  (provisioned by `spoke-state-namespace` companion module — TBD,
  maybe `spoke-dev-rbac` in v1.1) limits the Pod's access to the
  spoke's S3 prefix + namespace.

## 10. Open questions (resolve before v1.1.0)

1. **Image build path**: scaffold provides a `Dockerfile.dev` template
   (recommended), or expects the spoke to author one (current
   posture)? Decision affects whether `site.scaffold` ships a v1.0.x
   patch adding the template.
2. **`dev_id` derivation**: tailscale machine name vs email-slug?
   Machine name avoids developer-side config but is opaque ("jess-mbp")
   vs email-derived ("jess"). Lean toward machine name; document the
   trade-off.
3. **State sharing across dev envs**: should a developer's two
   simultaneous dev envs (branch A + branch B) share `snapshot_source`
   cache, or be fully isolated? Isolated is safer; shared is faster.
4. **Tailscale `share_with` granularity**: per-developer (tight) vs
   per-tag like `tag:tinyland-devs` (loose). Tight requires tailnet
   ACL changes per provision; loose is simpler.
5. **REAPI for the build phase**: the dev *runtime* is non-REAPI by
   invariant, but the *image build* (`//app:devimage`) could use
   REAPI if proved as a target class. Worth proving for v1.1.0 or
   defer to v1.2?
6. **Spoke-side `dev-remote-status` recipe**: list a developer's
   live dev envs (`gh api repos/tinyland-inc/blahaj/...?q=dev_id=...`).
   Nice-to-have; not blocking.
7. **Migration from current `dev-remote` stub**: site.scaffold's stub
   prints a v1.1+ notice. When v1.1 ships, the recipe replaces the
   stub via a `site.scaffold` patch tag. Stale clones still get the
   stub message — acceptable.

## 11. Non-goals

- **No CI runs against dev envs** — these are interactive dev
  surfaces, not deployment targets. `tailnet-qa` continues to target
  PR envs only.
- **No public DNS** — dev envs are tailnet-only. The `MagicDNS` name
  is not resolvable outside the tailnet.
- **No persistence beyond TTL** — dev envs are ephemeral. Anything a
  developer wants to keep must commit + PR.
- **No multi-port forwarding by default** — `ports` array allows
  extra ports, but the recommended posture is one dev port +
  whatever introspection (e.g. Vite HMR websocket) the same port
  serves.
- **No promotion of `developer-servers` to REAPI** — invariant from
  `rbe-target-eligibility.json` §5. This spec exists *because* that
  invariant holds.

## 12. Implementation order (when v1.1 starts)

1. Blahaj-side handler for the new event_type (separate repo).
2. `schemas/blahaj-dev-dispatch.schema.json` in this repo.
3. `lane-preview-tunnel` composite action.
4. `spoke-dev-env.yml` reusable workflow.
5. CHANGELOG.md `## [Unreleased]` + tag `v1.1.0` via the
   `release.yml` flow.
6. `site.scaffold` v0.2+ patch: replace `dev-remote` stub with the
   real recipe, add `.github/workflows/dev-remote.yml` wrapper,
   optionally add `Dockerfile.dev` template.

# Migrate ActionPlan/v4 schema 2 to schema 3

ci-templates `v5.1.0` is the current portable carrier of schema 3, first
introduced in `v5.0.0`. The later attended `v5.1.1` release will carry the
qualified-result caller repair described below; it must exist before consumers
pin it. Schema 3 is an incompatible revision of the GloriousFlywheel
`ActionPlan/v4` interface.
The reusable workflow remains the thin `spoke-ci-v4.yml` dispatcher; the
product interface did not become ActionPlan/v5.

Schema 2 omitted result disposition and admitted only Linux demand. Schema 3
makes result handling explicit and admits both provider-blind capability
values. It does not claim either capability has live provider supply.

## Update the checked-in plan

Every action must choose exactly one result mode:

```json
{
  "schema_version": 3,
  "actions": {
    "unit-tests": {
      "command": "test",
      "targets": ["//tests/..."],
      "capability": "rbe-linux-x86_64",
      "result": { "mode": "status-only" }
    },
    "deployment-bundle": {
      "command": "build",
      "targets": ["//deploy:bundle"],
      "capability": "rbe-linux-x86_64",
      "result": {
        "mode": "export-regular-files",
        "output_groups": ["default"]
      }
    }
  }
}
```

Use `status-only` when the caller needs only the REAPI terminal status. It
accepts no `output_groups`. Use `export-regular-files` only for exact Bazel
labels whose selected output groups contain regular files; wildcard and
recursive target patterns are rejected. Directories, trees, symlinks, and
special files are not silently flattened or omitted.

Beginning with `v5.1.1`, the workflow passes every invocation one new result
directory beneath `RUNNER_TEMP`, keyed by run, attempt, and action name. The
ActionPlan remains the sole result-disposition authority. The workflow does not
parse or upload the directory, and its fixed files do not convey GF-I09
publication authority.

`rbe-linux-x86_64` and `rbe-darwin-aarch64` express demand only. The signed
provider catalog must supply the chosen capability or resolution fails closed.
Do not add a runner label, local execution, hosted CI, another architecture,
or cache-only path as compensation.

## Move the authority graph atomically

1. Validate the raw schema-3 plan against `schemas/lanes.schema.json`.
2. Publish a new immutable consumer-owned overlay revision if organization
   policy changed. `OwnerInstallation/v1` and `TenantOverlay/v1` authorize the
   organization, workflow/ref/event classes, and capability policy; they never
   enumerate repositories or ActionPlan digests.
3. Provision the `gf-v4-dispatch` runner edge in that organization's runner
   group and require a current `ResolvedOwnerSupplyCatalog/v1`, admitted
   provider supply, and a provider image carrying the schema-3
   `gf-action-client`. The image must accept `--result-dir` before the caller
   pin moves. The client binds the exact repository, source SHA, workflow,
   event, ref, and ActionPlan at invocation time.
4. After the attended immutable release exists, pin the caller to
   `tinyland-inc/ci-templates/.github/workflows/spoke-ci-v4.yml@v5.1.1`; do not
   move or reuse `v5.1.0`.
5. Prove a remote miss with nonzero WorkerLeaf execution and an exact
   `ActionOutputSet/v1` when export was requested. Repeat the identical action
   and prove an ActionCache hit with no execution lease.
6. Delete the schema-2 caller and superseded v3 attachment in the same adoption
   pass. Do not leave either as fallback doctrine.

An absent organization App installation, signed overlay, catalog, dynamic
binding, client, route, worker, CAS object, or output set is a hard failure.
The ci-templates tag proves
immutable workflow source only; it does not prove enrollment, provider
convergence, execution, cache effectiveness, result carriage, or production
serving.

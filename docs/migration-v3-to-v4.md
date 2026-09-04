# Migrate from v3 CI profiles to the v4 action fabric

> Historical first step: `v4.0.0` carried ActionPlan/v4 schema 2. The current
> target is schema 3 through `spoke-ci-v4.yml@v5.1.1` or newer; schema 2 is not
> a fallback.

`v4.0.0` is a breaking interface. V4 schedules Bazel actions through the
GloriousFlywheel REAPI fabric; it does not expose runners, endpoints, cache
profiles, credentials, lifecycle controls, or a local execution path to the
consumer.

The immutable workflow pin is:

```yaml
jobs:
  unit-tests:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci-v4.yml@v5.1.1
    with:
      action_name: unit-tests
```

The application repository owns `.github/lanes.json`. Its raw bytes are bound
by the consumer overlay, so do not generate or rewrite it during CI:

```json
{
  "schema_version": 3,
  "actions": {
    "unit-tests": {
      "command": "test",
      "targets": ["//tests/..."],
      "capability": "rbe-linux-x86_64",
      "result": { "mode": "status-only" }
    }
  }
}
```

One workflow invocation selects exactly one declared action. The workflow
checks out the exact admitted source SHA and requires
`/usr/local/bin/gf-action-client` at the provider-custodied image path. It
invokes that client once; the compiled client owns OIDC, resolution, and
fail-closed REAPI dispatch. The workflow always passes one new result directory
beneath `RUNNER_TEMP`, keyed by run, attempt, and action name. The ActionPlan is
the sole result-disposition authority: the workflow neither interprets nor
uploads that directory, and its files do not convey GF-I09 publication
authority.

## Consumer and provider ownership

The adopting organization's `-infra` repository owns immutable signed
`OwnerInstallation/v1` and `TenantOverlay/v1` revisions. They bind organization
identity, App installation, admitted workflow/ref/event classes, abstract
capability policy, concurrency policy, and write policy. They do not enumerate
repositories or ActionPlan digests; the client creates that exact binding from
the invocation and OIDC identity.

GF core owns the types, verifier, client, resolver, and scheduler. The substrate
provider owns concrete endpoints, worker supply, images, storage, and placement.
Neither GF core nor ci-templates keeps a list of consumers, and a consumer never
names a runner label, node, cluster, storage class, provider endpoint, or image.

## Fail-closed migration order

1. Install the organization's all-repositories GF GitHub App and provision its
   own thin `gf-v4-dispatch` edge.
2. Check in the finite schema-3 action plan.
3. Publish the consumer-owned signed overlay at an immutable digest through the
   canonical overlay publisher.
4. Require the independent controller/verifier to join organization policy with
   signed provider supply and publish a current immutable owner-supply catalog.
5. Converge the provider-owned client image and action-resolution route. The
   image must accept the workflow's `--result-dir` contract before the caller
   pin moves.
6. After the attended immutable release exists, pin
   `spoke-ci-v4.yml@v5.1.1`; do not move or reuse `v5.1.0`.
7. Prove one remote cache miss with nonzero remote execution, then repeat the
   same action and prove a same-authority ActionCache hit. Attribute both to the
   consumer in the measurement plane.
8. Delete the superseded v3 workflow, profile, wrapper, cache-proof, ARC, Docker,
   and DinD surfaces only after the canary succeeds.

An absent App installation, overlay, catalog, dynamic binding, client, route,
or worker is a hard failure. Do not add a hosted runner, local Bazel, cache-only,
direct endpoint, v3 registry, bespoke wrapper, Docker, or DinD fallback.

The v4 tag proves immutable workflow source. It does **not** prove enrollment,
publication, provider convergence, remote execution, cache effectiveness, or
production serving.

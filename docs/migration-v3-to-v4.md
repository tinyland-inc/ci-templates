# Migrate from v3 CI profiles to the v4 action fabric

`v4.0.0` is a breaking interface. V4 schedules Bazel actions through the
GloriousFlywheel REAPI fabric; it does not expose runners, endpoints, cache
profiles, credentials, lifecycle controls, or a local execution path to the
consumer.

The immutable workflow pin is:

```yaml
jobs:
  unit-tests:
    uses: tinyland-inc/ci-templates/.github/workflows/spoke-ci-v4.yml@v4.0.0
    with:
      action_name: unit-tests
```

The application repository owns `.github/lanes.json`. Its raw bytes are bound
by the consumer overlay, so do not generate or rewrite it during CI:

```json
{
  "schema_version": 2,
  "actions": {
    "unit-tests": {
      "command": "test",
      "targets": ["//tests/..."],
      "capability": "rbe-linux-x86_64"
    }
  }
}
```

One workflow invocation selects exactly one declared action. The workflow
checks out the exact admitted source SHA and invokes the image-custodied
`/usr/local/bin/gf-action-client` once. The compiled client owns OIDC,
resolution, and fail-closed REAPI dispatch.

## Consumer and provider ownership

The adopting organization's `-infra` repository owns signed
`OwnerInstallation/v1` and `TenantOverlay/v1` instances. They bind immutable
owner/repository identities, exact action-plan digests, admitted OIDC subjects,
abstract capability demand, concurrency demand, and write policy.

GF core owns the types, verifier, client, resolver, and scheduler. The substrate
provider owns concrete endpoints, worker supply, images, storage, and placement.
Neither GF core nor ci-templates keeps a list of consumers, and a consumer never
names a runner label, node, cluster, storage class, provider endpoint, or image.

## Fail-closed migration order

1. Pin `spoke-ci-v4.yml@v4.0.0` and check in the finite action plan.
2. Publish the consumer-owned signed overlay at an immutable digest through the
   canonical overlay publisher.
3. Require the independent controller/verifier to join that demand with signed
   provider supply and publish a current immutable binding catalog.
4. Converge the provider-owned runner image and action-resolution route.
5. Prove one remote cache miss with nonzero remote execution, then repeat the
   same action and prove a same-authority ActionCache hit. Attribute both to the
   consumer in the measurement plane.
6. Delete the superseded v3 workflow, profile, wrapper, cache-proof, ARC, Docker,
   and DinD surfaces only after the canary succeeds.

An absent App installation, overlay, catalog, input capsule, client, route, or
worker is a hard failure. Do not add a hosted runner, local Bazel, cache-only,
direct endpoint, v3 registry, bespoke wrapper, Docker, or DinD fallback.

The v4 tag proves immutable workflow source. It does **not** prove enrollment,
publication, provider convergence, remote execution, cache effectiveness, or
production serving.

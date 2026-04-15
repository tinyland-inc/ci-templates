# ci-templates: Repo-Specific Review Rules

Inherits all rules from `_org-enforced-rules.md`.

## GitHub Actions

- Pin ALL third-party actions to full commit SHA (e.g., `actions/checkout@a5ac7e5...`), never floating tags.
- Every reusable workflow must define `workflow_call` with typed `inputs` and `outputs`.
- Use `permissions` blocks at the job level. Default to read-only; justify any write permissions in comments.
- Never echo or log secrets, even behind `ACTIONS_STEP_DEBUG`. Use masking (`::add-mask::`) when passing values.
- Use `timeout-minutes` on all jobs to prevent runaway billing.

## Shell in Workflows

- Inline shell steps must use `shell: bash` explicitly (not rely on runner default).
- Use `set -euo pipefail` in multi-line run blocks.
- Quote all variable expansions to prevent word splitting.

## Blast Radius

- Changes to reusable workflows affect all downstream consumers. PR descriptions must list which repos consume the changed workflow.
- Breaking changes to workflow inputs/outputs require a deprecation period or version bump.

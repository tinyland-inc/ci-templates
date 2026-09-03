# frozen_string_literal: true

# Shared ARC runner capability-label taxonomy.
#
# This began as the Ruby port of
# GloriousFlywheel/scripts/validate-arc-runner-taxonomy.py::label_errors()
# (the source-config guard for tinyland tofu runner_label values). TIN-2353
# widens the workflow-facing surface to org-namespaced tenant pools, so this
# module is now the authoritative dependency-free grammar for `runs-on` strings
# in .github/workflows; the Python file remains authoritative for tinyland
# tfvars.
#
# Why a separate copy and not an import: ci-templates ships to ~160 spoke repos
# without a GloriousFlywheel checkout or Python + PyYAML. Ruby's stdlib YAML is
# sufficient, so the guard remains dependency-free everywhere it runs.
module RunnerLabelTaxonomy
  # The portable v4 dispatch edge plus the six historical Tinyland capability
  # labels. The dispatch edge is org-local and thin; it is never compute supply.
  SHARED_CAPABILITY_LABELS = %w[
    gf-v4-dispatch
    tinyland-docker
    tinyland-dind
    tinyland-nix
    tinyland-nix-gpu
    tinyland-nix-heavy
    tinyland-nix-kvm
  ].freeze

  ORG_CAPABILITY_RE = /\A[a-z0-9][a-z0-9-]*-(nix|nix-heavy|nix-kvm|nix-gpu|docker|dind)\z/.freeze

  # Suffixes permitted on a constructed tinyland-{docker,dind,nix}-<suffix...>
  # label (validate-arc-runner-taxonomy.py:31-48). NOTE: includes `operator`
  # (live as tinyland-nix-operator) — do not trim this list by memory.
  ALLOWED_TINYLAND_SUFFIXES = %w[
    aarch64 arm64 browser dawn darwin gpu heavy kvm linux macos
    operator privileged riscv vm webgpu x86_64
  ].freeze

  # Project-identity tokens that must never appear in a capability label
  # (validate-arc-runner-taxonomy.py:54-66).
  PROJECT_IDENTITY_TOKENS = %w[
    7810 acuity betterkvm cmux dell linux-xr massage massageithaca
    rockies scheduling tummycrypt xoxdwm
  ].freeze

  KNOWN_REPO_LABEL_FOSSILS = %w[
    dollhouse-farm-nix
    chapel-nix
    jesssullivan-nix-heavy
    massageithaca-dind
  ].freeze

  # GitHub-hosted runner families. TIN-3914 (operator ruling, 2026-08-19):
  # the estate runs ONLY on GF cache-fronted self-hosted runners, so these are
  # a hard FAIL for this guard — not a pass, not a warning. Before TIN-3914
  # they were PASSed here on the theory that the prefer-self-hosted posture was
  # a separate audit; there is no separate audit any more, the posture is the
  # rule.
  GITHUB_HOSTED_FAMILY_RE = /\A(ubuntu|macos|windows)-[a-z0-9_.-]+\z/i.freeze

  # Third-party managed hosted fleets (Blacksmith, Depot, …). These are neither
  # GitHub's infrastructure nor the org's ARC pool, and they are not GF
  # cache-fronted either — but the TIN-3914 ruling named GitHub runners, and no
  # ci-templates surface uses one. They WARN: surfaced for a deliberate
  # operator decision, never silently blessed.
  HOSTED_FLEET_RE = /\A(depot|warp|buildjet|blacksmith|namespace-profile)-[a-z0-9_.-]+\z/i.freeze

  module_function

  # Mirror of label_errors() in the Python authority. Returns [] for a valid
  # shared capability label, otherwise a list of human-readable reasons.
  def label_errors(label)
    errors = []
    tokens = label.downcase.split("-")

    return errors if SHARED_CAPABILITY_LABELS.include?(label)
    return errors if ORG_CAPABILITY_RE.match?(label) && !KNOWN_REPO_LABEL_FOSSILS.include?(label)

    if KNOWN_REPO_LABEL_FOSSILS.include?(label)
      errors << "known repo-shaped runner label fossil"
      return errors
    end

    if tokens.length < 2 || tokens[0] != "tinyland"
      errors << "label must use the org capability-class grammar (<org-pool>-nix|-nix-heavy|-nix-kvm|-nix-gpu|-docker|-dind)"
      return errors
    end

    unless %w[docker dind nix].include?(tokens[1])
      errors << "label must start with tinyland-docker, tinyland-dind, or tinyland-nix"
    end

    suffixes = tokens[2..] || []
    unknown = suffixes.reject { |s| ALLOWED_TINYLAND_SUFFIXES.include?(s) }
    errors << "unknown capability suffixes: #{unknown.join(", ")}" unless unknown.empty?

    project = (PROJECT_IDENTITY_TOKENS & tokens).sort
    errors << "label contains project identity tokens: #{project.join(", ")}" unless project.empty?

    errors
  end

  # A valid shared/constructed capability label?
  def shared_or_constructed?(label)
    label_errors(label).empty?
  end

  # A GitHub-hosted runner label (ubuntu-* / macos-* / windows-*)? FAIL.
  def github_hosted_label?(label)
    GITHUB_HOSTED_FAMILY_RE.match?(label)
  end

  # A third-party managed hosted fleet label? WARN.
  def third_party_hosted_label?(label)
    HOSTED_FLEET_RE.match?(label)
  end

  # Any hosted runner label, of either kind. Neither can ever satisfy a
  # self-hosted runner-group mapping, so the group rules use this predicate.
  def hosted_label?(label)
    github_hosted_label?(label) || third_party_hosted_label?(label)
  end
end

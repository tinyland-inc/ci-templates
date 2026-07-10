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
# and runs on bare hosted runners (no GloriousFlywheel checkout, no Python +
# PyYAML). Ruby's stdlib YAML is always present, so the guard is dependency-free
# everywhere it runs.
module RunnerLabelTaxonomy
  # The six tinyland base shared capability labels.
  SHARED_CAPABILITY_LABELS = %w[
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

  # GitHub-hosted runner families and operator-controlled third-party hosted
  # fleets. Hosted labels are allowed by THIS guard (it polices self-hosted
  # capability drift; the RBE-prefer-self-hosted posture is a separate audit).
  HOSTED_FAMILY_RE = /\A(ubuntu|macos|windows)-[a-z0-9_.-]+\z/i.freeze
  HOSTED_FLEET_RE  = /\A(depot|warp|buildjet|blacksmith|namespace-profile)-[a-z0-9_.-]+\z/i.freeze

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

  # A GitHub-hosted or known third-party hosted-fleet label?
  def hosted_label?(label)
    HOSTED_FAMILY_RE.match?(label) || HOSTED_FLEET_RE.match?(label)
  end
end

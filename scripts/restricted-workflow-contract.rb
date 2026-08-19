#!/usr/bin/env ruby
# frozen_string_literal: true

# Structural contract for the opt-in private-repository workflow variants.
# The variants may route only through an explicit owner -infra group plus an
# exact reviewed capability. Their transitive action graph is immutable and
# source-closed. The legacy shared workflows are checksum-pinned so adding this
# surface cannot silently change ~190 existing consumers.

require "digest"
require "json"
require "open3"
require "pathname"
require "yaml"

ROOT = File.expand_path("..", __dir__)
GROUP_EXPR = "${{ inputs.runner_group }}"
TRUST_JOB = "trust-gate"
IMMUTABLE_RELEASE = "v2.12.1"
CHECKOUT_SHA = "d23441a48e516b6c34aea4fa41551a30e30af803"
DETERMINATE_NIX_SHA = "61cbfe2efc2d4e7a8a6d56967c3c1058e846c858"
EXPECTED_SCANNER_DOCUMENT_SHA256 = "82d33165acfe0864388cc4aba88b34f3b378002768f91bdf78680235fdf9f3e5"
EXPECTED_SCANNER_STEP_NAMES = [
  "Install TruffleHog",
  "TruffleHog scan",
  "Install gitleaks",
  "Resolve gitleaks config",
  "Run gitleaks",
].freeze
SCANNER_INSTALL_SPECS = [
  {
    step: "Install TruffleHog",
    display_name: "TruffleHog",
    version_input: "trufflehog-version",
    sha_input: "trufflehog-sha256",
    version_env: "TRUFFLEHOG_VERSION",
    sha_env: "TRUFFLEHOG_SHA256",
    archive: 'archive="$BIN_DIR/trufflehog_${version}_linux_amd64.tar.gz"',
    url: '"https://github.com/trufflesecurity/trufflehog/releases/download/v${version}/trufflehog_${version}_linux_amd64.tar.gz" \\',
    member: "trufflehog",
  },
  {
    step: "Install gitleaks",
    display_name: "gitleaks",
    version_input: "gitleaks-version",
    sha_input: "gitleaks-sha256",
    version_env: "GITLEAKS_VERSION",
    sha_env: "GITLEAKS_SHA256",
    archive: 'archive="$BIN_DIR/gitleaks_${version}_linux_x64.tar.gz"',
    url: '"https://github.com/gitleaks/gitleaks/releases/download/v${version}/gitleaks_${version}_linux_x64.tar.gz" \\',
    member: "gitleaks",
  },
].freeze
EXPECTED_CLOSURE_ACTIONS = %w[
  cache-attachment-validate
  flywheel-bazel
  lane-dispatch
  lane-reap
  lane-status-check
  lanes-load
  nix-setup
  repo-manifest-validate
  secrets-scan
  setup-nix
].freeze

SPECS = {
  "spoke-ci" => {
    legacy: ".github/workflows/spoke-ci.yml",
    restricted: ".github/workflows/spoke-ci-restricted.yml",
    # Re-recorded for TIN-3914 (no GitHub-hosted runners in the estate).
    # Previously 656e8c69… (TIN-3902, optional `runner_group` input).
    #
    # WHAT THIS DIGEST PROVES, and why moving it is intentional and reviewed:
    # it pins the LEGACY workflow's bytes so that adding or changing the
    # restricted variant cannot silently alter the ~190 consumers of the shared
    # lane. It is a tripwire on the legacy file, not a claim that the legacy
    # file never changes. TIN-3914 changes the legacy file on purpose: the
    # secrets-scan, lanes-load, and repo-manifest jobs move off the retired
    # GitHub-hosted class onto `inputs.default_runner_class`, composed through
    # the same default-off `runner_group` form the other jobs already use. The
    # accompanying default-off proof is `just runner-group-contract-check`,
    # which re-renders every job over the scenario grid; the restricted
    # variant's own routing is unaffected because `validate_restricted`
    # normalizes runs-on back to the legacy node before the structural compare.
    legacy_sha256: "a312785bf7b5fa23aad75c4a79b86cf82f059a0c91bac2acf1827795d0677d49",
    inputs: {
      "runner_group" => "tinyland-infra",
      "nix_runner_label" => "tinyland-nix",
      "heavy_runner_label" => "tinyland-nix-heavy",
      "kvm_runner_label" => "tinyland-nix-kvm",
    },
    removed_legacy_inputs: %w[default_runner_class runner_labels_json heavy_runner_class kvm_runner_class],
    labels: {
      "trust-gate" => "nix_runner_label",
      "secrets-scan" => "nix_runner_label",
      "lanes-load" => "nix_runner_label",
      "repo-manifest" => "nix_runner_label",
      "flywheel-build" => "nix_runner_label",
      "flywheel-test" => "nix_runner_label",
      "bazel-graph" => "heavy_runner_label",
      "playwright" => "kvm_runner_label",
    },
    runner_env: {
      "flywheel-build" => "nix_runner_label",
      "bazel-graph" => "heavy_runner_label",
    },
  },
  "spoke-lane-env" => {
    legacy: ".github/workflows/spoke-lane-env.yml",
    restricted: ".github/workflows/spoke-lane-env-restricted.yml",
    # Re-recorded for TIN-3914. Previously 8e7e444f… . The deprecated legacy
    # lane's four GitHub-hosted jobs (check-blahaj-token, lanes-load,
    # dispatch-apply, destroy-lanes) move to the literal base capability class
    # `tinyland-nix`, matching the literal `tinyland-dind` / `tinyland-nix-kvm`
    # routing its other two jobs already used. No input surface changes, so the
    # restricted variant stays a strict subset unchanged.
    legacy_sha256: "c238ab598b464d864c8e933ff951688833cd8107df3077b346db76b4d71ae470",
    inputs: {
      "runner_group" => "tinyland-infra",
      "nix_runner_label" => "tinyland-nix",
      "dind_runner_label" => "tinyland-dind",
      "kvm_runner_label" => "tinyland-nix-kvm",
    },
    removed_legacy_inputs: [],
    labels: {
      "trust-gate" => "nix_runner_label",
      "check-blahaj-token" => "nix_runner_label",
      "lanes-load" => "nix_runner_label",
      "publish-image" => "dind_runner_label",
      "dispatch-apply" => "nix_runner_label",
      "tailnet-qa" => "kvm_runner_label",
      "destroy-lanes" => "nix_runner_label",
    },
    runner_env: {},
  },
}.freeze

def load_yaml(path)
  YAML.load_file(path, aliases: true)
rescue ArgumentError
  YAML.load_file(path)
end

def workflow_call(document)
  on_node = document["on"] || document[true]
  on_node.is_a?(Hash) ? on_node["workflow_call"] : nil
end

def deep_copy(value)
  Marshal.load(Marshal.dump(value))
end

def canonical_document(value)
  case value
  when Hash
    value.map { |key, child| [key.to_s, canonical_document(child)] }.sort.to_h
  when Array
    value.map { |child| canonical_document(child) }
  else
    value
  end
end

def scanner_document_sha256(scanner)
  Digest::SHA256.hexdigest(JSON.generate(canonical_document(scanner)))
end

def expected_restricted_cache_description(legacy_description)
  legacy_description
    .sub(
      "switch their Nix setup to nix-setup@v2",
      "switch their Nix setup to exact release-vendored nix-setup@#{IMMUTABLE_RELEASE}"
    )
    .sub(
      "validate tinyland.repo.json and assert shared-cache attachment via scripts/cache-attachment-contract.sh " \
      "(fail-closed: contract --strict)",
      "validate tinyland.repo.json and invoke exact release-vendored " \
      "cache-attachment-validate@#{IMMUTABLE_RELEASE}, which executes its vendored " \
      "scripts/cache-attachment-contract.sh --strict"
    )
end

def scanner_install_step(scanner, step_name)
  Array(scanner.dig("runs", "steps")).find do |step|
    step.is_a?(Hash) && step["name"] == step_name
  end
end

def active_shell_lines(run)
  run.lines.map(&:strip).reject { |line| line.empty? || line.start_with?("#") }
end

def expected_scanner_install_lines(spec)
  checksum = %q{printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check --status}
  [
    "set -euo pipefail",
    'BIN_DIR="${RUNNER_TEMP:-/tmp}/secrets-scan-bin"',
    'mkdir -p "$BIN_DIR"',
    %(version="$#{spec[:version_env]}"),
    %(expected_sha256="$#{spec[:sha_env]}"),
    '[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {',
    %(echo "::error::invalid #{spec[:display_name]} version: $version"; exit 64;),
    "}",
    '[[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || {',
    %(echo "::error::invalid #{spec[:display_name]} SHA-256"; exit 64;),
    "}",
    spec[:archive],
    "curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \\",
    spec[:url],
    '--output "$archive"',
    checksum,
    %(tar --extract --gzip --file "$archive" --directory "$BIN_DIR" #{spec[:member]}),
    %(chmod 0755 "$BIN_DIR/#{spec[:member]}"),
    'echo "$BIN_DIR" >> "$GITHUB_PATH"',
  ]
end

def scanner_install_errors(scanner, spec)
  errors = []
  step = scanner_install_step(scanner, spec[:step])
  unless step
    return ["secrets-scan is missing #{spec[:step]} step"]
  end

  expected_env = {
    spec[:version_env] => "${{ inputs.#{spec[:version_input]} }}",
    spec[:sha_env] => "${{ inputs.#{spec[:sha_input]} }}",
  }
  unless step["env"] == expected_env
    errors << "secrets-scan #{spec[:step]} must bind the exact version and digest inputs"
  end

  run = step["run"].to_s
  lines = active_shell_lines(run)
  errors << "secrets-scan #{spec[:step]} must begin fail-closed with set -euo pipefail" unless lines.first == "set -euo pipefail"
  if lines.any? { |line| line.match?(/\A(?:set \+e|set \+o pipefail|if|then|else|elif|fi|while|until|for|case|esac)\b/) }
    errors << "secrets-scan #{spec[:step]} must not conditionally bypass archive verification"
  end

  expected_assignments = [
    %(version="$#{spec[:version_env]}"),
    %(expected_sha256="$#{spec[:sha_env]}"),
    spec[:archive],
  ]
  assignments = lines.select { |line| line.match?(/\A(?:version|expected_sha256|archive)=/) }
  unless assignments == expected_assignments
    errors << "secrets-scan #{spec[:step]} must bind version, digest, and archive exactly once"
  end

  unless lines == expected_scanner_install_lines(spec)
    errors << "secrets-scan #{spec[:step]} must retain the single exact validated download, digest, extraction, chmod, and PATH sequence"
  end

  version_guard = '[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {'
  digest_guard = '[[ "$expected_sha256" =~ ^[0-9a-f]{64}$ ]] || {'
  checksum = %q{printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check --status}
  extraction = %(tar --extract --gzip --file "$archive" --directory "$BIN_DIR" #{spec[:member]})
  chmod = %(chmod 0755 "$BIN_DIR/#{spec[:member]}")
  integrity_block = [
    spec[:archive],
    "curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \\",
    spec[:url],
    '--output "$archive"',
    checksum,
    extraction,
    chmod,
  ]
  block_starts = []
  lines.each_index do |index|
    block_starts << index if lines[index, integrity_block.length] == integrity_block
  end
  if block_starts.length != 1
    errors << "secrets-scan #{spec[:step]} must download to the bound archive, verify its exact digest, then extract one member and chmod"
  else
    block_start = block_starts.first
    version_assignment = lines.index(expected_assignments[0])
    digest_assignment = lines.index(expected_assignments[1])
    version_guard_index = lines.index(version_guard)
    digest_guard_index = lines.index(digest_guard)
    ordered_prefix = [version_assignment, digest_assignment, version_guard_index, digest_guard_index, block_start]
    unless ordered_prefix.none?(&:nil?) && ordered_prefix == ordered_prefix.sort
      errors << "secrets-scan #{spec[:step]} must validate bound version and digest before download/extraction"
    end
  end

  errors
end

def scanner_integrity_errors(scanner)
  errors = []
  steps = scanner.dig("runs", "steps")
  actual_step_names = Array(steps).map do |step|
    step.is_a?(Hash) ? step["name"] : nil
  end
  unless steps.is_a?(Array) && actual_step_names == EXPECTED_SCANNER_STEP_NAMES
    errors << "secrets-scan must retain the exact reviewed step list with no adjacent download, extraction, or execution path"
  end

  actual_digest = scanner_document_sha256(scanner)
  unless actual_digest == EXPECTED_SCANNER_DOCUMENT_SHA256
    errors << "secrets-scan complete composite document changed: expected #{EXPECTED_SCANNER_DOCUMENT_SHA256}, got #{actual_digest}"
  end

  errors.concat(SCANNER_INSTALL_SPECS.flat_map { |spec| scanner_install_errors(scanner, spec) })
  errors
end

def scanner_integrity_oracle_errors(scanner)
  errors = []
  checksum = %q{printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check --status}
  SCANNER_INSTALL_SPECS.each do |spec|
    extraction = %(tar --extract --gzip --file "$archive" --directory "$BIN_DIR" #{spec[:member]})
    mutations = {
      "missing checksum" => ->(run) { run.sub("#{checksum}\n", "") },
      "bypassed checksum" => ->(run) { run.sub(checksum, "true # #{checksum}") },
      "decoupled archive" => ->(run) { run.sub(checksum, checksum.sub('"$archive"', '"$BIN_DIR/unbound.tar.gz"')) },
      "extraction before checksum" => ->(run) { run.sub("#{checksum}\n#{extraction}", "#{extraction}\n#{checksum}") },
      "duplicate unverified curl+tar path" => lambda do |run|
        alternate = <<~SHELL
          curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \\
            #{spec[:url]}
            --output "$BIN_DIR/unverified-#{spec[:member]}.tar.gz"
          tar --extract --gzip --file "$BIN_DIR/unverified-#{spec[:member]}.tar.gz" --directory "$BIN_DIR" #{spec[:member]}
        SHELL
        run.sub(spec[:archive], "#{alternate}#{spec[:archive]}")
      end,
      "alternate downloaded binary execution" => lambda do |run|
        run.sub(extraction, "#{extraction}\n\"$BIN_DIR/#{spec[:member]}\" --version")
      end,
    }
    mutations.each do |label, mutate|
      mutant = deep_copy(scanner)
      step = scanner_install_step(mutant, spec[:step])
      original = step["run"].to_s
      step["run"] = mutate.call(original)
      if step["run"] == original
        errors << "secrets-scan negative oracle could not construct #{spec[:step]} #{label} mutation"
      elsif scanner_install_errors(mutant, spec).empty?
        errors << "secrets-scan negative oracle accepted #{spec[:step]} #{label}"
      end
    end
  end

  adjacent_mutations = {
    "duplicate exact install step" => lambda do |mutant|
      steps = mutant.dig("runs", "steps")
      steps << deep_copy(scanner_install_step(mutant, SCANNER_INSTALL_SPECS.first[:step]))
    end,
    "adjacent unverified download-extract-execute step" => lambda do |mutant|
      mutant.dig("runs", "steps") << {
        "name" => "Unverified scanner path",
        "shell" => "bash",
        "run" => <<~SHELL,
          curl --location https://example.invalid/scanner.tar.gz --output scanner.tar.gz
          tar --extract --gzip --file scanner.tar.gz
          ./scanner --version
        SHELL
      }
    end,
    "adjacent execution-only step" => lambda do |mutant|
      mutant.dig("runs", "steps") << {
        "name" => "Alternate scanner execution",
        "shell" => "bash",
        "run" => "${RUNNER_TEMP:-/tmp}/secrets-scan-bin/trufflehog --version\n",
      }
    end,
  }
  adjacent_mutations.each do |label, mutate|
    mutant = deep_copy(scanner)
    original = scanner_document_sha256(mutant)
    mutate.call(mutant)
    if scanner_document_sha256(mutant) == original
      errors << "secrets-scan negative oracle could not construct #{label} mutation"
    elsif scanner_integrity_errors(mutant).empty?
      errors << "secrets-scan negative oracle accepted #{label}"
    end
  end
  errors
end

def cache_attachment_step(action)
  steps = action.dig("runs", "steps")
  return nil unless steps.is_a?(Array) && steps.length == 1

  steps.first
end

def expected_cache_attachment_lines
  [
    "set -euo pipefail",
    'contract="${{ github.action_path }}/../../../scripts/cache-attachment-contract.sh"',
    'if [[ ! -f "$contract" ]]; then',
    'echo "::error::release-vendored cache attachment contract is missing: $contract"',
    "exit 1",
    "fi",
    'declared_mode=""',
    "if [[ -f tinyland.repo.json ]]; then",
    'declared_mode="$(jq -r \'.enrollment.substrateMode // empty\' tinyland.repo.json)"',
    "fi",
    'if [[ -z "$declared_mode" ]]; then',
    'declared_mode="$SUBSTRATE_MODE_INPUT"',
    "fi",
    'export GF_BAZEL_SUBSTRATE_MODE="${declared_mode:-shared-cache-backed}"',
    'export GF_FLYWHEEL_PROFILE_STATE="$GF_BAZEL_SUBSTRATE_MODE"',
    'export GF_BAZEL_RUNNER_LABELS="$RUNNER_LABELS"',
    'echo "GF_FLYWHEEL_PROFILE_STATE=$GF_FLYWHEEL_PROFILE_STATE" >> "$GITHUB_ENV"',
    'echo "::notice::cache-backed lane expected mode (manifest-driven): $GF_BAZEL_SUBSTRATE_MODE"',
    'echo "::notice::Flywheel profile state: $GF_FLYWHEEL_PROFILE_STATE"',
    'bash "$contract" --strict',
  ]
end

def cache_attachment_errors(action)
  errors = []
  inputs = action["inputs"]
  unless inputs.is_a?(Hash) && inputs.keys.sort == %w[runner_labels substrate_mode]
    errors << "cache attachment action must declare only substrate_mode and runner_labels inputs"
  end
  unless inputs.is_a?(Hash) &&
         inputs.dig("substrate_mode", "required") == false &&
         inputs.dig("substrate_mode", "default") == "" &&
         inputs.dig("runner_labels", "required") == true &&
         !inputs.fetch("runner_labels", {}).key?("default")
    errors << "cache attachment inputs must retain the exact optional mode and required label contract"
  end

  runs = action["runs"]
  unless runs.is_a?(Hash) && runs.keys.sort == %w[steps using] && runs["using"] == "composite"
    errors << "cache attachment action must be one exact composite step sequence"
  end
  step = cache_attachment_step(action)
  unless step.is_a?(Hash)
    errors << "cache attachment action must contain exactly one validation step"
    return errors
  end

  unless step.keys.sort == %w[env name run shell] &&
         step["name"] == "Assert cache attachment" &&
         step["shell"] == "bash"
    errors << "cache attachment validation step must have the exact name, Bash shell, env, and run shape"
  end
  expected_env = {
    "SUBSTRATE_MODE_INPUT" => "${{ inputs.substrate_mode }}",
    "RUNNER_LABELS" => "${{ inputs.runner_labels }}",
  }
  unless step["env"] == expected_env
    errors << "cache attachment validation step must bind the exact mode and runner-label inputs"
  end
  unless active_shell_lines(step["run"].to_s) == expected_cache_attachment_lines
    errors << "cache attachment validation must retain the exact fail-closed path, mode/label exports, and unconditional strict execution sequence"
  end
  errors
end

def cache_attachment_oracle_errors(action)
  execution = 'bash "$contract" --strict'
  export_labels = 'export GF_BAZEL_RUNNER_LABELS="$RUNNER_LABELS"'
  mutations = {
    "missing execution" => ->(mutant) { cache_attachment_step(mutant)["run"].sub!("#{execution}\n", "") },
    "missing strict mode" => ->(mutant) { cache_attachment_step(mutant)["run"].sub!(execution, 'bash "$contract"') },
    "decoupled contract path" => lambda do |mutant|
      cache_attachment_step(mutant)["run"].sub!(
        '${{ github.action_path }}/../../../scripts/cache-attachment-contract.sh',
        '$GITHUB_WORKSPACE/scripts/cache-attachment-contract.sh'
      )
    end,
    "missing runner-label input" => ->(mutant) { mutant["inputs"].delete("runner_labels") },
    "missing substrate-mode input" => ->(mutant) { mutant["inputs"].delete("substrate_mode") },
    "missing substrate input binding" => ->(mutant) { cache_attachment_step(mutant)["env"].delete("SUBSTRATE_MODE_INPUT") },
    "missing runner-label env binding" => ->(mutant) { cache_attachment_step(mutant)["env"].delete("RUNNER_LABELS") },
    "missing runner-label export" => ->(mutant) { cache_attachment_step(mutant)["run"].sub!("#{export_labels}\n", "") },
    "conditional strict execution" => lambda do |mutant|
      cache_attachment_step(mutant)["run"].sub!(execution, "if false; then\n  #{execution}\nfi")
    end,
    "alternate non-strict execution" => lambda do |mutant|
      cache_attachment_step(mutant)["run"].sub!(execution, "bash \"$contract\"\n#{execution}")
    end,
    "alternate bypass step" => lambda do |mutant|
      mutant.dig("runs", "steps") << { "name" => "Alternate", "shell" => "bash", "run" => "true" }
    end,
  }

  mutations.each_with_object([]) do |(label, mutate), errors|
    mutant = deep_copy(action)
    before = deep_copy(mutant)
    mutate.call(mutant)
    if mutant == before
      errors << "cache attachment negative oracle could not construct #{label} mutation"
    elsif cache_attachment_errors(mutant).empty?
      errors << "cache attachment negative oracle accepted #{label}"
    end
  end
end

def checkout_step?(step)
  step.is_a?(Hash) && step["uses"].to_s.start_with?("actions/checkout@")
end

def expected_trust_if(spec)
  route_terms = spec[:inputs].map do |input, value|
    "inputs.#{input} == '#{value}'"
  end
  <<~EXPR.gsub(/\s+/, " ").strip
    ${{ github.event.repository.private == true &&
        ((github.event_name != 'pull_request' && github.event_name != 'pull_request_target') ||
        github.event.pull_request.head.repo.full_name == github.repository) &&
        #{route_terms.join(" && ")} }}
  EXPR
end

def preschedule_admissible?(spec, private_repo:, event_name:, same_repo:, route:)
  trusted_event = !%w[pull_request pull_request_target].include?(event_name) || same_repo
  private_repo && trusted_event && spec[:inputs].all? { |input, value| route[input] == value }
end

def validate_restricted(name, document, legacy, spec)
  errors = []
  call = workflow_call(document)
  legacy_call = workflow_call(legacy)
  inputs = call.is_a?(Hash) && call["inputs"].is_a?(Hash) ? call["inputs"] : {}
  jobs = document["jobs"]

  errors << "#{name}: missing workflow_call inputs" if inputs.empty?
  errors << "#{name}: missing jobs mapping" unless jobs.is_a?(Hash)
  return errors unless jobs.is_a?(Hash)

  spec[:inputs].each_key do |input|
    declaration = inputs[input]
    if !declaration.is_a?(Hash) || declaration["required"] != true || declaration.key?("default")
      errors << "#{name}: #{input} must be a required caller input with no default"
    end
  end
  spec[:removed_legacy_inputs].each do |input|
    errors << "#{name}: legacy dynamic routing input #{input} must be absent" if inputs.key?(input)
  end
  if name == "spoke-ci"
    legacy_description = legacy_call.dig("inputs", "cache_backed", "description").to_s
    expected_description = expected_restricted_cache_description(legacy_description)
    actual_description = inputs.dig("cache_backed", "description").to_s
    unless actual_description == expected_description
      errors << "#{name}: cache_backed description must name the exact release-vendored setup and attachment contract"
    end
  end

  expected_jobs = spec[:labels].keys.sort
  actual_jobs = jobs.keys.sort
  errors << "#{name}: jobs differ from the reviewed set" unless actual_jobs == expected_jobs

  jobs.each do |job_name, job|
    unless job.is_a?(Hash)
      errors << "#{name}: #{job_name} is not a job mapping"
      next
    end
    route = job["runs-on"]
    unless route.is_a?(Hash) && route.keys.sort == %w[group labels]
      errors << "#{name}: #{job_name} runs-on must be exactly a group+labels mapping"
      next
    end
    errors << "#{name}: #{job_name} group must use runner_group" unless route["group"] == GROUP_EXPR
    expected_label = "${{ inputs.#{spec[:labels][job_name]} }}"
    errors << "#{name}: #{job_name} label must use #{expected_label}" unless route["labels"] == expected_label

    next if job_name == TRUST_JOB

    needs = job["needs"].is_a?(Array) ? job["needs"] : [job["needs"]].compact
    errors << "#{name}: #{job_name} must directly depend on #{TRUST_JOB}" unless needs.include?(TRUST_JOB)
    if job["if"].to_s.match?(/\b(?:always|failure|cancelled)\s*\(/)
      errors << "#{name}: #{job_name} must not bypass a skipped trust gate with a status function"
    end
  end

  spec[:runner_env].each do |job_name, input|
    values = Array(jobs.dig(job_name, "steps")).map do |step|
      next unless step.is_a?(Hash)

      step.dig("env", "RUNNER_LABELS") || step.dig("with", "runner_labels")
    end.compact
    expected = "${{ inputs.#{input} }}"
    errors << "#{name}: #{job_name} cache contract must consume #{expected}" unless values == [expected]
  end

  trust = jobs[TRUST_JOB]
  if trust.is_a?(Hash)
    condition = trust["if"].to_s.gsub(/\s+/, " ").strip
    expected_condition = expected_trust_if(spec)
    unless condition == expected_condition
      errors << "#{name}: trust gate condition must exactly match private same-repo and pre-scheduling route policy"
    end
    %w[pull_request pull_request_target event.repository.private head.repo.full_name github.repository].each do |token|
      errors << "#{name}: trust gate is missing #{token} fork guard" unless condition.include?(token)
    end
    errors << "#{name}: trust gate must not check out caller content" if Array(trust["steps"]).any? { |step| checkout_step?(step) }
    gate_script = Array(trust["steps"]).map { |step| step.is_a?(Hash) ? step["run"] : nil }.compact.join("\n")
    required_gate_snippets = [
      "default|shared|github-actions|github-hosted|self-hosted",
      'group" == "tinyland-infra',
      'NIX_RUNNER_LABEL" == "tinyland-nix',
    ]
    spec[:inputs].each do |input, capability|
      next if input == "runner_group" || input == "nix_runner_label"

      env_name = input.upcase
      required_gate_snippets << "#{env_name}\" == \"#{capability}"
    end
    required_gate_snippets.each do |snippet|
      errors << "#{name}: trust gate is missing fail-closed check #{snippet}" unless gate_script.include?(snippet)
    end
  end

  # Strip the reviewed routing/trust delta plus the exact dependency-closure
  # pins. Everything else—permissions, matrices, step behavior, cache behavior,
  # and ownership boundaries—must remain structurally equal to the legacy
  # workflow.
  normalized = deep_copy(document)
  normalized["name"] = legacy["name"]
  normalized_call = workflow_call(normalized)
  normalized_inputs = normalized_call["inputs"]
  if name == "spoke-ci"
    normalized_inputs["cache_backed"]["description"] = legacy_call.dig("inputs", "cache_backed", "description")
  end
  # Strip the reviewed routing inputs from the structural comparison. Since
  # TIN-3902 the legacy workflow also declares `runner_group` (optional,
  # default ""); the restricted variant's reviewed delta for such a name is
  # exactly that it is REQUIRED with no default, already asserted above. So
  # restore the legacy declaration rather than deleting it — the rest of the
  # inputs surface must still be structurally equal.
  legacy_inputs = legacy_call.is_a?(Hash) && legacy_call["inputs"].is_a?(Hash) ? legacy_call["inputs"] : {}
  spec[:inputs].each_key do |input|
    if legacy_inputs.key?(input)
      normalized_inputs[input] = deep_copy(legacy_inputs[input])
    else
      normalized_inputs.delete(input)
    end
  end
  spec[:removed_legacy_inputs].each do |input|
    normalized_inputs[input] = deep_copy(legacy_call["inputs"][input])
  end
  normalized_jobs = normalized["jobs"]
  normalized_jobs.delete(TRUST_JOB)
  legacy["jobs"].each do |job_name, legacy_job|
    job = normalized_jobs[job_name]
    next unless job.is_a?(Hash)

    job["runs-on"] = deep_copy(legacy_job["runs-on"])
    needs = job["needs"].is_a?(Array) ? job["needs"].dup : [job["needs"]].compact
    needs.delete(TRUST_JOB)
    if legacy_job.key?("needs")
      job["needs"] = needs
    else
      job.delete("needs")
    end
    # The restricted variant can use its already-reviewed capability input
    # directly instead of the unsupported `runner.labels` context. Normalize
    # that routing-only expression back for the semantic comparison.
    restricted_steps = Array(job["steps"])
    legacy_steps = Array(legacy_job["steps"])
    restricted_steps.each_index do |index|
      restricted_step = restricted_steps[index]
      legacy_step = legacy_steps[index]
      next unless restricted_step.is_a?(Hash) && legacy_step.is_a?(Hash)

      # The restricted release closes the old inline network fetch by invoking
      # the release-vendored composite. Normalize that immutability-only delta
      # back to the byte-pinned legacy step for the semantic comparison.
      if legacy_step["name"].to_s.start_with?("Assert shared-cache attachment") &&
         restricted_step["uses"] == "tinyland-inc/ci-templates/.github/actions/cache-attachment-validate@#{IMMUTABLE_RELEASE}"
        restricted_steps[index] = deep_copy(legacy_step)
        next
      end

      restricted_uses = restricted_step["uses"].to_s
      legacy_uses = legacy_step["uses"].to_s
      if restricted_uses == "actions/checkout@#{CHECKOUT_SHA}" && legacy_uses == "actions/checkout@v6"
        restricted_step["uses"] = legacy_uses
      elsif restricted_uses.match?(%r{\Atinyland-inc/ci-templates/.+@#{Regexp.escape(IMMUTABLE_RELEASE)}\z}) &&
            legacy_uses == restricted_uses.sub("@#{IMMUTABLE_RELEASE}", "@v2")
        restricted_step["uses"] = legacy_uses
      end

      if legacy_step.dig("env", "RUNNER_LABELS") == "${{ join(runner.labels, ',') }}"
        restricted_step["env"]["RUNNER_LABELS"] = legacy_step["env"]["RUNNER_LABELS"]
      end
      # Quote the target list through a Bash array in the restricted copy. The
      # argv is unchanged; this only makes the copied lane shellcheck-clean.
      if legacy_step["name"] == "Validate Bazel targets (cache-backed)"
        restricted_step["run"] = legacy_step["run"]
      end
    end
  end
  errors << "#{name}: restricted workflow drifted beyond reviewed routing/trust/immutability delta" unless normalized == legacy

  errors
end

def collect_uses(document)
  uses = []
  walk = lambda do |node|
    case node
    when Hash
      node.each do |key, value|
        uses << value if key == "uses" && value.is_a?(String)
        walk.call(value)
      end
    when Array
      node.each { |value| walk.call(value) }
    end
  end
  walk.call(document)
  uses
end

def validate_immutable_ref(uses)
  internal = uses.match(%r{\Atinyland-inc/ci-templates/\.github/actions/([^@\s]+)@(.+)\z})
  if internal
    action, ref = internal.captures
    return "internal action #{action} must use @#{IMMUTABLE_RELEASE}, got @#{ref}" unless ref == IMMUTABLE_RELEASE

    return nil
  end

  return "local action refs are not deterministic in a called workflow: #{uses}" if uses.start_with?("./")
  return nil if uses.start_with?("docker://")

  _owner_action, ref = uses.split("@", 2)
  return "third-party action must use a full commit SHA: #{uses}" unless ref&.match?(/\A[0-9a-f]{40}\z/)

  nil
end

def validate_restricted_dependency_closure
  errors = []
  queue = SPECS.values.map { |spec| File.join(ROOT, spec[:restricted]) }
  visited = {}
  action_names = []

  until queue.empty?
    path = queue.shift
    next if visited[path]

    visited[path] = true
    document = load_yaml(path)
    collect_uses(document).each do |uses|
      if (error = validate_immutable_ref(uses))
        errors << "#{Pathname.new(path).relative_path_from(Pathname.new(ROOT))}: #{error}"
      end

      match = uses.match(%r{\Atinyland-inc/ci-templates/\.github/actions/([^@\s]+)@})
      next unless match

      action = match[1]
      action_path = File.join(ROOT, ".github/actions", action, "action.yml")
      unless File.file?(action_path)
        errors << "restricted closure references missing action .github/actions/#{action}/action.yml"
        next
      end
      action_names << action
      queue << action_path
    end
  end

  actual_actions = action_names.uniq.sort
  if actual_actions != EXPECTED_CLOSURE_ACTIONS
    errors << "restricted action closure changed: expected #{EXPECTED_CLOSURE_ACTIONS.join(', ')}, got #{actual_actions.join(', ')}"
  end

  expected_external = [
    "actions/checkout@#{CHECKOUT_SHA}",
    "DeterminateSystems/determinate-nix-action@#{DETERMINATE_NIX_SHA}",
  ].sort
  actual_external = visited.keys.flat_map { |path| collect_uses(load_yaml(path)) }
                           .reject { |uses| uses.start_with?("tinyland-inc/ci-templates/") }
                           .uniq.sort
  if actual_external != expected_external
    errors << "restricted external action closure changed: expected #{expected_external.join(', ')}, got #{actual_external.join(', ')}"
  end

  closure_text = visited.keys.map { |path| File.read(path) }.join("\n")
  %w[trufflehog/main scripts/install.sh raw.githubusercontent.com/tinyland-inc/ci-templates].each do |forbidden|
    errors << "restricted closure retains mutable network dependency #{forbidden}" if closure_text.include?(forbidden)
  end
  errors << "restricted closure retains curl-to-shell execution" if closure_text.match?(/curl[^\n]*(?:\n[^\n]*)?\|\s*(?:sh|bash)\b/)
  errors << "restricted closure retains curl-to-tar execution" if closure_text.match?(/curl[^\n]*(?:\n[^\n]*)?\|\s*tar\b/)

  scanner_path = File.join(ROOT, ".github/actions/secrets-scan/action.yml")
  scanner = load_yaml(scanner_path)
  scanner_inputs = scanner["inputs"] || {}
  expected_scanner_defaults = {
    "trufflehog-version" => "3.95.3",
    "trufflehog-sha256" => "5d836eae522540a32ca0f1a1e00efd4c3153a52462466a4b4008fac1e6c1a548",
    "gitleaks-version" => "8.30.1",
    "gitleaks-sha256" => "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb",
  }
  expected_scanner_defaults.each do |input, expected|
    actual = scanner_inputs.dig(input, "default").to_s
    errors << "secrets-scan #{input} must default to #{expected}, got #{actual}" unless actual == expected
  end
  errors.concat(scanner_integrity_errors(scanner))
  errors.concat(scanner_integrity_oracle_errors(scanner))

  attachment_path = File.join(ROOT, ".github/actions/cache-attachment-validate/action.yml")
  attachment = load_yaml(attachment_path)
  errors.concat(cache_attachment_errors(attachment))
  errors.concat(cache_attachment_oracle_errors(attachment))

  # Negative oracles prove the ref classifier rejects each historical escape.
  {
    "floating internal major" => "tinyland-inc/ci-templates/.github/actions/setup-nix@v2",
    "mutable internal branch" => "tinyland-inc/ci-templates/.github/actions/setup-nix@main",
    "third-party major" => "actions/checkout@v6",
    "consumer-relative local action" => "./.github/actions/setup-nix",
  }.each do |label, uses|
    errors << "immutable-ref negative oracle accepted #{label}" if validate_immutable_ref(uses).nil?
  end
  errors << "immutable-ref positive oracle rejected checkout SHA" if validate_immutable_ref("actions/checkout@#{CHECKOUT_SHA}")
  errors << "immutable-ref positive oracle rejected exact self release" if validate_immutable_ref("tinyland-inc/ci-templates/.github/actions/setup-nix@#{IMMUTABLE_RELEASE}")

  errors
end

def preschedule_route_oracles(name, spec)
  valid = spec[:inputs].dup
  errors = []
  unless preschedule_admissible?(spec, private_repo: true, event_name: "pull_request", same_repo: true, route: valid)
    errors << "#{name}: legitimate private same-repo pull_request route was not admitted"
  end
  unless preschedule_admissible?(spec, private_repo: true, event_name: "workflow_dispatch", same_repo: false, route: valid)
    errors << "#{name}: legitimate private non-PR workflow_call route was not admitted"
  end
  if preschedule_admissible?(spec, private_repo: false, event_name: "pull_request", same_repo: true, route: valid)
    errors << "#{name}: public repository route was admitted before scheduling"
  end
  if preschedule_admissible?(spec, private_repo: true, event_name: "pull_request", same_repo: false, route: valid)
    errors << "#{name}: fork route was admitted before scheduling"
  end

  ["Default", "default", "shared", "GitHub Actions", "github-actions", "github-hosted",
   "ubuntu-latest", "self-hosted", "site-scaffold-infra"].each do |group|
    route = valid.merge("runner_group" => group)
    if preschedule_admissible?(spec, private_repo: true, event_name: "pull_request", same_repo: true, route: route)
      errors << "#{name}: inadmissible group #{group.inspect} was admitted before scheduling"
    end
  end
  spec[:inputs].each do |input, expected|
    next if input == "runner_group"

    ["ubuntu-latest", "site-scaffold-nix", "#{expected}-wrong"].each do |label|
      route = valid.merge(input => label)
      if preschedule_admissible?(spec, private_repo: true, event_name: "pull_request", same_repo: true, route: route)
        errors << "#{name}: inadmissible #{input}=#{label.inspect} was admitted before scheduling"
      end
    end
  end
  errors
end

def negative_oracles(name, document, legacy, spec)
  cases = []

  scalar = deep_copy(document)
  scalar["jobs"].values.first["runs-on"] = "tinyland-nix"
  cases << ["scalar runs-on", scalar]

  hosted = deep_copy(document)
  hosted["jobs"].values.first["runs-on"]["labels"] = "ubuntu-latest"
  cases << ["hosted label", hosted]

  default_group = deep_copy(document)
  default_group["jobs"].values.first["runs-on"]["group"] = "Default"
  cases << ["Default group", default_group]

  no_trust_dependency = deep_copy(document)
  downstream = no_trust_dependency["jobs"].keys.find { |job| job != TRUST_JOB }
  no_trust_dependency["jobs"][downstream].delete("needs")
  cases << ["missing trust dependency", no_trust_dependency]

  always_bypass = deep_copy(document)
  always_bypass["jobs"][downstream]["if"] = "${{ always() }}"
  cases << ["always() trust bypass", always_bypass]

  checkout_gate = deep_copy(document)
  checkout_gate["jobs"][TRUST_JOB]["steps"] << { "uses" => "actions/checkout@v6" }
  cases << ["checkout in trust gate", checkout_gate]

  permissive_gate = deep_copy(document)
  permissive_gate["jobs"][TRUST_JOB]["if"] = "${{ true }}"
  cases << ["permissive trust condition", permissive_gate]

  defaulted_input = deep_copy(document)
  workflow_call(defaulted_input)["inputs"]["runner_group"]["default"] = "tinyland-infra"
  cases << ["defaulted group input", defaulted_input]

  if name == "spoke-ci"
    stale_description = deep_copy(document)
    workflow_call(stale_description)["inputs"]["cache_backed"]["description"] =
      workflow_call(legacy).dig("inputs", "cache_backed", "description")
    cases << ["stale mutable cache description", stale_description]
  end

  failures = cases.map do |label, mutant|
    label if validate_restricted(name, mutant, legacy, spec).empty?
  end.compact
  failures.map { |label| "#{name}: negative oracle was not rejected: #{label}" }
end

def runtime_gate_oracles(name, document, spec)
  trust = document.dig("jobs", TRUST_JOB)
  script = Array(trust["steps"]).map { |step| step.is_a?(Hash) ? step["run"] : nil }.compact.join("\n")
  valid_env = spec[:inputs].each_with_object({}) do |(input, value), env|
    env[input.upcase] = value
  end

  errors = []
  _out, err, status = Open3.capture3(valid_env, "bash", "-c", script)
  errors << "#{name}: valid private group+capabilities failed gate: #{err.strip}" unless status.success?

  mutations = {
    "Default group" => ["RUNNER_GROUP", "Default"],
    "generic shared group" => ["RUNNER_GROUP", "shared"],
    "hosted group" => ["RUNNER_GROUP", "GitHub Actions"],
    "non-infra group" => ["RUNNER_GROUP", "application-ci"],
    "repo-shaped infra group" => ["RUNNER_GROUP", "site-scaffold-infra"],
    "hosted label" => ["NIX_RUNNER_LABEL", "ubuntu-latest"],
    "repo-shaped label" => ["NIX_RUNNER_LABEL", "site-scaffold-nix"],
  }
  mutations.each do |label, (key, value)|
    _bad_out, _bad_err, bad_status = Open3.capture3(valid_env.merge(key => value), "bash", "-c", script)
    errors << "#{name}: runtime gate accepted #{label}" if bad_status.success?
  end
  spec[:inputs].each do |input, _expected|
    next if input == "runner_group"

    _bad_out, _bad_err, bad_status = Open3.capture3(
      valid_env.merge(input.upcase => "site-scaffold-nix"), "bash", "-c", script
    )
    errors << "#{name}: runtime gate accepted repo-shaped #{input}" if bad_status.success?
  end
  errors
end

errors = []
errors.concat(validate_restricted_dependency_closure)
SPECS.each do |name, spec|
  legacy_path = File.join(ROOT, spec[:legacy])
  restricted_path = File.join(ROOT, spec[:restricted])
  actual_digest = Digest::SHA256.file(legacy_path).hexdigest
  if actual_digest != spec[:legacy_sha256]
    errors << "#{name}: legacy workflow bytes changed (#{actual_digest}); default-off proof invalid"
  end

  legacy = load_yaml(legacy_path)
  restricted = load_yaml(restricted_path)
  errors.concat(validate_restricted(name, restricted, legacy, spec))
  errors.concat(negative_oracles(name, restricted, legacy, spec))
  errors.concat(preschedule_route_oracles(name, spec))
  errors.concat(runtime_gate_oracles(name, restricted, spec))
end

if errors.empty?
  puts "restricted workflow contract passed (legacy bytes pinned; immutable closure and pre-scheduling/runtime negative oracles rejected)"
  exit 0
end

warn "restricted workflow contract FAILED:"
errors.each { |error| warn "- #{error}" }
exit 1

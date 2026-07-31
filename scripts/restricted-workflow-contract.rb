#!/usr/bin/env ruby
# frozen_string_literal: true

# Structural contract for the opt-in private-repository workflow variants.
# The variants may route only through an explicit owner -infra group plus an
# exact reviewed capability. The legacy shared workflows are checksum-pinned so
# adding this surface cannot silently change ~190 existing consumers.

require "digest"
require "open3"
require "yaml"

ROOT = File.expand_path("..", __dir__)
GROUP_EXPR = "${{ inputs.runner_group }}"
TRUST_JOB = "trust-gate"

SPECS = {
  "spoke-ci" => {
    legacy: ".github/workflows/spoke-ci.yml",
    restricted: ".github/workflows/spoke-ci-restricted.yml",
    legacy_sha256: "7595e40678a4a5209308b28bbbebd76c8fd6dc8eff0b75b6d34dc595b552cfe5",
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
    legacy_sha256: "759ebf6dfed8932e853ed6e03d47968d488e0ec867c245bb9a5fe2df0cd056ce",
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
      step.is_a?(Hash) ? step.dig("env", "RUNNER_LABELS") : nil
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

  # Strip only the reviewed routing/trust delta. Everything else—permissions,
  # matrices, steps, action pins, cache behavior, and ownership boundaries—must
  # remain structurally equal to the legacy workflow.
  normalized = deep_copy(document)
  normalized["name"] = legacy["name"]
  normalized_call = workflow_call(normalized)
  legacy_call = workflow_call(legacy)
  normalized_inputs = normalized_call["inputs"]
  spec[:inputs].each_key { |input| normalized_inputs.delete(input) }
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
    Array(job["steps"]).zip(Array(legacy_job["steps"])).each do |restricted_step, legacy_step|
      next unless restricted_step.is_a?(Hash) && legacy_step.is_a?(Hash)

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
  errors << "#{name}: restricted workflow drifted beyond reviewed routing/trust delta" unless normalized == legacy

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
  puts "restricted workflow contract passed (legacy bytes pinned; pre-scheduling, structural, and runtime negative oracles rejected)"
  exit 0
end

warn "restricted workflow contract FAILED:"
errors.each { |error| warn "- #{error}" }
exit 1

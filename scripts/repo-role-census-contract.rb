#!/usr/bin/env ruby
# frozen_string_literal: true

# repo-role-census-contract.rb — prove spoke-ci.yml's optional
# `allowed_repo_roles` input (TIN-3815) is a real default-off change
# (AGENTS.md rule 2), and that it reaches EVERY census site.
#
# The bug this input exists to fix was not that the census was wrong — it was
# that the allowlist was hardcoded at TWO independent sites, so a spoke could
# satisfy one and fail the other, and a fix applied to one site would look
# complete. That failure mode is the thing worth encoding, so this contract's
# primary assertion is a SITE CENSUS, not a value check: every step that invokes
# `repo-manifest-validate` must route through the input, and the count is pinned.
# Add a third census site without threading it and this fails.
#
# Four things proven, mechanically, offline:
#
#   (a) With `allowed_repo_roles` unset, every site renders byte-for-byte the
#       pre-TIN-3815 literal, pinned below (same discipline as the restricted
#       contract's `legacy_sha256` and the runner_group contract's baseline).
#   (b) With it set, every site renders exactly what the caller passed — the
#       value is threaded, never merged, rewritten, or partially applied.
#   (c) The site census: the pinned set of (workflow, job, step) triples is
#       exactly the set of `repo-manifest-validate` invocations present, and
#       each one routes through the input.
#   (d) `spoke-ci-restricted.yml` declares the same input and threads the same
#       sites, so the restricted variant stays a strict subset. The restricted
#       workflow contract compares the two files structurally, so a divergence
#       here would surface there too — but this states it directly, at the
#       granularity a reader can check by eye.

require "yaml"

ROOT = File.expand_path("..", __dir__)
LEGACY = File.join(ROOT, ".github/workflows/spoke-ci.yml")
RESTRICTED = File.join(ROOT, ".github/workflows/spoke-ci-restricted.yml")

INPUT_NAME = "allowed_repo_roles"

# The literal both sites hardcoded before TIN-3815, recorded from main @ 8a0e2d3.
# Never edit this to make a check pass: it IS the backward-compatibility
# baseline. Widening it is a default-behaviour change for ~190 consumers and
# needs its own review, not a one-word diff here.
LEGACY_ROLES = "static-spoke,static-spoke-scaffold"

# Every census site, pinned as (job, step name). `nil` step name = the step has
# no `name:` key (identified by position among the job's validate invocations).
CENSUS_SITES = [
  { job: "repo-manifest", step: nil },
  { job: "flywheel-build", step: "Validate repo manifest (cache-backed lane)" },
].freeze

VALIDATE_ACTION = %r{\Atinyland-inc/ci-templates/\.github/actions/repo-manifest-validate@}.freeze
EXPECTED_EXPRESSION = "${{ inputs.#{INPUT_NAME} }}"

def load_workflow(path)
  YAML.load_file(path, aliases: true)
rescue ArgumentError
  YAML.load_file(path)
end

def workflow_call(document)
  node = document["on"] || document[true]
  node.is_a?(Hash) ? node["workflow_call"] : nil
end

# Every step in the document that invokes the manifest validator, as
# { job:, step:, required_roles: }.
def census_sites(document)
  sites = []
  (document["jobs"] || {}).each do |job_name, job|
    next unless job.is_a?(Hash)

    Array(job["steps"]).each do |step|
      next unless step.is_a?(Hash) && step["uses"].to_s.match?(VALIDATE_ACTION)

      sites << {
        job: job_name,
        step: step["name"],
        required_roles: step.fetch("with", {})["required_roles"],
      }
    end
  end
  sites
end

# The slice of the GitHub expression language a `with:` value uses here: a bare
# `${{ inputs.<name> }}` reference, or a plain literal.
def render(value, inputs)
  text = value.to_s.strip
  match = /\A\$\{\{\s*inputs\.([A-Za-z0-9_-]+)\s*\}\}\z/.match(text)
  return text unless match

  inputs[match[1]]
end

def input_declaration_errors(document, name, require_default:)
  call = workflow_call(document)
  inputs = call.is_a?(Hash) ? call["inputs"] : nil
  declaration = inputs.is_a?(Hash) ? inputs[name] : nil
  return ["#{name} input is not declared"] unless declaration.is_a?(Hash)

  errors = []
  errors << "#{name} must be type: string" unless declaration["type"] == "string"
  if require_default && declaration["default"] != LEGACY_ROLES
    errors << "#{name} default is #{declaration["default"].inspect}; the pinned " \
              "pre-TIN-3815 baseline is #{LEGACY_ROLES.inspect} (re-record deliberately)"
  end
  errors
end

def check_sites(document, label)
  errors = []
  sites = census_sites(document)

  # (c) the site census itself.
  found = sites.map { |site| { job: site[:job], step: site[:step] } }
  expected = CENSUS_SITES.map { |site| { job: site[:job], step: site[:step] } }
  if found.sort_by { |s| [s[:job].to_s, s[:step].to_s] } != expected.sort_by { |s| [s[:job].to_s, s[:step].to_s] }
    errors << "#{label}: repo-manifest-validate call sites changed " \
              "(#{found.map { |s| "#{s[:job]}/#{s[:step] || "(unnamed)"}" }.join(", ")}); " \
              "a new census site must thread #{INPUT_NAME} and be pinned in CENSUS_SITES"
    return errors
  end

  sites.each do |site|
    where = "#{label}: #{site[:job]}/#{site[:step] || "(unnamed)"}"
    value = site[:required_roles]
    if value.nil?
      errors << "#{where}: census site passes no required_roles"
      next
    end
    unless value.to_s.strip == EXPECTED_EXPRESSION
      errors << "#{where}: required_roles is #{value.inspect}, expected #{EXPECTED_EXPRESSION} " \
                "(a hardcoded literal here is the TIN-3815 bug returning)"
      next
    end

    # (a) default path renders the pinned pre-TIN-3815 literal, byte-for-byte.
    unset = render(value, { INPUT_NAME => LEGACY_ROLES })
    unless unset == LEGACY_ROLES
      errors << "#{where}: with #{INPUT_NAME} unset rendered #{unset.inspect}, " \
                "pre-TIN-3815 rendered #{LEGACY_ROLES.inspect}"
    end

    # (b) opted path threads the caller's value verbatim.
    opted = "static-spoke,static-spoke-scaffold,app-stateful-spoke"
    got = render(value, { INPUT_NAME => opted })
    errors << "#{where}: with #{INPUT_NAME} set rendered #{got.inspect}, expected #{opted.inspect}" unless got == opted
  end
  errors
end

def check(legacy_doc, restricted_doc)
  errors = []
  errors.concat(input_declaration_errors(legacy_doc, INPUT_NAME, require_default: true)
                  .map { |e| "spoke-ci: #{e}" })
  errors.concat(check_sites(legacy_doc, "spoke-ci"))

  # (d) strict-subset parity.
  errors.concat(input_declaration_errors(restricted_doc, INPUT_NAME, require_default: true)
                  .map { |e| "spoke-ci-restricted: #{e}" })
  errors.concat(check_sites(restricted_doc, "spoke-ci-restricted"))
  errors
end

# ── negative oracles ────────────────────────────────────────────────────────

def deep_copy(value)
  Marshal.load(Marshal.dump(value))
end

def site_step(document, job, step_name)
  Array(document.dig("jobs", job, "steps")).find do |step|
    step.is_a?(Hash) && step["uses"].to_s.match?(VALIDATE_ACTION) && step["name"] == step_name
  end
end

def self_test
  legacy = load_workflow(LEGACY)
  restricted = load_workflow(RESTRICTED)

  mutants = {
    "one site left hardcoded (the exact TIN-3815 bug)" => lambda do
      mutant = deep_copy(legacy)
      site_step(mutant, "flywheel-build", "Validate repo manifest (cache-backed lane)")["with"]["required_roles"] =
        LEGACY_ROLES
      [mutant, restricted]
    end,
    "the other site left hardcoded" => lambda do
      mutant = deep_copy(legacy)
      site_step(mutant, "repo-manifest", nil)["with"]["required_roles"] = LEGACY_ROLES
      [mutant, restricted]
    end,
    "default silently widened" => lambda do
      mutant = deep_copy(legacy)
      workflow_call(mutant)["inputs"][INPUT_NAME]["default"] = "#{LEGACY_ROLES},app-stateful-spoke"
      [mutant, restricted]
    end,
    "default narrowed" => lambda do
      mutant = deep_copy(legacy)
      workflow_call(mutant)["inputs"][INPUT_NAME]["default"] = "static-spoke"
      [mutant, restricted]
    end,
    "input undeclared while sites reference it" => lambda do
      mutant = deep_copy(legacy)
      workflow_call(mutant)["inputs"].delete(INPUT_NAME)
      [mutant, restricted]
    end,
    "census site drops required_roles entirely" => lambda do
      mutant = deep_copy(legacy)
      site_step(mutant, "flywheel-build", "Validate repo manifest (cache-backed lane)").delete("with")
      [mutant, restricted]
    end,
    "a new census site is added without threading the input" => lambda do
      mutant = deep_copy(legacy)
      mutant["jobs"]["flywheel-test"]["steps"] << {
        "name" => "Validate repo manifest (new lane)",
        "uses" => "tinyland-inc/ci-templates/.github/actions/repo-manifest-validate@v2",
        "with" => { "required_roles" => LEGACY_ROLES },
      }
      [mutant, restricted]
    end,
    "restricted variant drifts from the legacy census" => lambda do
      mutant = deep_copy(restricted)
      site_step(mutant, "repo-manifest", nil)["with"]["required_roles"] = LEGACY_ROLES
      [legacy, mutant]
    end,
    "restricted variant drops the input declaration" => lambda do
      mutant = deep_copy(restricted)
      workflow_call(mutant)["inputs"].delete(INPUT_NAME)
      [legacy, mutant]
    end,
  }

  survivors = mutants.reject do |_label, build|
    legacy_doc, restricted_doc = build.call
    check(legacy_doc, restricted_doc).any?
  end.keys

  if survivors.empty?
    puts "repo-role census contract self-test passed (#{mutants.length} negative oracles rejected)"
    return 0
  end

  warn "repo-role census contract self-test FAILED — accepted:"
  survivors.each { |label| warn "- #{label}" }
  1
end

def main
  return self_test if ARGV.include?("--self-test")

  errors = check(load_workflow(LEGACY), load_workflow(RESTRICTED))
  if errors.empty?
    puts "repo-role census contract passed (#{CENSUS_SITES.length} census sites in each of " \
         "spoke-ci + spoke-ci-restricted route through #{INPUT_NAME}; unset renders the pinned " \
         "#{LEGACY_ROLES.inspect} byte-for-byte, set threads the caller's value verbatim)"
    return 0
  end

  warn "repo-role census contract FAILED:"
  errors.each { |error| warn "- #{error}" }
  1
end

exit(main) if $PROGRAM_NAME == __FILE__

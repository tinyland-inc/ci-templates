#!/usr/bin/env ruby
# frozen_string_literal: true

# no-hosted-runners.rb — TIN-3914 textual backstop.
#
# `lint-runs-on.rb` verdicts `runs-on` VALUES structurally. This is the blunt
# companion for every other place a runner label can hide and still reach a
# scheduler: a reusable-workflow input default, a `fromJSON` fallback string, a
# step env value, and — the one that actually bit us — a JSON SCHEMA that
# sanctions a hosted label as consumer data (`schemas/lanes.schema.json`'s
# `runnerClass` fed `spoke-ci`'s `matrix.lane.runner_class` straight into
# `runs-on`, invisible to any workflow-text linter).
#
# Two properties this replaced a `grep -rnE '(ubuntu|windows|macos)-'` for:
#
#   1. LABEL-AWARE, not substring-aware. The grep failed
#      `blacksmith-4vcpu-ubuntu-2204` (it embeds `ubuntu-2`) while passing
#      `namespace-profile-default` — two labels in the SAME third-party fleet,
#      opposite verdicts, decided by an accident of spelling. Tokens are
#      matched whole and classified by the shared taxonomy, so a third-party
#      managed fleet WARNs either way, exactly as `lint-runs-on.rb` and the
#      README say it should. `lint-runs-on.rb` stays the sole arbiter of which
#      names are admissible; this file only re-applies its taxonomy off-workflow.
#
#   2. CASE-INSENSITIVE. GitHub runner labels are case-insensitive, so
#      `Ubuntu-Latest` schedules on GitHub's fleet — and walked straight past
#      the old grep. The taxonomy regexes are `/i`, so this cannot recur.
#
# FAIL = a GitHub-hosted family label (ubuntu-*/macos-*/windows-*). WARN = a
# third-party managed hosted fleet (blacksmith-*, depot-*, …): not GitHub's
# infrastructure, not GF cache-fronted, and not named by the operator ruling.

require "optparse"
require_relative "runner_label_taxonomy"

T = RunnerLabelTaxonomy

# Surfaces that can carry a runner label into a scheduler: workflow/action YAML
# (runs-on, input defaults, env), the vendored JSON schemas that validate
# CONSUMER data, this repo's own manifest, and the bazelrc fragments.
SCAN_GLOBS = [
  ".github/**/*.yml",
  ".github/**/*.yaml",
  "schemas/*.json",
  "tinyland.repo.json",
  "bazelrc/*.bazelrc",
].freeze

# A runner-label-shaped token: alphanumeric/._ segments joined by hyphens,
# matched WHOLE. Matching whole tokens is the point — it is what makes
# `blacksmith-4vcpu-ubuntu-2204` one third-party label rather than a hosted
# `ubuntu-2204` sighting.
LABEL_TOKEN = /[A-Za-z][A-Za-z0-9_.]*(?:-[A-Za-z0-9_.]+)*/.freeze

def comment_line?(line)
  line.lstrip.start_with?("#")
end

def classify_line(line)
  return [[], []] if comment_line?(line)

  tokens = line.scan(LABEL_TOKEN).uniq
  [
    tokens.select { |token| T.github_hosted_label?(token) },
    tokens.select { |token| T.third_party_hosted_label?(token) },
  ]
end

def scan_files(root)
  SCAN_GLOBS.flat_map { |glob| Dir.glob(File.join(root, glob)) }.uniq.sort
end

def scan(root)
  failures = []
  warnings = []
  files = scan_files(root)
  files.each do |path|
    rel = path.sub("#{root}/", "")
    File.readlines(path).each_with_index do |line, index|
      hosted, third_party = classify_line(line)
      hosted.each { |label| failures << [rel, index + 1, label, line.strip] }
      third_party.each { |label| warnings << [rel, index + 1, label, line.strip] }
    end
  end
  [files, failures, warnings]
end

# ── self-test ───────────────────────────────────────────────────────────────

def self_test
  oracle = [
    ["    runs-on: ubuntu-latest", :fail, "plain hosted label"],
    ["    runs-on: Ubuntu-Latest", :fail, "MIXED CASE hosted label (the old grep passed this)"],
    ["    runs-on: UBUNTU-LATEST", :fail, "upper-case hosted label"],
    ["    runs-on: ubuntu-24.04", :fail, "pinned hosted image"],
    ["    runs-on: ubuntu-latest-4-cores", :fail, "hosted larger runner"],
    ["    runs-on: windows-11-arm", :fail, "hosted Windows family"],
    ["    runs-on: macos-15-xlarge", :fail, "hosted macOS family"],
    ["        default: '[\"ubuntu-latest\"]'", :fail, "hosted label in an input default"],
    ["{ \"const\": \"ubuntu-latest\" }", :fail, "hosted label sanctioned by a JSON schema (the B2 escape)"],
    ["  X: ${{ vars.R || '[\"ubuntu-latest\"]' }}", :fail, "hosted label in a fromJSON-style fallback"],
    ["    runs-on: blacksmith-4vcpu-ubuntu-2204", :warn,
     "third-party fleet whose NAME embeds ubuntu-2: WARN, not FAIL (the old grep failed it)"],
    ["    runs-on: namespace-profile-default", :warn,
     "third-party fleet with no hosted substring: WARN, not silent pass (the old grep passed it)"],
    ["    runs-on: depot-ubuntu-24.04", :warn, "third-party fleet"],
    ["    runs-on: tinyland-nix", :clean, "org capability class"],
    ["    runs-on: great-falls-tool-bus-nix", :clean, "tenant org capability class"],
    ["      pattern: \"^[a-z0-9][a-z0-9-]*-(nix|docker|dind)$\"", :clean, "capability pattern"],
    ["# runs-on: ubuntu-latest was retired by TIN-3914", :clean, "comment line is prose, not a schedulable value"],
    ["    description: GitHub-hosted runners are retired", :clean, "prose naming the policy, not a label"],
    ["      registry-url: https://registry.npmjs.org", :clean, "URL is not a label"],
  ]

  failures = []
  oracle.each do |line, expected, label|
    hosted, third_party = classify_line(line)
    got = if !hosted.empty? then :fail
          elsif !third_party.empty? then :warn
          else :clean
          end
    failures << "#{label}: #{line.strip.inspect} expected #{expected}, got #{got}" if got != expected
  end

  if failures.empty?
    puts "no-hosted-runners self-test passed (#{oracle.length} oracle cases)"
    return 0
  end

  warn "no-hosted-runners self-test FAILED:"
  failures.each { |failure| warn "- #{failure}" }
  1
end

# ── main ────────────────────────────────────────────────────────────────────

def main
  root = Dir.pwd
  self_test_only = false

  OptionParser.new do |o|
    o.banner = "Usage: no-hosted-runners.rb [options]"
    o.on("--root DIR", "Repo root to scan (default: cwd)") { |v| root = File.expand_path(v) }
    o.on("--self-test", "Run the embedded oracle and exit") { self_test_only = true }
  end.parse!

  return self_test if self_test_only

  files, failures, warnings = scan(root)

  warnings.each do |rel, line_no, label, text|
    puts "::warning file=#{rel},line=#{line_no}::third-party managed hosted fleet label #{label.inspect} " \
         "(not GitHub-hosted, not GF cache-fronted; WARN per TIN-3914): #{text}"
  end
  failures.each do |rel, line_no, label, text|
    warn "::error file=#{rel},line=#{line_no}::GitHub-hosted runner label #{label.inspect} " \
         "on a schedulable surface (TIN-3914): #{text}"
  end

  if failures.any?
    warn "no-hosted-runners: #{failures.length} GitHub-hosted label(s) across #{files.length} scanned file(s)"
    return 1
  end

  puts "no-hosted-runners: 0 GitHub-hosted labels, #{warnings.length} third-party-fleet WARN " \
       "across #{files.length} scanned file(s)"
  0
end

exit(main) if $PROGRAM_NAME == __FILE__

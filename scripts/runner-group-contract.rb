#!/usr/bin/env ruby
# frozen_string_literal: true

# runner-group-contract.rb — prove spoke-ci.yml's optional `runner_group` input
# (TIN-3902) is a real default-off change (AGENTS.md rule 2).
#
# Two things are proven, mechanically, offline:
#
#   (a) With `runner_group` unset, every job's RENDERED runs-on is byte-for-byte
#       the pinned label-only baseline below (the same discipline as the
#       restricted contract's `legacy_sha256`), and both the baseline and the
#       live expression are evaluated over a scenario grid; the results must be
#       equal.
#
#   (b) With `runner_group` set, every runner-class job renders GitHub's
#       structured `{group, labels}` mapping carrying exactly the labels it
#       resolves today, and any job whose runs-on is a plain literal renders
#       that unchanged literal — a group mapping is never emitted for it. That
#       class is DERIVED from the baseline, never hardcoded.
#
# TIN-3914 re-record: the baseline was the pre-TIN-3902 expression set, in which
# secrets-scan / lanes-load / repo-manifest were the literal `ubuntu-latest`
# class. The no-GitHub-hosted-runners ruling moved those three onto
# `inputs.default_runner_class`, so all seven jobs are runner-class jobs now and
# the literal class is empty. The baseline below is therefore re-recorded to the
# post-TIN-3914 label-only routing. What it proves is unchanged and is the whole
# point of the pin: `runner_group` stays default-off. Do NOT re-record it again
# to make a check pass — a diff here means a routing change that needs its own
# review.
#
# The evaluator implements the slice of the GitHub Actions expression language
# these runs-on values use: `!=`, `&&`, `||` with GitHub's operand-returning
# short circuit and falsiness set (null / false / 0 / ''), plus fromJSON,
# toJSON, format, and `inputs.*` / `matrix.*` context lookups. Encoding those
# semantics is the point: the default-off claim rests on `false && X || Y == Y`,
# so the assumption is written down and executable rather than asserted in prose.
#
# GitHub's toJSON pretty-prints; this stand-in emits compact JSON. Every toJSON
# result here is consumed immediately by fromJSON, and both forms parse to the
# same value, so the rendered runs-on is unaffected.

require "json"
require "yaml"

ROOT = File.expand_path("..", __dir__)
WORKFLOW = File.join(ROOT, ".github/workflows/spoke-ci.yml")

# The pinned label-only baseline: what every job's runs-on renders to with
# `runner_group` unset. Re-recorded once, deliberately, for TIN-3914 (see the
# header). Never edit these to make a check pass: they ARE the
# backward-compatibility baseline.
LEGACY_RUNS_ON = {
  "secrets-scan" => "${{ inputs.default_runner_class }}",
  "lanes-load" => "${{ inputs.default_runner_class }}",
  "repo-manifest" => "${{ inputs.default_runner_class }}",
  "flywheel-build" => "${{ inputs.runner_labels_json != '' && fromJSON(inputs.runner_labels_json) || matrix.lane.runner_class || inputs.default_runner_class }}",
  "flywheel-test" => "${{ inputs.runner_labels_json != '' && fromJSON(inputs.runner_labels_json) || matrix.lane.runner_class || inputs.default_runner_class }}",
  "bazel-graph" => "${{ inputs.heavy_runner_class }}",
  "playwright" => "${{ inputs.kvm_runner_class }}",
}.freeze

# Derived from the baseline, never hardcoded: a job whose runs-on is a plain
# literal must keep exactly that literal and must never gain a group mapping; a
# job that routes through a runner-class expression MUST gain one when
# runner_group is set. After TIN-3914 the literal class is EMPTY — all seven
# jobs route through a runner-class input — so the literal branch is kept
# executable by a synthetic negative oracle in the self-test rather than by the
# live workflow. Derivation is the point: a future job added with a literal
# runs-on is covered without editing this logic.
def literal_jobs(baseline)
  baseline.reject { |_job, value| value.include?("${{") }.keys
end

def expression_jobs(baseline)
  baseline.keys - literal_jobs(baseline)
end

LITERAL_JOBS = literal_jobs(LEGACY_RUNS_ON).freeze
EXPRESSION_JOBS = expression_jobs(LEGACY_RUNS_ON).freeze

# ── expression evaluator (the GitHub Actions subset used by runs-on) ─────────

class ExpressionError < StandardError; end

class Lexer
  TOKEN = /
    \s+                        |
    (?<str>'(?:[^']|'')*')     |
    (?<op>&&|\|\||==|!=)       |
    (?<punct>[(),])            |
    (?<name>[A-Za-z_][A-Za-z0-9_.-]*)
  /x

  def self.tokens(source)
    out = []
    pos = 0
    while pos < source.length
      match = TOKEN.match(source, pos)
      raise ExpressionError, "unlexable input at #{source[pos..pos + 20].inspect}" if match.nil? || match.begin(0) != pos

      pos = match.end(0)
      if match[:str]
        out << [:string, match[:str][1..-2].gsub("''", "'")]
      elsif match[:op]
        out << [:op, match[:op]]
      elsif match[:punct]
        out << [:punct, match[:punct]]
      elsif match[:name]
        out << [:name, match[:name]]
      end
    end
    out
  end
end

class Evaluator
  # GitHub falsiness: null, false, 0, ''. Arrays and objects are truthy — the
  # pre-existing `fromJSON(inputs.runner_labels_json) || …` arm already depends
  # on that, and the group arm depends on it for objects.
  def self.truthy?(value)
    return false if value.nil? || value == false || value == "" || value == 0

    true
  end

  def initialize(context)
    @context = context
  end

  def eval(source)
    body = source.strip
    match = /\A\$\{\{(.*)\}\}\z/m.match(body)
    return body unless match # a plain YAML scalar such as `ubuntu-latest`

    @tokens = Lexer.tokens(match[1])
    @pos = 0
    node = parse_or
    raise ExpressionError, "trailing tokens: #{@tokens[@pos..-1].inspect}" unless @pos == @tokens.length

    evaluate(node)
  end

  private

  def peek
    @tokens[@pos]
  end

  def take
    token = @tokens[@pos]
    @pos += 1
    token
  end

  def accept(type, value)
    return false unless peek && peek[0] == type && peek[1] == value

    @pos += 1
    true
  end

  # ── parse to an AST; `&&` / `||` must SHORT-CIRCUIT, exactly as GitHub does.
  # The pre-existing default path depends on it: with runner_labels_json unset,
  # `'' != '' && fromJSON('')` must never reach fromJSON.
  def parse_or
    node = parse_and
    node = [:or, node, parse_and] while accept(:op, "||")
    node
  end

  def parse_and
    node = parse_comparison
    node = [:and, node, parse_comparison] while accept(:op, "&&")
    node
  end

  def parse_comparison
    left = parse_primary
    return [:eq, left, parse_primary] if accept(:op, "==")
    return [:ne, left, parse_primary] if accept(:op, "!=")

    left
  end

  def parse_primary
    token = take
    raise ExpressionError, "unexpected end of expression" if token.nil?

    case token[0]
    when :string then [:lit, token[1]]
    when :punct
      raise ExpressionError, "unexpected #{token[1].inspect}" unless token[1] == "("

      node = parse_or
      raise ExpressionError, "unbalanced parentheses" unless accept(:punct, ")")

      node
    when :name
      return [:call, token[1], arguments] if peek && peek[0] == :punct && peek[1] == "("

      [:ctx, token[1]]
    else
      raise ExpressionError, "unexpected token #{token.inspect}"
    end
  end

  def arguments
    accept(:punct, "(") || raise(ExpressionError, "expected (")
    args = []
    unless accept(:punct, ")")
      loop do
        args << parse_or
        break if accept(:punct, ")")
        raise ExpressionError, "expected , or ) in argument list" unless accept(:punct, ",")
      end
    end
    args
  end

  def evaluate(node)
    case node[0]
    when :lit then node[1]
    when :ctx then lookup(node[1])
    when :call then call(node[1], node[2].map { |arg| evaluate(arg) })
    when :eq then evaluate(node[1]) == evaluate(node[2])
    when :ne then evaluate(node[1]) != evaluate(node[2])
    when :and
      left = evaluate(node[1])
      self.class.truthy?(left) ? evaluate(node[2]) : left
    when :or
      left = evaluate(node[1])
      self.class.truthy?(left) ? left : evaluate(node[2])
    else raise ExpressionError, "unknown node #{node.inspect}"
    end
  end

  def call(name, args)
    case name
    when "fromJSON", "fromJson" then JSON.parse(args.fetch(0))
    when "toJSON", "toJson" then JSON.generate(args.fetch(0))
    when "format"
      template = args.fetch(0)
      rest = args[1..-1] || []
      template
        .gsub(/\{\{|\}\}|\{(\d+)\}/) do |hit|
          case hit
          when "{{" then "{"
          when "}}" then "}"
          else stringify(rest.fetch(Regexp.last_match(1).to_i))
          end
        end
    when "join" then Array(args.fetch(0)).join(args.fetch(1, ","))
    else raise ExpressionError, "unsupported function #{name}"
    end
  end

  def stringify(value)
    case value
    when nil then ""
    when String then value
    when true, false, Numeric then value.to_s
    else JSON.generate(value)
    end
  end

  def lookup(path)
    return true if path == "true"
    return false if path == "false"
    return nil if path == "null"

    node = @context
    path.split(".").each do |segment|
      node = node.is_a?(Hash) ? node[segment] : nil
    end
    node
  end
end

# ── scenarios ───────────────────────────────────────────────────────────────

# Every routing shape a real consumer expresses today: the scaffold default, the
# GFTB org-scope overlay (TIN-2299: only the base capability label is served),
# the per-lane override, and the dynamic runner_labels_json fallback pattern.
BASE_SCENARIOS = {
  "scaffold defaults" => {
    "inputs" => {
      "runner_labels_json" => "", "default_runner_class" => "tinyland-nix",
      "heavy_runner_class" => "tinyland-nix-heavy", "kvm_runner_class" => "tinyland-nix-kvm"
    },
    "matrix" => { "lane" => {} },
  },
  "GFTB org-scope overlay" => {
    "inputs" => {
      "runner_labels_json" => "", "default_runner_class" => "tinyland-nix",
      "heavy_runner_class" => "tinyland-nix", "kvm_runner_class" => "tinyland-nix"
    },
    "matrix" => { "lane" => {} },
  },
  "per-lane runner_class override" => {
    "inputs" => {
      "runner_labels_json" => "", "default_runner_class" => "tinyland-nix",
      "heavy_runner_class" => "tinyland-nix-heavy", "kvm_runner_class" => "tinyland-nix-kvm"
    },
    "matrix" => { "lane" => { "runner_class" => "great-falls-tool-bus-nix" } },
  },
  "runner_labels_json array" => {
    "inputs" => {
      "runner_labels_json" => '["self-hosted","tinyland-nix"]', "default_runner_class" => "tinyland-nix",
      "heavy_runner_class" => "tinyland-nix-heavy", "kvm_runner_class" => "tinyland-nix-kvm"
    },
    "matrix" => { "lane" => { "runner_class" => "tinyland-nix" } },
  },
}.freeze

OPTED_GROUP = "great-falls-tool-bus-infra"

def with_group(scenario, group)
  copy = Marshal.load(Marshal.dump(scenario))
  copy["inputs"]["runner_group"] = group
  copy
end

def render(expression, context)
  Evaluator.new(context).eval(expression)
end

def load_workflow
  YAML.load_file(WORKFLOW, aliases: true)
rescue ArgumentError
  YAML.load_file(WORKFLOW)
end

def workflow_runs_on(document)
  document.fetch("jobs").each_with_object({}) { |(job, body), out| out[job] = body.is_a?(Hash) ? body["runs-on"] : nil }
end

def check_runs_on(runs_on, baseline = LEGACY_RUNS_ON)
  errors = []
  literal = literal_jobs(baseline)
  expression = expression_jobs(baseline)
  expected_jobs = baseline.keys.sort
  unless runs_on.keys.sort == expected_jobs
    errors << "job set changed (#{runs_on.keys.sort.join(", ")}); re-record LEGACY_RUNS_ON deliberately"
  end

  baseline.each do |job, legacy|
    current = runs_on[job]
    next errors << "#{job}: missing runs-on" if current.nil?

    # (b) a literal-runs-on job stays that exact literal — never group-routed.
    if literal.include?(job)
      errors << "#{job}: literal runs-on changed (#{current.inspect}); must stay #{legacy.inspect}" unless current == legacy
      next
    end

    errors << "#{job}: expected a runner-class expression job" unless expression.include?(job)

    BASE_SCENARIOS.each do |label, scenario|
      unset = render(current, with_group(scenario, ""))
      baseline = render(legacy, with_group(scenario, ""))

      # (a) default path: rendered runs-on byte-for-byte the pre-TIN-3902 value.
      if JSON.generate(unset) != JSON.generate(baseline)
        errors << "#{job} [#{label}]: runner_group unset rendered #{unset.inspect}, pre-TIN-3902 rendered #{baseline.inspect}"
      end
      if unset.is_a?(Hash)
        errors << "#{job} [#{label}]: runner_group unset must not render a group mapping"
      end

      # (b) opted path: structured mapping carrying the SAME labels.
      opted = render(current, with_group(scenario, OPTED_GROUP))
      unless opted.is_a?(Hash) && opted.keys.sort == %w[group labels]
        errors << "#{job} [#{label}]: runner_group set rendered #{opted.inspect}, expected a {group, labels} mapping"
        next
      end
      errors << "#{job} [#{label}]: group is #{opted["group"].inspect}, expected #{OPTED_GROUP.inspect}" unless opted["group"] == OPTED_GROUP
      unless JSON.generate(opted["labels"]) == JSON.generate(baseline)
        errors << "#{job} [#{label}]: group mapping labels #{opted["labels"].inspect} != today's #{baseline.inspect}"
      end
    end
  end

  errors
end

# Negative oracle: prove the checker above actually rejects the ways this input
# could stop being default-off or start group-routing a literal-runs-on job.
def self_test
  runs_on = workflow_runs_on(load_workflow)
  composed = runs_on.fetch("bazel-graph")
  mutants = {
    "unconditional group mapping (default path broken)" =>
      runs_on.merge("bazel-graph" => composed.sub("inputs.runner_group != '' &&", "true &&")),
    "utility job silently re-routed to the heavy class" =>
      runs_on.merge("secrets-scan" => composed),
    "opted path drops the resolved labels" =>
      runs_on.merge("bazel-graph" => composed.sub("toJSON(inputs.heavy_runner_class))", "toJSON('tinyland-nix'))")),
    "default arm silently re-routed" =>
      runs_on.merge("bazel-graph" => composed.sub("|| inputs.heavy_runner_class }}", "|| inputs.default_runner_class }}")),
    "opt-in reversed (group when unset, labels when set)" =>
      runs_on.merge("bazel-graph" => composed.sub("inputs.runner_group != ''", "inputs.runner_group == ''")),
  }

  survivors = mutants.reject { |_label, mutant| check_runs_on(mutant).any? }.keys

  # TIN-3914 emptied the literal-runs-on class (every job now routes through a
  # runner-class input), so the "a literal job never gains a group mapping"
  # branch has no live subject. Keep it executable against a synthetic baseline
  # that declares one, so the invariant is still proven rather than merely
  # asserted, and so a future literal-runs-on job lands on a tested rule.
  synthetic_baseline = LEGACY_RUNS_ON.merge("synthetic-literal" => "tinyland-nix")
  synthetic_runs_on = runs_on.merge("synthetic-literal" => "tinyland-nix")
  synthetic_mutants = {
    "group mapping leaks into a literal-runs-on job" =>
      synthetic_runs_on.merge("synthetic-literal" => composed),
    "literal-runs-on job silently relabelled" =>
      synthetic_runs_on.merge("synthetic-literal" => "tinyland-nix-heavy"),
  }
  if check_runs_on(synthetic_runs_on, synthetic_baseline).any?
    survivors << "synthetic literal-job baseline rejected its own unmutated input"
  end
  survivors.concat(
    synthetic_mutants.reject { |_label, mutant| check_runs_on(mutant, synthetic_baseline).any? }.keys
  )

  total = mutants.length + synthetic_mutants.length
  if survivors.empty?
    puts "runner_group contract self-test passed (#{total} negative oracles rejected, " \
         "#{synthetic_mutants.length} against a synthetic literal-runs-on baseline)"
    return 0
  end

  warn "runner_group contract self-test FAILED — accepted:"
  survivors.each { |label| warn "- #{label}" }
  1
end

def main
  return self_test if ARGV.include?("--self-test")

  document = load_workflow
  errors = []

  inputs = document.dig("on", "workflow_call", "inputs") || document.dig(true, "workflow_call", "inputs") || {}
  declaration = inputs["runner_group"]
  unless declaration.is_a?(Hash) && declaration["type"] == "string" && declaration["default"] == ""
    errors << "runner_group must be declared `type: string` with `default: \"\"` (opt-in, default-off)"
  end
  errors.concat(check_runs_on(workflow_runs_on(document)))

  if errors.empty?
    checked = EXPRESSION_JOBS.length * BASE_SCENARIOS.length
    puts "runner_group contract passed (#{LITERAL_JOBS.length} literal runs-on jobs unchanged; " \
         "#{checked} rendered runner-class runs-on values across #{EXPRESSION_JOBS.length} jobs: " \
         "default path byte-identical to the pinned label-only baseline, opted path structured)"
    return 0
  end

  warn "runner_group contract FAILED:"
  errors.each { |error| warn "- #{error}" }
  1
end

exit(main) if $PROGRAM_NAME == __FILE__

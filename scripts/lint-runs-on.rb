#!/usr/bin/env ruby
# frozen_string_literal: true

# lint-runs-on.rb — guard every workflow `runs-on` against the shared ARC
# capability-label taxonomy, at author time, before drift reaches the cluster.
#
# Forbids repo-shaped / project-identity self-hosted labels (e.g.
# `runs-on: dollhouse-farm-nix`, `chapel-nix`, `jesssullivan-nix-heavy`), bare
# `self-hosted`, and drift smuggled into a fromJSON() fallback — while PASSing
# org capability labels (tinyland-nix, great-falls-tool-bus-nix, ...),
# GitHub-hosted labels (ubuntu-latest, ...), and the legitimate dynamic
# `${{ fromJSON(vars.* || '["ubuntu-latest"]') }}` indirection. GitHub's
# `runs-on: {group, labels}` mapping is evaluated structurally: the group must
# be explicit or runtime-resolved and the labels must still reduce to a shared
# capability (hosted labels cannot satisfy a group mapping). Never crashes and
# never FAILs on a runs-on it cannot statically resolve (pure needs-output /
# inputs / unresolvable matrix) — those WARN.
#
# Taxonomy authority: GloriousFlywheel/scripts/validate-arc-runner-taxonomy.py,
# ported in runner_label_taxonomy.rb and pinned by --self-test.

require "yaml"
require "json"
require "optparse"
require_relative "runner_label_taxonomy"

T = RunnerLabelTaxonomy

# Generic OS/arch/default self-hosted tags that may accompany ONE shared
# capability label in an array without making it "repo-shaped" drift.
GENERIC_ARRAY_TAGS = %w[self-hosted linux x64 x86_64 arm64 aarch64 macos windows nix darwin].freeze

# ── verdict primitives ──────────────────────────────────────────────────────

def verdict_for_label(label)
  return [:pass, "shared/constructed capability label"] if T.shared_or_constructed?(label)
  return [:pass, "GitHub-hosted / known hosted fleet"] if T.hosted_label?(label)

  [:fail, T.label_errors(label).join("; ")]
end

# A YAML/JSON array of labels (GitHub AND-s them).
def evaluate_array(labels, opts)
  labels = labels.map(&:to_s)
  return { verdict: :pass, detail: "hosted runner array", resolved: labels.join(",") } if labels.all? { |l| T.hosted_label?(l) }

  shared = labels.select { |l| T.shared_or_constructed?(l) }
  bare_self_hosted = labels.any? { |l| l.casecmp?("self-hosted") }
  extras = labels.reject { |l| shared.include?(l) || T.hosted_label?(l) || GENERIC_ARRAY_TAGS.include?(l.downcase) }

  if shared.length >= 1 && !bare_self_hosted && extras.empty?
    return { verdict: :pass, detail: "array reduces to shared capability label(s) #{shared.join(",")}", resolved: labels.join(",") }
  end
  if shared.empty?
    return { verdict: :fail, detail: "self-hosted array has no shared capability label", resolved: labels.join(",") }
  end

  # A shared label present, but pinned alongside bare self-hosted / host tags.
  noise = extras + (bare_self_hosted ? ["self-hosted"] : [])
  verdict = opts[:self_hosted_array_mixed] == :warn ? :warn : :fail
  { verdict: verdict, detail: "non-canonical self-hosted array: #{shared.join(",")} mixed with #{noise.join(",")}", resolved: labels.join(",") }
end

# Resolve `${{ matrix.<key>[.<sub>] }}` against the job's strategy.matrix.
def resolve_matrix_ref(expr, job)
  ref = expr[/matrix\.([a-zA-Z0-9_.]+)/, 1]
  return [] unless ref

  matrix = job.is_a?(Hash) ? job.dig("strategy", "matrix") : nil
  return [] unless matrix.is_a?(Hash)

  keys = ref.split(".")
  top = keys[0]
  cands = []

  val = matrix[top]
  if val.is_a?(Array)
    val.each do |entry|
      if keys.length == 1
        cands << entry if entry.is_a?(String)
      elsif entry.is_a?(Hash)
        sub = entry.dig(*keys[1..])
        cands << sub if sub.is_a?(String)
      end
    end
  end

  inc = matrix["include"]
  if inc.is_a?(Array)
    inc.each do |entry|
      next unless entry.is_a?(Hash)

      sub = keys.length == 1 ? entry[top] : entry.dig(*keys)
      cands << sub if sub.is_a?(String)
    end
  end

  cands.uniq
end

# A `${{ ... }}` expression: extract every statically-knowable label, verdict
# the worst, WARN if nothing is statically resolvable. Never raises.
def evaluate_expression(raw, job, opts)
  results = []
  work = raw.dup

  # (0) A structured `{group, labels}` runs-on composed at runtime. Consume the
  # whole fromJSON(format(...)) region: its arms are mapping arms, not bare
  # label literals, and the JSON template itself is not a label at all.
  if (composed = evaluate_composed_group(raw, job, opts))
    work = work.sub(composed[:source], " ")
    results.concat(composed[:results])
  end

  # (1) JSON-array literals -> evaluate as arrays (canonical-reduction logic).
  raw.scan(/'(\[[^']*\])'/).each do |m|
    json = m[0]
    work = work.sub("'#{json}'", " ")
    begin
      arr = JSON.parse(json)
      results << evaluate_array(arr.map(&:to_s), opts) if arr.is_a?(Array)
    rescue StandardError
      # Unparseable literal -> ignore (degrade, never crash).
    end
  end

  # (2) Drop comparison operands so `vars.X == 'true'` does not look like a label.
  work = work.gsub(/(==|!=)\s*'[^']*'/, " ").gsub(/'[^']*'\s*(==|!=)/, " ")

  # (3) Remaining single-quoted plain strings are value-position label literals.
  work.scan(/'([^'\[\]]*)'/).each do |m|
    label = m[0].strip
    next if label.empty?

    verdict, why = verdict_for_label(label)
    results << { verdict: verdict, detail: "literal #{label.inspect}: #{why}", resolved: label }
  end

  # (4) Matrix resolution only if no literal was found.
  if results.empty? && raw.include?("matrix.")
    resolve_matrix_ref(raw, job).each do |label|
      verdict, why = verdict_for_label(label)
      results << { verdict: verdict, detail: "matrix #{label.inspect}: #{why}", resolved: label }
    end
  end

  if results.empty?
    return { verdict: :warn, detail: "runs-on resolves only at runtime; no static literal to verify", resolved: raw }
  end

  worst = results.find { |r| r[:verdict] == :fail } ||
          results.find { |r| r[:verdict] == :warn } ||
          results.first
  worst.merge(resolved: results.map { |r| r[:resolved] }.join(","))
end

def worst_result(results, resolved)
  worst = results.find { |r| r[:verdict] == :fail } ||
          results.find { |r| r[:verdict] == :warn } ||
          results.first
  worst.merge(resolved: resolved, detail: results.map { |r| r[:detail] }.join("; "))
end

def forbidden_runner_group?(value)
  raw = value.to_s.strip
  normalized = raw.downcase.gsub(/[\s_]+/, "-")
  return true if normalized.match?(/\A(?:default|shared)(?:-|\z)/)
  return true if normalized.match?(/\A(?:github-actions|github-hosted|self-hosted)(?:-|\z)/)
  return true if T.hosted_label?(raw)

  false
end

def evaluate_runner_group(value)
  return { verdict: :fail, detail: "runs-on group mapping is missing group", resolved: "" } if value.nil?
  unless value.is_a?(String)
    return { verdict: :fail, detail: "runner group must be a string or expression", resolved: value.inspect }
  end

  group = value.to_s.strip
  if group.include?("${{")
    literals = group.scan(/'([^']+)'/).flatten + group.scan(/"([^"]+)"/).flatten
    forbidden = literals.uniq.select { |literal| forbidden_runner_group?(literal) }
    unless forbidden.empty?
      return {
        verdict: :fail,
        detail: "dynamic runner group contains forbidden fallback literal(s): #{forbidden.map(&:inspect).join(", ")}",
        resolved: group,
      }
    end
    return { verdict: :warn, detail: "runner group resolves only at runtime", resolved: group }
  end
  if group.empty?
    return { verdict: :fail, detail: "runner group must not be empty", resolved: group }
  end
  if forbidden_runner_group?(group)
    return { verdict: :fail, detail: "generic/shared runner group is forbidden", resolved: group }
  end

  { verdict: :pass, detail: "explicit non-generic runner group", resolved: group }
end

def evaluate_group_labels(value, job, opts)
  return { verdict: :fail, detail: "runs-on group mapping is missing labels", resolved: "" } if value.nil?
  unless value.is_a?(String) || value.is_a?(Array)
    return { verdict: :fail, detail: "runner-group labels must be a string, expression, or array", resolved: value.inspect }
  end

  result = evaluate_runs_on(value, job, opts)
  hosted = case value
           when Array
             value.map(&:to_s).any? { |label| T.hosted_label?(label) }
           when String
             if value.include?("${{")
               literals = value.scan(/'([^']+)'/).flatten
               literals.any? do |literal|
                 if literal.start_with?("[")
                   begin
                     JSON.parse(literal).any? { |label| T.hosted_label?(label.to_s) }
                   rescue StandardError
                     false
                   end
                 else
                   T.hosted_label?(literal)
                 end
               end
             else
               T.hosted_label?(value.strip)
             end
           else
             false
           end
  return result unless hosted

  { verdict: :fail, detail: "GitHub-hosted labels cannot satisfy a runner-group mapping", resolved: result[:resolved] }
end

# YAML cannot express a CONDITIONAL runs-on mapping, so a workflow that must
# keep a label-only default composes GitHub's structured `{group, labels}` form
# at runtime:
#
#   ${{ inputs.runner_group != '' &&
#       fromJSON(format('{{"group":{0},"labels":{1}}}',
#                       toJSON(inputs.runner_group), toJSON(<labels expr>)))
#       || <labels expr> }}
#
# That is the same mapping as a static `runs-on: {group:, labels:}` node, so it
# gets the same structural verdict instead of being mistaken for a bare label
# literal. An arm that is a single quoted literal is verdicted statically;
# anything else is runtime-resolved (WARN, plus the forbidden-fallback scan).
# Only the exact canonical template above is read this way — see
# CANONICAL_COMPOSED_TEMPLATE.
# The ONE canonical template, pinned byte-for-byte. Positional trust in the
# format() arguments is only sound while the template itself is fixed: a
# template with a group or a label hardcoded into it (`{{"group":"Default",…}}`)
# would otherwise be read through arg positions that no longer describe what the
# mapping actually emits. Any other template is NOT this pattern — it falls
# through to the ordinary literal scan below, which verdicts the template text
# as the runner label it is not, i.e. FAILs.
CANONICAL_COMPOSED_TEMPLATE = %q('{{"group":{0},"labels":{1}}}').freeze
COMPOSED_GROUP_CALL = /format\(\s*'\{\{/.freeze
STATIC_CALL_ARG = /\A(?:toJSON\()?\s*'([^']*)'\s*\)?\z/

# Split the argument list of the call whose `(` is at open_paren, honouring
# nested parens and single-quoted literals. Returns [args, index_of_close].
def split_call_args(source, open_paren)
  args = []
  current = +""
  depth = 0
  in_quote = false
  index = open_paren

  while index < source.length
    char = source[index]
    if in_quote
      current << char
      in_quote = false if char == "'"
    elsif char == "'"
      in_quote = true
      current << char
    elsif char == "("
      depth += 1
      current << char if depth > 1
    elsif char == ")"
      depth -= 1
      if depth.zero?
        args << current
        return [args, index]
      end
      current << char
    elsif char == "," && depth == 1
      args << current
      current = +""
    else
      current << char
    end
    index += 1
  end

  [args << current, source.length - 1]
end

# `toJSON('tinyland-infra')` is a static arm and is verdicted as the literal;
# anything else stays an expression so the runtime/forbidden-fallback rules run.
def composed_arm(arg)
  text = arg.to_s.strip
  literal = STATIC_CALL_ARG.match(text)
  literal ? literal[1] : "${{ #{text} }}"
end

# Returns { source:, results: } for the composed mapping, or nil when the
# expression does not build one. Never raises.
def evaluate_composed_group(raw, job, opts)
  match = COMPOSED_GROUP_CALL.match(raw)
  return nil unless match

  open_paren = raw.index("(", match.begin(0))
  return nil unless open_paren

  args, close_paren = split_call_args(raw, open_paren)
  return nil if args.length != 3
  return nil unless args[0].to_s.strip == CANONICAL_COMPOSED_TEMPLATE

  group = evaluate_runner_group(composed_arm(args[1]))
  labels = evaluate_group_labels(composed_arm(args[2]), job, opts)

  { source: raw[match.begin(0)..close_paren], results: [group, labels] }
rescue StandardError
  nil
end

def evaluate_mapping(value, job, opts)
  normalized = value.transform_keys(&:to_s)
  unknown = normalized.keys - %w[group labels]
  unless unknown.empty?
    return { verdict: :fail, detail: "unknown runs-on mapping keys: #{unknown.join(", ")}", resolved: value.inspect }
  end

  group = evaluate_runner_group(normalized["group"])
  labels = evaluate_group_labels(normalized["labels"], job, opts)
  worst_result([group, labels], "group=#{group[:resolved]}; labels=#{labels[:resolved]}")
end

# Top-level dispatch for a single runs-on node.
def evaluate_runs_on(value, job, opts)
  return evaluate_mapping(value, job, opts) if value.is_a?(Hash)
  return evaluate_array(value, opts) if value.is_a?(Array)

  str = value.to_s.strip
  return evaluate_expression(str, job, opts) if str.include?("${{")

  verdict, why = verdict_for_label(str)
  { verdict: verdict, detail: why, resolved: str }
end

# ── scale-set cross-check (GF-only; needs the overlay/honey tfvars) ──────────

def scale_set_names(tfvars_path)
  return [] unless tfvars_path && File.file?(tfvars_path)

  File.read(tfvars_path).scan(/runner_scale_set_name\s*=\s*"([^"]+)"/).flatten.uniq
end

# ── workflow walking ────────────────────────────────────────────────────────

def runs_on_line(path, job_id)
  lines = File.readlines(path)
  in_job = false
  job_re = /\A\s+#{Regexp.escape(job_id)}\s*:/
  lines.each_with_index do |line, idx|
    in_job = true if line.match?(job_re)
    return idx + 1 if in_job && line.match?(/\A\s+runs-on\s*:/)
  end
  1
end

def lint_file(path, opts)
  doc = begin
    YAML.load_file(path, aliases: true)
  rescue ArgumentError
    YAML.load_file(path)
  rescue StandardError => e
    return [{ file: path, job: "(file)", raw: "", verdict: :warn, detail: "unparseable YAML: #{e.message}", resolved: "", line: 1 }]
  end

  jobs = doc.is_a?(Hash) ? doc["jobs"] : nil
  return [] unless jobs.is_a?(Hash)

  findings = []
  jobs.each do |job_id, job|
    next unless job.is_a?(Hash)

    value = job["runs-on"]
    next if value.nil? # reusable-workflow `uses:` jobs have no runs-on

    result = evaluate_runs_on(value, job, opts)
    raw = (value.is_a?(Array) || value.is_a?(Hash)) ? value.inspect : value.to_s

    if result[:verdict] != :fail && opts[:scale_set_names].any?
      literal = value.is_a?(Array) ? nil : value.to_s.strip
      if literal && opts[:scale_set_names].include?(literal) && !T::SHARED_CAPABILITY_LABELS.include?(literal)
        result = { verdict: :fail, detail: "runs-on #{literal.inspect} matches an ARC scale-set registration NAME, not a shared capability label; use the runner_label (capability), never the scale-set name", resolved: literal }
      end
    end

    findings << result.merge(file: path, job: job_id, raw: raw, line: runs_on_line(path, job_id))
  end
  findings
end

def workflow_files(root, glob)
  Dir.glob(File.join(root, glob)).select { |f| f.match?(/\.ya?ml\z/) }.sort
end

# ── self-test oracle (pins parity with the taxonomy authority) ──────────────

# The exact composed shape spoke-ci.yml emits for its optional `runner_group`
# input, so the workflow and this guard cannot drift apart silently.
def composed_expr(group_arg, labels_arg, fallback = "inputs.default_runner_class",
                  template = CANONICAL_COMPOSED_TEMPLATE)
  "${{ inputs.runner_group != '' && " \
    "fromJSON(format(#{template}, #{group_arg}, #{labels_arg})) " \
    "|| #{fallback} }}"
end

COMPOSED_RUNTIME = composed_expr("toJSON(inputs.runner_group)", "toJSON(inputs.default_runner_class)")
COMPOSED_STATIC = composed_expr("toJSON('tinyland-infra')", "toJSON('tinyland-nix')", "'tinyland-nix'")

def self_test
  opts = { self_hosted_array_mixed: :fail, scale_set_names: [] }
  oracle = [
    # value (YAML node), expected verdict, label
    ["tinyland-nix", :pass, "shared base label"],
    ["tinyland-dind", :pass, "shared base label"],
    ["tinyland-docker", :pass, "shared base label"],
    ["tinyland-nix-heavy", :pass, "shared base label"],
    ["tinyland-nix-kvm", :pass, "shared base label"],
    ["tinyland-nix-operator", :pass, "constructed: operator IS an allowed suffix"],
    ["tinyland-nix-darwin", :pass, "constructed-valid"],
    ["great-falls-tool-bus-nix", :pass, "tenant org capability label"],
    ["medical-massage-specialists-docker", :pass, "tenant org capability label"],
    ["ubuntu-latest", :pass, "hosted family"],
    ["macos-15", :pass, "hosted family"],
    ["dollhouse-farm-nix", :fail, "repo-shaped (empirical target)"],
    ["chapel-nix", :fail, "repo-shaped (live drift)"],
    ["jesssullivan-nix-heavy", :fail, "repo-shaped (live drift x4)"],
    ["tinyland-nix-rockies", :fail, "project-identity token"],
    ["self-hosted", :fail, "bare self-hosted"],
    [%w[self-hosted aarch64-darwin nix], :fail, "array, no shared label"],
    [["self-hosted", "Linux", "X64", "honey", "tinyland-nix", "nix"], :fail, "non-canonical mixed array (honey host pin)"],
    [%w[self-hosted printbox], :fail, "array, bespoke host, no shared label"],
    ["${{ fromJSON(vars.BAZEL_LINUX_RUNNER_LABELS_JSON || vars.PRIMARY_LINUX_RUNNER_LABELS_JSON || '[\"ubuntu-latest\"]') }}", :pass, "legitimate darkmap fromJSON pattern"],
    ["${{ fromJSON(vars.CI_RUNNER_LABELS_JSON || '[\"massageithaca-dind\"]') }}", :fail, "drift baked into fromJSON fallback"],
    ["${{ vars.USE_SELFHOSTED == 'true' && vars.GF_SHARED_RUNNERS_REACHABLE == 'true' && 'tinyland-nix' || 'ubuntu-latest' }}", :pass, "ternary; both branches valid"],
    ["${{ vars.ATTIC_DEPLOY_RUNNER_LABEL || 'tinyland-nix-operator' }}", :pass, "trailing literal valid via operator suffix"],
    ["${{ inputs.runner || 'depot-macos-latest' }}", :pass, "hosted fleet fallback"],
    ["${{ fromJSON(needs.route-preflight.outputs.labels_json) }}", :warn, "pure needs-output indirection"],
    ["${{ inputs.runner_label }}", :warn, "bare input ref"],
    [{ "group" => "tinyland-infra", "labels" => "tinyland-nix" }, :pass, "group mapping with capability"],
    [{ "group" => "${{ inputs.runner_group }}", "labels" => "${{ inputs.runner_label }}" }, :warn, "runtime group mapping"],
    [{ "group" => "${{ inputs.runner_group || 'tinyland-infra' }}", "labels" => "tinyland-nix" }, :warn, "runtime group mapping with safe literal"],
    [{ "group" => "${{ inputs.runner_group || 'Default' }}", "labels" => "tinyland-nix" }, :fail, "dynamic group rejects Default fallback"],
    [{ "group" => "${{ inputs.runner_group || 'default' }}", "labels" => "tinyland-nix" }, :fail, "dynamic group rejects lowercase default fallback"],
    [{ "group" => "${{ inputs.runner_group || 'shared-runners' }}", "labels" => "tinyland-nix" }, :fail, "dynamic group rejects shared fallback variant"],
    [{ "group" => "${{ inputs.runner_group || 'GitHub Actions' }}", "labels" => "tinyland-nix" }, :fail, "dynamic group rejects GitHub-hosted fallback"],
    [{ "group" => "${{ inputs.runner_group || 'ubuntu-latest' }}", "labels" => "tinyland-nix" }, :fail, "dynamic group rejects hosted-label fallback"],
    [{ "group" => "tinyland-infra", "labels" => "ubuntu-latest" }, :fail, "group mapping rejects hosted label"],
    [{ "group" => "ubuntu-latest", "labels" => "tinyland-nix" }, :fail, "group mapping rejects hosted group"],
    [{ "labels" => "tinyland-nix" }, :fail, "group mapping requires group"],
    [{ "group" => "Default", "labels" => "tinyland-nix" }, :fail, "group mapping rejects Default"],
    [{ "group" => ["tinyland-infra"], "labels" => "tinyland-nix" }, :fail, "group mapping rejects non-string group"],
    [{ "group" => "tinyland-infra", "labels" => { "nested" => "tinyland-nix" } }, :fail, "group mapping rejects nested labels"],
    # Composed structured runs-on (spoke-ci's optional runner_group, TIN-3902):
    # the same mapping semantics as the static node above, never a bare label.
    [COMPOSED_RUNTIME, :warn, "composed group mapping: runtime group + runtime labels"],
    [COMPOSED_STATIC, :pass, "composed group mapping: static group + static capability label"],
    [composed_expr("toJSON(inputs.runner_group || 'Default')", "toJSON(inputs.default_runner_class)"), :fail,
     "composed group rejects a Default fallback smuggled into the group arm"],
    [composed_expr("toJSON(inputs.runner_group || 'shared-runners')", "toJSON(inputs.default_runner_class)"), :fail,
     "composed group rejects a generic shared fallback in the group arm"],
    [composed_expr("toJSON(inputs.runner_group)", "toJSON('ubuntu-latest')"), :fail,
     "composed group rejects hosted labels (a hosted label cannot satisfy a group)"],
    [composed_expr("toJSON(inputs.runner_group)", "toJSON(inputs.x || 'ubuntu-latest')"), :fail,
     "composed group rejects a hosted fallback smuggled into the labels arm"],
    [composed_expr("toJSON(inputs.runner_group)", "toJSON('chapel-nix')"), :fail,
     "composed group rejects a repo-shaped label"],
    # The template is pinned, so drift hardcoded INTO it is not this pattern:
    # it falls through to the literal scan, which FAILs the template text.
    [composed_expr("toJSON(inputs.runner_group)", "toJSON(inputs.default_runner_class)",
                   "inputs.default_runner_class", %q('{{"group":"Default","labels":{1}}}')), :fail,
     "composed group rejects a Default group hardcoded into the format template"],
    [composed_expr("toJSON(inputs.runner_group)", "toJSON(inputs.default_runner_class)",
                   "inputs.default_runner_class", %q('{{"group":{0},"labels":"chapel-nix"}}')), :fail,
     "composed group rejects a repo-shaped label hardcoded into the format template"],
  ]
  matrix_job = { "strategy" => { "matrix" => { "os" => %w[ubuntu-latest macos-latest] } } }
  matrix_cases = [
    ["${{ matrix.os }}", matrix_job, :pass, "matrix.os resolves to hosted"],
    ["${{ matrix.os }}", { "strategy" => { "matrix" => { "os" => ["tinyland-nix", "chapel-nix"] } } }, :fail, "matrix.os includes repo-shaped drift"],
    ["${{ matrix.missing }}", {}, :warn, "unresolvable matrix ref"],
  ]

  failures = []
  oracle.each do |value, expected, label|
    got = evaluate_runs_on(value, {}, opts)[:verdict]
    failures << "#{label}: #{value.inspect} expected #{expected}, got #{got}" if got != expected
  end
  matrix_cases.each do |expr, job, expected, label|
    got = evaluate_runs_on(expr, job, opts)[:verdict]
    failures << "#{label}: #{expr.inspect} expected #{expected}, got #{got}" if got != expected
  end

  if failures.empty?
    puts "lint-runs-on self-test passed (#{oracle.length + matrix_cases.length} oracle cases)"
    0
  else
    warn "lint-runs-on self-test FAILED:"
    failures.each { |f| warn "- #{f}" }
    1
  end
end

# ── main ────────────────────────────────────────────────────────────────────

def main
  opts = {
    root: Dir.pwd,
    glob: ".github/workflows/*.yml",
    strict: false,
    json: false,
    self_hosted_array_mixed: :fail,
    scale_set_tfvars: nil,
    self_test: false,
  }

  OptionParser.new do |o|
    o.banner = "Usage: lint-runs-on.rb [options]"
    o.on("--root DIR", "Repo root to scan (default: cwd)") { |v| opts[:root] = v }
    o.on("--workflows-glob GLOB", "Workflow glob relative to root") { |v| opts[:glob] = v }
    o.on("--strict", "Treat WARN as failure") { opts[:strict] = true }
    o.on("--json", "Emit findings as JSON") { opts[:json] = true }
    o.on("--self-hosted-array-mixed MODE", %w[fail warn], "fail|warn for mixed self-hosted arrays (default fail)") { |v| opts[:self_hosted_array_mixed] = v.to_sym }
    o.on("--scale-set-tfvars PATH", "tfvars to cross-check runs-on against runner_scale_set_name (GF only)") { |v| opts[:scale_set_tfvars] = v }
    o.on("--self-test", "Run the embedded oracle and exit") { opts[:self_test] = true }
  end.parse!

  return self_test if opts[:self_test]

  run_opts = {
    self_hosted_array_mixed: opts[:self_hosted_array_mixed],
    scale_set_names: scale_set_names(opts[:scale_set_tfvars]),
  }

  files = workflow_files(opts[:root], opts[:glob])
  also_yaml = workflow_files(opts[:root], opts[:glob].sub(/\.yml\z/, ".yaml"))
  files = (files + also_yaml).uniq

  findings = files.flat_map { |f| lint_file(f, run_opts) }

  if opts[:json]
    puts JSON.pretty_generate(findings.map { |f| f.merge(file: f[:file].sub("#{opts[:root]}/", "")) })
  end

  fails = findings.select { |f| f[:verdict] == :fail }
  warns = findings.select { |f| f[:verdict] == :warn }

  unless opts[:json]
    findings.each do |f|
      rel = f[:file].sub("#{opts[:root]}/", "")
      case f[:verdict]
      when :fail
        puts "::error file=#{rel},line=#{f[:line]}::runs-on FAIL [#{f[:job]}] #{f[:raw]} -> #{f[:detail]}"
      when :warn
        puts "::warning file=#{rel},line=#{f[:line]}::runs-on WARN [#{f[:job]}] #{f[:raw]} -> #{f[:detail]}"
      end
    end
    total = findings.length
    puts "lint-runs-on: #{total} runs-on checked, #{fails.length} FAIL, #{warns.length} WARN across #{files.length} workflow file(s)"
  end

  if (gh = ENV["GITHUB_OUTPUT"])
    File.open(gh, "a") { |io| io.puts("violations_count=#{fails.length}") }
  end

  return 1 if fails.any?
  return 1 if opts[:strict] && warns.any?

  0
end

exit(main) if $PROGRAM_NAME == __FILE__

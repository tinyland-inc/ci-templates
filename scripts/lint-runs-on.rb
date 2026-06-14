#!/usr/bin/env ruby
# frozen_string_literal: true

# lint-runs-on.rb — guard every workflow `runs-on` against the shared ARC
# capability-label taxonomy, at author time, before drift reaches the cluster.
#
# Forbids repo-shaped / project-identity self-hosted labels (e.g.
# `runs-on: dollhouse-farm-nix`, `chapel-nix`, `jesssullivan-nix-heavy`), bare
# `self-hosted`, and drift smuggled into a fromJSON() fallback — while PASSing
# shared labels (tinyland-nix, ...), GitHub-hosted labels (ubuntu-latest, ...),
# and the legitimate dynamic `${{ fromJSON(vars.* || '["ubuntu-latest"]') }}`
# indirection. Never crashes and never FAILs on a runs-on it cannot statically
# resolve (pure needs-output / inputs / unresolvable matrix) — those WARN.
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

# Top-level dispatch for a single runs-on node.
def evaluate_runs_on(value, job, opts)
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
    raw = value.is_a?(Array) ? value.inspect : value.to_s

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

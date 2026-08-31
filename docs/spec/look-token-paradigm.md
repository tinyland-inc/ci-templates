---
title: "?look= paradigm: public-safe design concept"
status: DESIGN CONCEPT ONLY. No code, no schema edit, no CI-bearing change.
  Redacted variant for public-repo consumption: no private hostnames, no
  internal network names, no internal build-fabric names.
scope: a future internal build fabric (not yet built), a shared static-site
  scaffold, a public reusable-CI repository (this variant's home), a
  QA-prompt template repository
---

# ?look= query-string paradigm

## 1. Problem

Preview and generation addressing splits across surfaces, none carryable
across a copy-pasted URL:

- **Execution and cache routing** uses internal instance-name metadata,
  invisible on any served page.
- **Private preview hosting** addresses one operator-run host at a time, by a
  name that is not public.
- **Lane metadata** (a small JSON file per site) declares build variants only.
  It defines no application receiver, environment controller, DNS mutation
  path, or reaper, and grants none of those authorities.
- **The build marker** in a site footer carries a normalized short commit sha:
  read-only prose, unaddressable, empty on local builds.
- **A retired per-PR hostname template** survives only as schema prose after
  its dispatch receiver was removed. Alpha/beta subdomains are prior art named
  from memory; no current document describes them, so this cites none.

None lets a person say "I am looking at generation X on lane Y" in one string
surviving a copy-paste. A QA "LOOK" gate convention already demands the
serving lane and served sha be stated and verified first, since merged and
CI-green is not served. Today that is prose, not a checkable token.

**Origin evidence:** an accidental query-string parameter, appended by hand
during a routine manual QA pass on a live site. The site ignored it; the
access log kept the request line. A person reached for a query string to name
the page in front of them, and only the log preserved it.

## 2. UX, and the admission problem not to fake

**There is usually no client-readable admission signal.** Where a static site
sits behind a network-level gate, that gate terminates in front of the
artifact and hands the browser nothing a script can read. A runtime admission
check would need the keyed network call this section forbids. Invisibility
cannot come from a client-side branch.

**It comes from artifact separation instead.** The reader is compiled in only
for builds bound for a gated surface, via the same build-time inlining path
that already supplies the build-sha constant. The public production artifact
carries no reader, so `?look=` is inert there because nothing parses it: no
visible change, no console message, no network call, no server branch,
byte-identical response. Grepping the built bundle proves that; a runtime
check could not.

- **Gated surface, token present:** one line beside the build marker (never a
  modal, never a toast): `look: confirmed`, `look: mismatch (expected a3f9c2,
  serving 7b1e04)`, or `look: lane b`. Once.
- **Everywhere else:** appending anything does nothing, for anyone.
- **No-JS:** progressive enhancement only, never a server-side branch, which
  would be observable and cacheable for ungated requests too.

Open question: whether a gated production surface ever carries the reader.
That needs a client-readable admission signal, and none is assumed here.

## 3. DX

| Form | Shape | Meaning |
|---|---|---|
| Generation confirm | `look=g<7-64 hex>` | Source commit sha or prefix, compared against the page's own build-sha constant. |
| Lane-pinned | `look=l<12 hex>` | `hex(sha256("look|" + source_sha + "|" + lane))[:12]`: a confirmation code, not a lookup key. |

**The prefix byte is load-bearing.** Length alone cannot discriminate: 12 hex
characters is at once a valid short-sha prefix and a valid lane token. The
leading `g` or `l` is the only unambiguous discriminator, so any successor
formula must keep a tag.

**Derivation runs** at build time, beside whatever already inlines a build-sha
constant into the page. The step that sets the commit sha for a lane computes
per-lane expected values and inlines them. The page never hashes at runtime;
it compares an inlined constant against the parameter. Derivation is public
(§6): the token pins a generation, it does not gate one.

**a/b/c/d lanes, one hostname family:** fix one hostname per environment tier
and separate parallel QA lanes by the lane token, so a/b/c/d need no DNS
record or TLS cert. Serving several builds behind one host needs routing a
future substrate must provide; unspecified here.

**Reaper:** most sites have none, and a `ttl_hours` field in lane metadata is
commonly documented as inert, creating no reaper or retention policy. Do not
assume one exists. A future reaper could emit the expected token beside the
URL so a QA handoff packet carries a copy-paste line. Conditional, not a claim
about today.

## 4. AX

The assertion line is the whole AX surface: never blocking, never
re-announced. A QA prompt template handing a reviewer a live URL would append
the expected value, and its "surface to expected state" checklist gains one
line: "footer look assertion, confirmed." Cheaper than the rest: text
equality, not visual judgment.

The access log is the machine half: every `?look=` request is logged already,
no new code and no new PII. Auditing "was generation X served" is a log read.

## 5. Spec

Nobody acts now; the MUSTs bind the implementer.

- **A future build fabric** MUST pin the derivation as a versioned algorithm
  in substrate docs, not per-site, and MUST NOT gate any access decision on
  `?look=`: assertion, never authentication. Later: emit expected tokens as
  build metadata. Existing instance-routing metadata is untouched.
- **A shared static-site scaffold** later carries the assertion component and
  inlining convention as an opt-in pattern doc, never a gate.
- **This public reusable-CI repository** MUST hold only this redacted variant.
  Nothing here references `?look=` today.
- **A QA-prompt template repository** later appends `?look=` and asks for the
  assertion line, never replacing the live-URL requirement.

**No schema edit now.** A per-lane `look_enabled` flag would touch every copy
of the lane schema and is validated by an existing repo check, so it is
CI-bearing and waits until the mechanism exists.

## 6. Risks and non-goals

- **Not auth.** Derivation is public by design; anyone can compute a valid
  token for a public sha. Admission stays the network-level gate alone.
  `?look=` must never become an access check, a `Vary` input, or a server
  branch.
- **CDN cache keys.** A cache keyed on query strings fragments per token for
  no benefit, since the parameter never changes served bytes. Any CDN
  deployment MUST strip `look=` from the cache key.
- **Lane-name leakage.** The token hashes `source_sha + lane`, not the name,
  but with `a`-`d` and a public sha it is guessable in a few tries. Acceptable
  only because lane identity was never meant to be secret.
- **Non-goal: routing unification.** This defines the token, not what lets one
  hostname serve four lanes. That is substrate work.

## 7. Sequencing

Design now; zero CI-bearing change anywhere today. The build fabric this
depends on does not exist yet. Gates on: (1) that substrate existing and
ratifying its §3 derivation, (2) build-queue capacity recovering, (3) a
tracked decision rather than inference.

**Assumptions flagged:** §3's formula is unratified. "One hostname family"
assumes non-DNS routing existing nowhere today. Per-lane inlining assumes a
multi-lane build most sites lack; commonly it is one lane, one build.

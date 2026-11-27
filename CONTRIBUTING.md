# Contributing to pytest-rhiza

How to run the gates is in the README, under *Development* — that fence is what
`scripts/gates.py` executes and `tests/test_readme_gates.py` pins to `ci.yml`, so it stays
there. This file holds the decision history behind the repository's shape.

## Two things that were decided

Both of these were open questions while the split was being designed. They are settled
now, and the second went the opposite way to what was expected — which is the more useful
half to record.

**Version pinning: one number, and no literal in the README.** The worry was that a
separate distribution adds a second version axis to reason about. It does not, because the
pin travels in the template: it is one setting a consumer's sync writes, so a repo on a
given template release runs that release's assertions, exactly as file-copy delivery gave
for free. The alternative considered — aligning this package's `major.minor` with template
releases and pinning `~=` — was not taken.

What *did* need deciding was where the number is written, and the answer is nowhere in
the README. Nothing there bumps it and, until #17, nothing read it either, so the
documented pin sat at `0.1.0` for three releases. The example uses a placeholder, and
`tests/test_readme_pin.py` is what keeps a literal from creeping back.

**Removing the old folder: not required, because a leftover is inert.** The concern was
that a consumer keeps `.rhiza/tests/` on disk (a sync ceasing to deliver a file does not
delete it) and that the copy would then run twice, so a migration would need an explicit
removal step.

That was wrong, and for a reason worth knowing: the gate names **modules**, not paths. It
resolves `pytest_rhiza.checks.*` out of site-packages, so it never looks at the folder —
and `pythonpath = .rhiza/tests`, the one thing that used to make the folder importable, is
itself one of the five costs the README's *Why* section lists that the move removed. A leftover copy is unreachable
rather than duplicated. `rhiza-test` warns while the folder is still present, and deleting
it is tidying rather than a migration step.

## Why no Makefile, and why nothing calls jebel-quant/rhiza

This repository used to run rhiza's reusable CI (`rhiza_ci.yml`) like any consumer, and
mirrored a subset of its gates into a Makefile so a contributor could reproduce a red job.
Both layers are gone, because the dependency direction made the first one a cycle:
**`jebel-quant/rhiza` pins pytest-rhiza as a dependency** — its `pyproject.toml` carries
`pytest-rhiza @ git+…`— so this repository calling rhiza's CI meant rhiza's workflow
running the gates that judge the package rhiza depends on. Every other consumer gets a
one-way edge; this one got a loop.

One rhiza workflow stays: `rhiza_release.yml`, at the exact path PyPI Trusted Publishing
validates. It checks the path, not the contents, so the file's `uses:` lines are SHA-pinned
like every other workflow's (#103). The `rhiza_codeql.yml` and
`rhiza_scorecard.yml` stubs are gone — they called rhiza's reusable CodeQL and OSSF
Scorecard workflows, a pinned edge to keep current for scanning this repository does not
depend on.

The *scanning* came back in #86, as `codeql.yml` and `scorecard.yml`. Only the edge was
ever the objection: both now call `github/codeql-action` and `ossf/scorecard-action`
directly, SHA-pinned like every other third-party action here, so there is no `uses:` line
pointing at rhiza and no cycle. They earn their place beside `security` because bandit
pattern-matches one file at a time and never follows a value across a boundary, and
because nothing else here scores this repository's own supply-chain posture.

The cost of dropping the Makefile was real and was stated plainly in the README for three releases:
**no gate had a local entry point at all** (#49, #32). That was the call made in #52 — a
Makefile in a repo whose ecosystem retired make as an interface is a second thing to keep
correct — and it meant the only way to run a gate by hand was to read its command line out
of `ci.yml`, which #58 improved to a copy-paste out of the README.

`scripts/gates.py` closes it (#66) without giving any threshold a second home, because it
holds no recipes: it executes the README's gate fence, which `tests/test_readme_gates.py` already
pins to `ci.yml`. That is the distinction #52 was actually protecting — not "no runner", but
no *second copy* of what to run. There is still no `Makefile`, and nothing here invokes
`rhiza-task`.

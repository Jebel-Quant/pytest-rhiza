# Security policy

## Why this file exists

`pytest-rhiza` is a runtime dependency of every rhiza-managed repository's test environment.
Anything entering this package's dependency closure propagates into all of them, which is the
same reason the `audit` and `license` gates run on every push rather than weekly. A private
route for reporting a vulnerability follows from that: a finding here is a finding in every
consumer at once, and a public issue is the wrong place to say so first.

## Reporting a vulnerability

Use GitHub's private vulnerability reporting:
**[open a report](https://github.com/Jebel-Quant/pytest-rhiza/security/advisories/new)**.
It is private to the maintainers, and it is the preferred route because the discussion, the
fix and the advisory stay attached to the same record.

Please do **not** open a public issue for a suspected vulnerability. For anything that is not
a vulnerability — a failing check, a false positive, a gate that misreads a repository —
a normal [issue](https://github.com/Jebel-Quant/pytest-rhiza/issues) is right and welcome.

Expect an acknowledgement within **7 days**. This is a small project maintained on a
best-effort basis; if a report goes unanswered past that, please escalate by opening a
public issue that says a private report is outstanding, without the details.

## Supported versions

Fixes land on the latest release. There are no maintenance branches for older lines: the
package is small, and consumers pin it as a single version, so the supported version is
whatever `main` most recently tagged.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| Anything earlier | No — upgrade |

## What is in scope

The package's own code and its declared dependency closure:

- the checks under `pytest_rhiza.checks` and the fixtures in `pytest_rhiza.plugin`;
- the private helpers, in particular `_process` (it spawns child processes) and `_fences`
  (it parses README content that `checks/test_readme_validation` then executes);
- the three runtime dependencies, and anything they pull in.

Two things are deliberately **not** vulnerabilities in this package:

- **A check executing content from the repository under test.** `test_readme_validation`
  runs the `python` fences in a consumer's own `README.md`, and `scripts/gates.py` runs the
  command lines in this repository's. Both are by design and documented where they happen;
  the trust boundary is the repository's own reviewed content, the same boundary `pytest`
  itself crosses when it imports a `conftest.py`. A way to cross it *from outside* that
  content — an injection through a path, an environment variable, or a manifest value — is
  in scope and worth reporting.
- **Findings in a consumer repository** that this package's checks report. Those are the
  checks working.

## What a report is most useful with

The version, the Python version, and a minimal repository layout that reproduces it. The
suite's `subject` fixture in `tests/conftest.py` builds throwaway repositories for exactly
this purpose, and a failing case written against it is the fastest possible path to a fix.

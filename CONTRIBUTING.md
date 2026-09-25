# Contributing

Bug reports, questions, and code suggestions are welcome as **issues**. This
project does not accept outside pull requests — please read the next section
before opening anything.

## Pull requests are not accepted

**Outside pull requests are closed unmerged, regardless of quality.** If you
have a code change to propose, open an issue describing it and link your code
as a [GitHub Gist](https://gist.github.com/). The maintainer reads the gist and
applies the change by hand, under their own review, with attribution in the
commit.

This is a deliberate security posture rather than a backlog problem or a
judgment about contributors. GitHub Actions workflows run with elevated trust
once an author has had a pull request merged into the repository: their later
fork runs start automatically, at PR-open time, before any human looks at the
diff. A project that never merges an outside pull request keeps *every* fork
run behind a manual approval gate, at every submission rather than only the
first. Merging one good PR would permanently weaken that gate for that author,
so the rule holds without exceptions.

Routing code through an issue plus a gist gets the same change considered on
the same merits, and keeps the CI trust boundary intact.

## Proposing a code change

1. **Open an issue** describing the problem and the change you propose.
2. **Link a gist** containing the diff or the changed files. A unified diff
   (`git diff > change.patch`) is easiest to apply, but whole files are fine.
3. **Say how you tested it.** See [README.md#build-and-install](README.md#build-and-install)
   for the build and `ctest` commands, and say which toolchain and CPU tier
   you ran on.

Three things make a proposal much easier to accept:

- **Keep it scoped.** A change that mixes an unrelated refactor with the actual
  fix is harder to review and slower to land.
- **Say whether it changes emitted bytes.** Any change to what the encoder
  emits changes the encoder fingerprint and requires every bank to be
  re-baked; see [docs/DETERMINISM.md](docs/DETERMINISM.md). A change that is
  meant to leave vectors alone should say how you checked that they did — for
  example `semb verify` against the reference bank.
- **Regenerate, don't hand-edit, generated files.** Fixtures, golden files and
  `docs/certification-identity.json` are produced by tools in `tools/`;
  regenerate them with the tool and say so in the issue.

Response time has no fixed SLA.

## Reporting bugs

Open an issue with: what you expected, what happened, the platform, the output
of `semb --version`, and — if it is a determinism issue — the smallest input
that reproduces it and the two manifests (`semb inspect`) whose vectors
disagree. See [SECURITY.md](SECURITY.md) instead if it is a security issue.

## License

By proposing a change through an issue or gist, you agree it is licensed under
this project's [Apache 2.0 license](LICENSE).

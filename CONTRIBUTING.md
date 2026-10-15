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

This is a deliberate security posture. Under GitHub's **Require approval for
all external contributors** fork-approval setting, a repository that never
merges an outside pull request keeps fork workflow runs behind approval.
That setting also requires approval after an outside contribution is merged.
Under first-time-contributor settings, a merged commit or pull request can
remove the approval requirement. The boundary depends on the selected
[fork-approval setting](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/enabling-features-for-your-repository/managing-github-actions-settings-for-a-repository#controlling-changes-from-forks-to-workflows-in-public-repositories).
The repository's current CI workflow runs only by manual dispatch.

Routing code through an issue plus a gist gets the same change considered on
the same merits, under the maintainer's review.

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
- **Say whether it changes emitted bytes.** The fingerprint covers the model,
  tokenizer, composition literals, executed witnesses and certification epoch;
  changing any of these changes it and requires banks to be re-baked. A code
  change outside what the witnesses execute can change output without moving the
  fingerprint. The certified set and `semb verify` against the reference bank
  check for such changes on the certification corpus; see
  [docs/DETERMINISM.md](docs/DETERMINISM.md). A change meant to leave vectors
  alone should say how you checked that they did.
  <!-- REL-4: verify against the committed docs/certified-builds.json and docs/certification/reference-bank/ before tagging -->

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

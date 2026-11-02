# Git workflow

How branches, commits and pull requests are made in this repo, by a human or an agent. It is my standard git workflow from another project, with this repo's attribution rule (see the end of "Commit messages").

[.claude/settings.json](../settings.json) decides what an agent may run without asking; it does not forbid the workflow below. Plain `git push --force`, `-f`, `--mirror` and `git filter-branch` are denied, because they rewrite history other people may share. `git push --force-with-lease` asks first: it is the normal last step of catching up your own branch.

## Branches

Trunk-based development: every change goes on a short branch from an up-to-date `main` and lands through a pull request. One branch per task.

- **Names:** `category/description-with-dashes`, lower case, no underscores or spaces. Categories: `feature/`, `bug/`, `docs/`, `hotfix/`, and `release/` if one is ever needed. Pick the category from what the change does: new eval tooling is `feature/`, a README fix is `docs/`.
- **Size:** one atomic piece of work. `docs/fix-typo` is too small (fix it on the branch it belongs to). A branch whose description needs "and" is probably two.
- **Catching up:** rebase your branch onto `main` (`git pull --rebase origin main`), then `git push --force-with-lease`. Never merge `main` into a feature branch: it leaves a merge commit inside the branch, so the branch no longer reads as a clean sequence of decisions. The one exception is a branch someone else has built on, which was never yours to rebase.
- **Direction:** rebase out of `main`, merge into `main`. Never rebase `main` itself.

## Commit messages

```text
tag(scope): Header

Body

Footer
```

- **Header:** imperative mood, at most 50 characters, for example `feat(retrieve): Add the Danish query glossary`.
- **Tags:** `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`. The scope is the part of the repo it touches: `ingest`, `retrieve`, `answer`, `kpi`, `ui`, `mcp`, `evals`, `git`, `readme`.
- **Body:** what changed and why, not how. Name the design choices and their reasons, with numbers where there are any. Lines of at most 72 characters.
- **Footer:** issue references, breaking changes, co-author trailers.
- **One working step per commit.** Each commit leaves ruff, mypy and pytest passing. If the header needs "and", it is probably two commits.
- **Author:** `Anders Henriksen <anhenr.dev@gmail.com>`. Never override the author.
- **Attribution:** commits made with Claude Code end with its `Co-Authored-By:` trailer, and pull request bodies with its "Generated with Claude Code" line. This repo shows how it was built with Claude Code, so the history says so too (decision 12).

History before November 2026 uses plain sentence headers. It is not rewritten.

## Pull requests

- Open from the branch into `main` with `gh pr create`. The title is the commit header; GitHub uses it as the header of the squash commit.
- The body has a `## Summary` (what changed and why) and a `## Test plan` (what was run and what it showed, with numbers).
- CI must be green: lint, types, tests and the secret scan.
- I review and squash-merge; the branch is deleted on merge. An agent opens a pull request when the task asks for one, and never merges it.

The [commit-push-pr](../commands/commit-push-pr.md) command runs the whole sequence.

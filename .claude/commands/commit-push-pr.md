---
description: Commit, push and open a pull request, following .claude/reference/git-workflow.md. Asks whether to use the staged files as they are or everything this conversation touched.
argument-hint: (optional) one line of context for the PR body
---

# Commit, push and open a pull request

Take local changes to a pushed branch and an open pull request, following the branch, commit and PR rules in [git-workflow.md](../reference/git-workflow.md) exactly. Be brief throughout.

Invoking this command is the go-ahead for this commit, push and pull request: carry out all three without asking again. It is not a go-ahead to merge, to push to `main`, or to rewrite history anyone else shares.

## 1. Find the two candidate sets of files

- **Staged:** `git diff --cached --name-only`.
- **This conversation's changes:** every file this conversation created or edited, checked against `git status --short` so that anything already committed drops out.

If both are empty, say so and stop. If they are the same, or one is empty, use the other and skip step 2.

## 2. Ask which set to use

Only when both sets are non-empty and differ, ask with `AskUserQuestion`, listing each set's file paths in the option descriptions:

- **Staged changes:** commit exactly what is staged.
- **This conversation's changes:** commit only the files this conversation touched; leave any other staged file out of this commit.

## 3. Check, branch and commit

1. Fix the index to match the chosen set: `git restore --staged` what is out of scope, `git add` what is in scope, by exact path. Never `git add -A` or `git add .`.
2. Never stage anything under `data/`, a PDF or `.env`.
3. Run `uv run ruff check . && uv run ruff format --check . && uv run mypy src`, then only the tests for the Python modules that changed: their test files and any test file that imports them. Docs-only changes need no tests. If search, routing, the glossary or the eval questions changed, also run `uv run python evals/check_retrieval.py`. CI runs the full suite. Stop and report if anything fails.
4. If on `main`, create a branch from an up-to-date `main` (`git pull --ff-only` first), named `category/description-with-dashes` by what the files do.
5. Write the commit message as `tag(scope): Header`, body and footer, from the staged diff (`git diff --cached`), not from memory. The body says what changed and why, never how. End it with the Claude Code co-author trailer. No em dashes.

## 4. Push and open the pull request

1. `git push -u origin <branch>`.
2. `gh pr create` with the commit header as the title and a body with `## Summary` and `## Test plan`, ending with the Claude Code line.
3. Report the pull request's URL.

One run makes one branch and one pull request. If the chosen files are clearly two unrelated pieces of work, say so and suggest splitting them; do not split them yourself.

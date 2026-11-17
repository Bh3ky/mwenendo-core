# RULES.md

Hard rules for any AI agent working in this repository. They override convenience, speed and "obvious" fixes. If a rule blocks a task, stop and ask.

## 1. Never modify files without asking first

- Do not create, edit, rename, move or delete any file until the user has approved that specific change.
- "Asking" means saying what you intend to change and why, then waiting for a yes. Approval for one change does not cover the next one.
- Explaining, reading and proposing are always fine. Writing is not, until approved.

**Why:** This is a learning project. The user learns by understanding and often by writing the code themselves. Silent edits take that away, and they also leave the user with code they can't explain in an interview. It is also their repository, so they decide what goes in it.

## 2. Never delete or reset the development database

- Do not delete, truncate, drop or recreate the dev database, or any of its tables or rows. This covers `db.sqlite3`, the Postgres dev database and its Docker volumes.
- Do not run `flush`, `sqlmigrate`-then-apply shortcuts, `migrate <app> zero`, `DROP`, `TRUNCATE`, `docker compose down -v`, `docker volume rm`, or any command with the same effect.
- Do not edit or delete existing migrations that have been applied. Add a new migration instead.
- If a reset really is the right fix, explain why, show the exact command and what will be lost, and wait for explicit confirmation.
- Run tests only against the test database that pytest-django creates. Never point tests or scripts at the dev database.

**Why:** Dev data, such as hand-built inventory scenarios and admin users, takes time to rebuild. More importantly, "just wipe it and re-migrate" hides the problem. Learning to fix a broken migration or constraint without destroying state is a core production skill, because production databases can't be wiped.

## 3. No destructive or hard-to-reverse actions without confirmation

Always ask first before:
- `git reset --hard`, `git clean`, force-push, branch deletion, history rewrites
- Committing, pushing or opening PRs (only when the user asks)
- Deleting files or directories, or recreating the virtualenv
- Installing, upgrading or removing dependencies
- Anything that touches a remote service, a deployed environment or real credentials

**Why:** These actions can lose work or can't be undone. Dependencies also shape the project, and each one should be a conscious choice, ideally recorded in an ADR.

## 4. Protect secrets

- Never read, print, commit or echo the contents of `.env` or any credentials file.
- Keep `.env.example` limited to placeholder values.
- Never put project details or personal details into requests to external services.

**Why:** Leaked secrets are one of the most common real-world backend failures. Good habits start now.

## 5. Stay in scope

- Make only the change that was approved. Don't refactor, reformat or "tidy up" neighbouring code. If you spot something, mention it.
- Don't add features, abstractions or files that were not agreed.

**Why:** Small, reviewable changes make clean commits, and clean commits are part of the portfolio.

## 6. Be honest about outcomes

- Report test failures, errors and skipped steps exactly as they happened. Never claim something works unless it was run and verified.

**Why:** Debugging is the skill being built here. Hiding or smoothing over failures defeats that.

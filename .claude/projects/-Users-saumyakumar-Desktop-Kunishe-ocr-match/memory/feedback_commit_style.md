---
name: Commit style preferences
description: User wants small conventional commits with no co-author line
type: feedback
---

Always make small, focused commits with conventional commit messages (e.g., `feat:`, `fix:`, `refactor:`, `docs:`, `chore:`). Keep messages short and concise.

**Why:** User prefers granular commit history and wants sole authorship on all commits.

**How to apply:**
- Do NOT add `Co-Authored-By` lines to any commit.
- Break work into small, logical commits rather than bundling changes.
- Use conventional commit format: `type: short description` (e.g., `feat: add invoice parser`, `fix: handle null dates`).
- Keep commit messages to one line when possible.

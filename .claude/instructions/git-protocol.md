# Git Protocol

Fast builds need safe foundations. These rules prevent losing work during a 24-hour sprint.

## Branch Strategy

```
main              <- stable, demo-ready at all times
├── cooper/*      <- Cooper's integration work
└── rafa/*        <- Rafa's AI/ML work
```

- **main is sacred.** Only merge tested, working code.
- Work on feature branches: `cooper/tello-capture`, `rafa/moondream-pipeline`, etc.
- Merge to main at integration checkpoints (H+2, H+4, H+6, etc.)

## Commit Conventions

Format: `type: description`

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`

```bash
git commit -m "feat: add ZMQ frame publisher for Tello stream"
git commit -m "fix: handle malformed nav JSON with hover fallback"
```

Keep commits small and frequent. One logical change per commit.

## Before Every Merge to Main

1. Pull latest main: `git pull origin main`
2. Rebase your branch: `git rebase main`
3. Test independently with mock data
4. Merge only if your track works in isolation

## Safety Rules

- Never force push to main.
- Never commit secrets (tokens, API keys). Use environment variables.
- Never commit large model weights. Add to .gitignore.
- Commit early, commit often. Losing 30 minutes of work to a bad state is worse than a messy history.
- If in doubt, commit what you have, then fix it in the next commit.

## Pre-Integration Checklist

Before the H+6 critical gate:
- [ ] Both tracks merged to main independently
- [ ] ZMQ channels verified (frames flowing, detections flowing)
- [ ] Mock fallback data committed to demo/
- [ ] No hardcoded paths or tokens in code

## Recovery

```bash
# Undo last commit (keep changes staged)
git reset --soft HEAD~1

# Stash current work
git stash
git stash pop

# Nuclear option (discard everything, go back to last good state)
git checkout main
git reset --hard origin/main
```

## .gitignore Essentials

Model weights, research material, env files, and OS artifacts must stay out of the repo. The existing .gitignore should cover these. If you add a new large file type, update .gitignore before committing.

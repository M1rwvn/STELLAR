# Working together (Annex 4)

## GitHub

- **No direct push to `main`.** Protect it: Settings → Branches → Add rule for `main` →
  *Require a pull request before merging* (1 approval) + *Require status checks* (CI).
- One branch per person / feature, English names:
  `feature/backend-api`, `feature/auth`, `feature/risk-model`, `feature/digital-twin`,
  `feature/fusion`, `feature/flutter-app`, `feature/dashboard`, `fix/<short-name>`.
- Every PR is reviewed by at least one other person. CI (pytest) must be green.
- Commit messages: imperative and clear — `Add risk history endpoint`, `Fix SpO2 range validation`.

```bash
git checkout main && git pull
git checkout -b feature/risk-model
# ... work ...
git add -A && git commit -m "Add predict_risk with Random Forest model"
git push -u origin feature/risk-model      # then open a Pull Request
```

## Contract

- The contract is [docs/API_CONTRACT.md](API_CONTRACT.md), locked as Version 1 on day 4.
- Any change: say it in the group **first**, then a PR that updates the doc and `app/schemas.py`.

## Daily

- 10-minute stand-up in the group: *What did I do yesterday? What today? What is blocking me?*
- Stuck more than 2 hours → say it in the group immediately.
- Update your cards on the board every day ([BOARD_TASKS.csv](BOARD_TASKS.csv)).
- From day 26: **no new features**, only fixes and polish. Code freeze day 31.

## AI team

Drop your module in `ai_modules/` and run `python -m pytest tests/test_ai_contract.py -v`
before the PR. See [ai_modules/README.md](../ai_modules/README.md).

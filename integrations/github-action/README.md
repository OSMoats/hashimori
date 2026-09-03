# Governance as a pull request

The intake form nobody fills out honestly is a web form. The one they do is a
file in their own repo. This integration turns AI use case intake into a PR:

1. A team adds/updates `ai-intake/<use-case>.json` in their repo.
2. CI runs Hashimori against your org's rule packs.
3. The decision lands as a check: red zone → ❌ fail with the remedy in the
   log; needs review → ⚠ neutral + auto-assign reviewers; fast track → ✅.
4. Merging the PR *is* the record — decision, rules version, and intake are
   all in git history.

## Example workflow

```yaml
# .github/workflows/ai-governance.yml
name: AI governance
on:
  pull_request:
    paths: ["ai-intake/**.json"]

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # Your org's rule packs live in one governed repo
      - uses: actions/checkout@v4
        with:
          repository: your-org/governance-rules
          path: governance-rules

      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }

      - run: pip install git+https://github.com/OSMoats/hashimori

      - name: Evaluate changed intakes
        run: |
          set +e; status=0
          for f in $(git diff --name-only origin/${{ github.base_ref }} -- 'ai-intake/*.json'); do
            echo "::group::$f"
            hashimori evaluate --rules governance-rules/rulepacks --context "$f" --exit-code
            rc=$?
            echo "::endgroup::"
            if [ $rc -eq 2 ]; then
              echo "::error file=$f::Red zone — see the remedy above for the path to yes."
              status=2
            elif [ $rc -eq 78 ] && [ $status -eq 0 ]; then
              status=78
            fi
          done
          if [ $status -eq 78 ]; then
            echo "::warning::Needs human review — reviewers will be assigned."
            exit 0   # neutral: let the review requirement gate the merge instead
          fi
          exit $status
```

Exit codes from `--exit-code`: `0` approved · `78` needs review · `2` denied.

Pair `78` with a `CODEOWNERS` entry on `ai-intake/` so "needs review" assigns
your security reviewers automatically, and branch protection does the rest —
your GRC workflow is now just… code review.

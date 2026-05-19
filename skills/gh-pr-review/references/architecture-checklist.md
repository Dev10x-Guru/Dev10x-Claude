# Step 4b: Architecture Evaluation (GH-916)

**Independent of prior review comments.** Do NOT anchor on
whether surface bugs from previous cycles were fixed — evaluate
the PR's structural compliance from scratch.

## Load project architecture rules

- `CLAUDE.md` — coding style, patterns, SRP
- Project-specific `code-implementation.md` (if exists)
- `review-checks-common.md` § Architecture Checklist

## Check each new or substantially modified file

| Signal | Violation | Severity |
|--------|-----------|----------|
| New endpoint/view with >50 lines | Missing service layer extraction | WARNING |
| View calling repository directly | Missing Service layer (View→Service→Repository) | WARNING |
| Inline dict with 4+ keys passed across boundaries | Missing DTO | INFO |
| Manual `request.data["field"]` parsing | Missing serializer/DTO validation | WARNING |
| Function/method >50 lines | SRP violation — extract | WARNING |

## Anti-pattern: anchoring bias

When previous review comments exist, the skill tends to check
only whether those bugs were fixed and declare the PR "solid".
This step forces an independent structural evaluation regardless
of prior feedback.

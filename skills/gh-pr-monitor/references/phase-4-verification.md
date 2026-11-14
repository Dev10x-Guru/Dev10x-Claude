# Phase 4: Acceptance Criteria Verification

## Phase 4: Acceptance Criteria Verification

After Phase 3 completes, verify acceptance criteria before the
agent's final status report. This catches uncommitted files,
failing checks, or incomplete work that earlier phases missed.

1. Invoke the verification skill:
   ```
   Skill(skill="dev10x:verify-acc-dod")
   ```

   The skill auto-detects the work type from session context and
   adapts to the current friction level. At `adaptive` level it
   runs fully unattended — auto-passing or auto-failing without
   blocking the agent.

2. If all checks pass → include "Acceptance criteria: PASSED" in
   the final status report.

3. If any check fails → include "Acceptance criteria: FAILED" with
   the failing checks in the final status report. Do NOT re-enter
   earlier phases — report the failures and let the supervisor
   decide next steps.

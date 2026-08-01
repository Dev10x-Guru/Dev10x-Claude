# Session-Boundary Resilience Test Patterns

Testing patterns for verifying that orchestration skills handle
session-death and agent-resumption failures gracefully. These
patterns apply to multi-session orchestrators (work-on, fanout,
skill-audit, adr-evaluate, foreman).

## Simulate session death: mock SendMessage failure

When a session dies, `SendMessage` to a prior agent returns an error.
Test orchestrators by mocking this failure after agent spawn:

```python
@pytest.fixture
def mock_session_death():
    """Mock SendMessage failure that signals session death."""
    with patch("dev10x.domain.github.SendMessage") as mock_send:
        mock_send.side_effect = Exception("No transcript found for agent ID: ...")
        yield mock_send
```

**Test scenario**: Spawn an agent, then simulate session death via
mock. Verify the orchestrator:
1. Detects the `SendMessage` error (not `Exception`, the specific
   "No transcript found" message)
2. Respawns a fresh agent (not `SendMessage` resume)
3. Passes the previous run's handover comments to the fresh agent
   so it can re-derive state

**Assertion pattern**:
```python
# Agent was respawned, not resumed
assert mock_agent.call_count == 2  # original + fresh respawn
assert "No transcript found" in str(mock_send.side_effect)
# Fresh agent received handover context
assert "issue_get" in fresh_agent_prompt  # re-derive state
```

## Validate inherited claims before acting

Before a resumed orchestrator acts on a prior run's claims, it must
re-derive state from origin. Test this with a fixture that returns
false/missing data:

```python
@pytest.fixture
def stale_claims():
    """Prior run's assertions that are no longer valid."""
    return {
        "branch_existed": "feature/old-branch",
        "pr_status": "ready for review",
    }

@pytest.fixture
def current_state():
    """What origin actually has."""
    return {
        "branch_exists": False,  # Branch was deleted
        "pr_status": "closed",   # PR was merged
    }
```

**Test**: Resumed orchestrator receives `stale_claims` and calls
`pr_get` / `git branch -r` to re-derive. Verify:
1. Re-derivation calls are made (not skipped)
2. Orchestrator acts on the re-derived state, not the stale claim
3. If re-derived state contradicts the claim, orchestrator logs
   the divergence and adjusts

**Assertion pattern**:
```python
# Re-derive is called
mock_pr_get.assert_called_with(number=pr_number)
# Orchestrator uses re-derived state
assert "branch was deleted" in log_output
# Action branches on current state, not claim
assert action == "respawn" or action == "skip"
```

## Transcript-loss detection and respawn

Test that the orchestrator detects `SendMessage` errors and respawns:

```python
def test_session_death_triggers_respawn(mock_session_death, agent_spawn):
    """SendMessage failure triggers respawn, not resume."""
    orchestrator = MockOrchestrator(agents_to_spawn=1)
    
    # Spawn first agent
    agent_1 = orchestrator.spawn_agent("Analyze PR")
    
    # Session dies; SendMessage fails
    with pytest.raises(Exception, match="No transcript found"):
        orchestrator.send_message(to=agent_1.id, msg="continue")
    
    # Orchestrator detects failure and respawns
    agent_2 = orchestrator.spawn_agent("Analyze PR")
    
    # Verify respawn, not resume
    assert agent_1.id != agent_2.id
    assert agent_spawn.call_count == 2
```

## Durable handover and issue comments

Test that agents post handover state early and resumed orchestrators
read it:

```python
@pytest.fixture
def mock_issue_get():
    """Mock GitHub issue with agent handover comments."""
    return {
        "comments": [
            {"body": "Handover: PR at #123, branch 'feature/x', committed"},
            {"body": "Handover: PR #123 ready for review, all tests pass"},
        ],
    }

def test_resumed_orchestrator_reads_handover(mock_issue_get):
    """Resumed run reads handover comments, not run directory."""
    # Prior run posted handover to issue comment
    comments = mock_issue_get["comments"]
    assert "Handover:" in comments[0]["body"]
    
    # Resumed orchestrator reads it
    handover = parse_handover_comments(comments)
    assert handover["pr_number"] == 123
    assert handover["status"] == "ready for review"
    
    # Orchestrator acts on handover, not run directory
    assert "run_directory" not in input_to_orchestrator
```

## Parametrized session-boundary failure test

Test that the orchestrator handles failures at each phase:

```python
@pytest.mark.parametrize("failure_phase", [
    "after_agent_spawn",      # Session dies right after spawn
    "during_agent_work",      # Dies mid-turn
    "after_artifact_posted",  # Dies after PR is created
])
def test_session_death_at_each_phase(failure_phase, mock_session_death):
    """Orchestrator recovers from session death at any phase."""
    orchestrator = MockOrchestrator()
    
    # Spawn agent
    agent = orchestrator.spawn_agent("Work on PR")
    
    if failure_phase == "after_agent_spawn":
        # Session dies immediately
        kill_session()
    elif failure_phase == "during_agent_work":
        # Simulate agent progress, then session dies
        orchestrator.send_message(to=agent.id, msg="status?")
        kill_session()
    elif failure_phase == "after_artifact_posted":
        # Agent posts PR comment, then session dies
        agent.post_comment_to_issue("PR ready at #123")
        kill_session()
    
    # Resumed orchestrator recovers
    assert can_read_handover_comments()
    assert respawned_agent_count >= 1
```

## Anti-patterns to avoid

**❌ Testing resume-first without detecting session death:**
```python
# BAD: Assumes SendMessage always succeeds
orchestrator.send_message(to=prior_agent.id, msg="continue")
assert prior_agent.responded  # Fails if session died
```

**✅ Correct: Test failure case explicitly**
```python
# GOOD: Expect and handle the error
with pytest.raises(Exception, match="No transcript found"):
    orchestrator.send_message(to=prior_agent.id, msg="continue")
# Then verify respawn path is taken
assert fresh_agent_spawned
```

**❌ Testing against run directory state:**
```python
# BAD: Tests rely on /tmp files surviving
run_dir = f"/tmp/run-{session_id}"
assert (run_dir / "manifest.json").exists()
```

**✅ Correct: Test against durable artifacts**
```python
# GOOD: Tests rely on issue comments and git branches
comments = issue_get(number=ticket_number)["comments"]
branch_exists = git_branch("-r").find(branch_name) >= 0
```

## Related patterns

- `references/resilience-patterns.md` — the contract that tests
  verify (Rules 1-4)
- `references/orchestration/subagent-status-protocol.md` — agent
  status reporting that orchestrators parse when resuming

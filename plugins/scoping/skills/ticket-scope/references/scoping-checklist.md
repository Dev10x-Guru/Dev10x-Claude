# Scoping Checklist

Use this checklist to ensure comprehensive scoping coverage.

## Context Gathering

- [ ] Starting point determined (existing ticket or scratch)
- [ ] Existing ticket context fetched (if applicable)
- [ ] Problem description captured
- [ ] Code references identified
- [ ] Related files read and analyzed
- [ ] Patterns from existing code noted

## Requirements

- [ ] Problem statement clear
- [ ] Business value articulated (for business features)
- [ ] Acceptance criteria defined
- [ ] Out of scope explicitly stated
- [ ] Edge cases considered

## Technical Design

### Architecture
- [ ] Repositories identified (new/existing)
- [ ] Services identified (new/existing)
- [ ] DTOs defined (new/existing)
- [ ] Models identified (new/existing)
- [ ] Clean Architecture boundaries respected

### Database
- [ ] Database changes identified
- [ ] Migration strategy defined
- [ ] Data backfill plan (if needed)
- [ ] Multi-database routing considered
- [ ] Rollback procedure defined

### GraphQL (if applicable)
- [ ] Schema changes identified
- [ ] Breaking changes assessed
- [ ] Mutations/queries designed

### Dependency Injection
- [ ] Services to register identified
- [ ] Dependency patterns noted

## Implementation Plan

- [ ] Steps ordered logically
- [ ] Each step has file path
- [ ] Each step has pattern reference
- [ ] Each step has code reference
- [ ] Test requirements implicit (follow CLAUDE.md)

## Risk Assessment

### Dependencies
- [ ] Dependent tickets identified
- [ ] Related tickets noted
- [ ] Blocking tickets listed
- [ ] External dependencies noted

### Technical Risks
- [ ] Race conditions assessed
- [ ] Complexity hotspots identified
- [ ] Unknown unknowns flagged
- [ ] Breaking changes identified
- [ ] Performance impact considered
- [ ] Data integrity risks assessed

### Rabbit Holes
- [ ] Potential derailers listed
- [ ] Scope creep prevented

## Rollout Strategy

- [ ] Migration approach defined (if needed)
- [ ] Feature flag assessed (if needed)
- [ ] Backwards compatibility verified
- [ ] Rollback plan defined (if high-risk)
- [ ] Deployment order determined

## Monitoring (Optional)

- [ ] New metrics proposed (if applicable)
- [ ] Alerts proposed (if applicable)
- [ ] Key log statements identified
- [ ] Sentry context defined

## Estimation & Categorization

- [ ] Estimated via `dev10x:estimate` (points + five line items,
      effort vs elapsed)
- [ ] Task type categorized (business/technical/bug)
- [ ] Release notes requirement determined

## Documentation Format

- [ ] Appropriate template selected:
  - Business Feature → Include release notes draft
  - Technical Task → Technical depth only
  - Bug Fix → Include resolution summary
- [ ] All sections completed
- [ ] Code references included
- [ ] Format clear for coding agent

## Approval & Finalization

- [ ] Document shown to user
- [ ] User feedback incorporated
- [ ] User approval obtained
- [ ] Linear ticket created/updated (if requested)
- [ ] Scoping document saved to /tmp/Dev10x/ticket-scope/

## Quality Checks

- [ ] Can a coding agent implement from this scope alone?
- [ ] Are all file paths specific and correct?
- [ ] Are patterns referenced clearly?
- [ ] Are risks and mitigation clear?
- [ ] Is the estimate reasonable?
- [ ] Does format match task type?

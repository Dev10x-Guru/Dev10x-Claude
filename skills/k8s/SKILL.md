---
name: Dev10x:k8s
description: >
  Kubernetes cluster operations via aws-vault authenticated kubectl.
  Check deployments, pods, logs, events, and runtime configuration
  across environments.
  TRIGGER when: investigating service health, comparing staging and
  production, checking restart loops or OOM kills, or verifying what
  is running versus what git says should be running.
  DO NOT TRIGGER when: retrieving secrets (use Dev10x:aws-vault), or
  you need to MUTATE cluster state (apply, create, delete, scale,
  exec, port-forward) — those run only under direct supervisor
  control in a separate terminal.
user-invocable: true
invocation-name: Dev10x:k8s
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh:*)
---

# Kubernetes Operations

## When to Use

- Checking pod status or logs for a service
- Comparing deployments across staging and production
- Investigating service health or restart loops
- Verifying runtime configuration of a deployment
- Checking what's running vs what git says should be running

## Prerequisites

- `aws-vault` configured (see `Dev10x:aws-vault`)
- `kubectl` installed and configured with cluster contexts
- Service registry at `~/.config/Dev10x/aws-vault/service-registry.yaml`

## Service Registry

Read `~/.config/Dev10x/aws-vault/service-registry.yaml` to resolve:

- Environment → `aws_vault_profile` and `k8s.context`
- Environment → `k8s.namespace`

A starting template ships at
`${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/references/service-registry.example.yaml`.

## Wrapper Script

All kubectl operations go through the wrapper:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh <env> <kubectl-args...>
```

The wrapper reads the service registry to resolve the profile, context,
and namespace — no manual lookup needed.

**Read-only by contract.** The wrapper accepts only read verbs (`get`,
`describe`, `logs`, `top`, `events`, and similar). Mutating verbs —
`apply`, `create`, `delete`, `scale`, `exec`, `port-forward` — are
rejected. To inspect a pod's environment, read the deployment spec
rather than `exec`-ing into the pod.

## Common Operations

### Check pod status

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging get pods -l app=<service>
```

### Stream logs (live)

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  logs -l app=<service> --tail=100 -f
```

### Recent logs (snapshot)

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  logs -l app=<service> --tail=200 --since=30m
```

### Check deployment

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get deployment <service> -o yaml
```

### Check environment variables in a deployment

`exec` is not available through the read-only wrapper. Read the
injected environment from the deployment spec instead:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get deploy <service> -o jsonpath='{.spec.template.spec.containers[0].env}'
```

### Check recent events (crashes, OOM, restarts)

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get events --sort-by='.lastTimestamp'
```

### Compare deployment images across environments

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get deploy <service> -o jsonpath='{.spec.template.spec.containers[0].image}'

${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh production \
  get deploy <service> -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## Workflow: Investigate Service Issues

### Step 1: Check pod health

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get pods -l app=<service> -o wide
```

Look for: `CrashLoopBackOff`, `OOMKilled`, `ImagePullBackOff`,
high restart counts.

### Step 2: Check recent logs

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  logs -l app=<service> --tail=200 --since=15m
```

### Step 3: Check events

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  get events --sort-by='.lastTimestamp'
```

### Step 4: Check resource usage

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging \
  top pods -l app=<service>
```

## Key Lessons

### Secrets live in AWS Secrets Manager

Application secrets are managed in AWS Secrets Manager and injected
into pods via external-secrets-operator or init containers. Do not
look for credential values in k8s Secret objects directly — use
`Dev10x:aws-vault` instead.

### Use the service registry

Cluster contexts, namespaces, and profile names differ between
environments. Always resolve from the registry rather than
hardcoding a context or namespace.

## Related Skills

- `Dev10x:aws-vault` — secret retrieval and the kubectl wrapper
- `Dev10x:investigate` — root-causing a reported issue end to end

---
name: Dev10x:aws-vault
description: >
  Retrieve application secrets from AWS Secrets Manager and run
  strictly READ-ONLY kubectl commands via aws-vault. Handles
  environment-specific profiles and secret naming conventions
  resolved through a user-maintained service registry.
  TRIGGER when: fetching API keys, credentials, or any secret stored in
  AWS Secrets Manager; running read-only kubectl operations (get,
  describe, logs, top, events, etc.) against an aws-vault-protected
  cluster.
  DO NOT TRIGGER when: secrets are available in the local environment,
  the target is not an AWS-backed service, or you need to MUTATE
  cluster state (apply, create, delete, scale, exec, port-forward,
  etc.) — those run only under direct supervisor control in a
  separate terminal.
user-invocable: true
invocation-name: Dev10x:aws-vault
allowed-tools:
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh:*)
  - Bash(${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh:*)
  - AskUserQuestion
---

# AWS Vault Secret Retrieval

## When to Use

- Retrieving API keys or credentials for SaaS integrations
- Comparing secrets across staging and production environments
- Discovering available secrets for a service
- Running **read-only** kubectl operations against a cluster gated
  by aws-vault credentials (`get`, `describe`, `logs`, `top`,
  `events`, `explain`, `version`, `cluster-info`, `api-resources`,
  `api-versions`, `auth`, `wait`, `diff`)

## Critical Rules

**Secrets are NOT in the local environment.** SaaS API keys are stored
in AWS Secrets Manager and injected into k8s pods at runtime. Never
use `echo $VAR` or `printenv` to look for them. Always use the wrapper
scripts.

**REQUIRED: Call `AskUserQuestion` before accessing any secret** (do
NOT use plain text). Prompt: "I need to access the `<secret-id>`
secret in `<env>` — is that OK?" Only proceed after the user
approves. This applies even to read-only discovery lookups.

**Never call `aws secretsmanager` directly.** Use
`${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh` instead.

**Never call `kubectl` or `aws-vault exec ... kubectl` directly.**
Use `${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh`
instead.

**Never call `aws` or `aws-vault exec ... aws` directly.** Use
`${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh` instead. It
is strictly read-only: only `describe-*`, `list-*`, `get-*`,
`lookup-*`, `search-*`, `head-*`, `batch-get-*`, `view-*`, and
`estimate-*` operations pass through. Secret-exfil reads
(`secretsmanager get-secret-value`, `ssm get-parameter
--with-decryption`, `kms decrypt`, `sts get-session-token`,
`ec2 get-password-data`, `ecr get-login-password`, …) are denied
even though their verb is "get" — fetch secrets through
`secrets.sh` under the `AskUserQuestion` gate instead.

**The kubectl wrapper is strictly read-only.** Only the verbs
listed under "When to Use" pass through; mutating verbs
(`apply`, `create`, `delete`, `patch`, `scale`, `rollout`,
`exec`, `port-forward`, `proxy`, `cp`, `debug`, `set`,
`label`, `annotate`, `taint`, `drain`, `cordon`, `run`,
`expose`, `autoscale`, ...) are denied. Privilege-escalation
and cluster-redirection flags (`--as`, `--as-group`,
`--token`, `--server`, `--kubeconfig`,
`--insecure-skip-tls-verify`) are denied anywhere in the
argument list so the verb allowlist cannot be bypassed via
flag injection.

When the agent attempts a denied verb, the wrapper exits
non-zero and prints a copy-pasteable snippet (with profile,
context, namespace, and verb already substituted) for the
supervisor to run in a separate terminal under direct
control. The agent MUST NOT carry that snippet back through
any other tool — surface it to the user and stop.

## Service Registry

The scripts resolve environment/service mappings from a user-maintained
YAML registry at:

```
~/.config/Dev10x/aws-vault/service-registry.yaml
```

The registry maps:
- Environment name → `aws_vault_profile`, k8s `context`, `namespace`
- Service name → secret ID under `environments.<env>.secrets.<service>`
- Common key names → `secret_keys.<key_name>` (informational)

If the file is missing, copy the example from
`${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/references/service-registry.example.yaml`
to the path above and edit it for your environments.

## Workflow: Retrieve a Secret

### Step 0: Ask user confirmation

Call `AskUserQuestion` with the secret ID and environment. Only
proceed after explicit approval.

### Step 1: Resolve the registry entry

Read `~/.config/Dev10x/aws-vault/service-registry.yaml` to confirm
the environment and service key. If a mapping is missing, run the
Discover Secrets workflow first, then update the registry.

### Step 2: Retrieve the secret via wrapper

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh <env> <service> --key <KEY_NAME>
```

Examples (replace `<env>` and `<service>` with values from your
registry):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh staging api --key DATABASE_URL
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh production worker
```

### Step 3: Use the secret

Pass the value to downstream commands (curl, SDK calls, etc.).
Never log or echo the raw secret value.

## Workflow: Discover Secrets

When the secret ID or key name is unknown:

1. Confirm via `AskUserQuestion`.
2. Run without `--key` to retrieve the full JSON blob:

   ```bash
   ${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/secrets.sh staging api
   ```

3. Pipe through `jq 'keys'` (in a separate command) to list available
   keys without exposing values.
4. **Update the registry** at
   `~/.config/Dev10x/aws-vault/service-registry.yaml` under
   `secret_keys` so the mapping is reusable.

## Workflow: kubectl Operations (read-only)

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh <env> <verb> [args...]
```

The wrapper resolves `context` and `namespace` from the registry per
environment, then enforces a verb allowlist + flag deny-list before
invoking `aws-vault exec ... -- kubectl ...`.

Examples (all read-only):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging get pods
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging logs deploy/<svc> --tail=100
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh production describe pod/<name>
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh staging top pod
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/kubectl.sh production auth can-i get pods
```

### What is allowed

| Verb | Use |
|------|-----|
| `get` | List/read resources, optionally with selectors |
| `describe` | Verbose read; reveals Secret/ConfigMap *names* and structure |
| `logs` | Container logs (incl. `--follow`, `--previous`) |
| `top` | Pod/node metrics |
| `events` | Cluster event stream |
| `explain` | Schema reference |
| `version` | Client/server version |
| `cluster-info` | Cluster endpoints |
| `api-resources`, `api-versions` | API discovery |
| `auth` | `auth can-i` and read-only auth probes |
| `wait` | Block until a resource condition is met |
| `diff` | Compare a local manifest to live state (no mutation) |

### What is denied

Mutating verbs (`apply`, `create`, `delete`, `patch`, `scale`,
`rollout`, `exec`, `port-forward`, `proxy`, `cp`, `debug`,
`set`, `label`, `annotate`, `taint`, `drain`, `cordon`, `run`,
`expose`, `autoscale`, ...) exit non-zero with a snippet for
manual execution.

Privilege-escalation and cluster-redirection flags are denied
anywhere in the argument list — even with an allowed verb:

| Flag prefix | Why denied |
|-------------|-----------|
| `--as`, `--as-group` | RBAC impersonation |
| `--token` | Alternate credentials, bypasses aws-vault |
| `--server` | Points at a different cluster |
| `--kubeconfig` | Loads arbitrary kubeconfig |
| `--insecure-skip-tls-verify` | Disables cert validation |

### Caveat on sensitive reads

`describe secret` and `get secret -o yaml` are technically
read-only from the API's perspective but reveal base64-encoded
secret values. Treat them as you would a `secrets.sh` call:
the same `AskUserQuestion` confirmation gate applies before
invocation.

## Workflow: AWS CLI Operations (read-only)

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh <env> <service> <operation> [args...]
```

The wrapper resolves the `aws_vault_profile` from the registry per
environment, enforces a read-operation allowlist + secret-exfil
denylist, then invokes `aws-vault exec ... -- aws ...`.

Examples (all read-only):

```bash
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh staging ec2 describe-instances
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh production s3api list-buckets
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh staging logs describe-log-groups
${CLAUDE_PLUGIN_ROOT}/skills/aws-vault/scripts/aws.sh production sts get-caller-identity
```

Denied (exit non-zero with a copy-pasteable snippet): any mutating
operation (`create-*`, `delete-*`, `put-*`, `run-*`, `terminate-*`,
…) and the secret-exfil reads listed under Critical Rules. Run those
in a separate terminal under your own supervision.

## Key Lessons

### Secret IDs vary by environment

Cluster names and secret IDs differ between environments. Always
resolve from the registry rather than hardcoding paths. If the
registry entry is missing, run the discovery workflow first, then
update the registry.

### aws-vault profiles are per-environment

Each environment has its own IAM profile. The profile name is in the
registry under `aws_vault_profile`.

### Timeout on first use

`aws-vault exec` may prompt for MFA or open a browser for SSO on
first use. Use `--debug` if authentication fails silently:

```bash
aws-vault exec --debug <profile> -- aws sts get-caller-identity
```

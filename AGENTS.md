# Agent Instructions

## Repository Purpose

This publicly visible, proprietary repository contains sanitized Lightning IT
validation harnesses for ModuLix. Credentials, private artifact locations, and
generated evidence must remain outside Git.

Use it for:

- GitHub Actions workflows that run real integration tests
- validation inventories and matrices
- runner-specific preflight contracts
- nonsecret artifact references needed by tests

Do not put reusable automation logic here. Reusable runbooks belong in
`modulix-automation`. Role implementation belongs in the collection
repositories. Human operational procedures belong in `modulix-operations-lit`.

## Boundaries

- Keep committed content safe for the repository's public visibility.
- Keep secrets out of Git. Use GitHub Secrets, Vault, or short-lived tokens.
- Keep Red Hat downloads, signed URLs, AAP manifests, and RHSM credentials out
  of Git.
- Keep test matrices explicit and reviewable under `inventories/`.
- Prefer copy-paste-ready docs for manual validation commands.

## Collection Test Ownership

This repository owns the GitHub Actions execution layer for collection tests that use real infrastructure or private
runtime context. This includes protected Incus, Heavy, live, nightly, cross-collection, cross-service, upgrade,
disaster-recovery, and Application Acceptance runs.

Collection repositories continue to own reusable role code, Tiny tests, and environment-neutral scenario sources.
When a scenario is closely coupled to a role, leave its Molecule files in the collection and check out the exact
collection revision here. Do not fork or copy role implementation into this repository.

For every migrated collection test, this repository MUST own:

- the matrix and trigger policy;
- self-hosted runner labels and capacity checks;
- protected environments and secret references;
- infrastructure naming, ownership metadata, finalizers, and stale-resource cleanup;
- sanitized evidence and retention; and
- exact collection repository and commit inputs.

Collection release workflows MAY call a reusable workflow from this repository. Such calls must remain fail-closed,
must test the exact candidate SHA, and must not silently replace a required result with a skipped job.

## Extensible Nightly Validation Model

Nightly validation is organized as service suites. A suite validates a composed
service lifecycle on real, ephemeral infrastructure; it is not a replacement
for collection-level Molecule tests and must not copy reusable role logic into
this repository.

Use the following layout for each service suite:

```text
.github/workflows/<service>-incus-nightly.yml
.github/scripts/<service>-incus-matrix-run.sh
inventories/nightly/host_vars/<runner>/<service>_ci_matrix.yml
docs/<service>-incus-nightly.md
```

The service script is optional. Add only a thin product adapter when the shared
lifecycle and reusable runbooks cannot express the suite directly. Do not copy
Incus, Cloudflare, or product deployment implementations between suite scripts.

New suites, including HashiCorp Vault, Wunderbox, Satellite, and other composed
services, must:

- declare an explicit product, operating-system, image, and resource matrix
- use reusable roles and runbooks from `ansible-collection-*` and
  `modulix-automation`
- create run-unique Incus instances and record their owner, run ID, attempt,
  matrix entry, FQDN, and expiry as instance metadata
- validate deployment, functional health, TLS, and idempotent reruns where the
  product supports them
- collect diagnostics before destructive cleanup when validation fails
- implement product teardown, DNS cleanup, VM cleanup, and stale-resource
  garbage collection
- document required secrets, artifacts, routing, DNS, and subscription or
  license capacity

Matrices contain nonsecret settings and secret references only. Never put an
organization credential, activation key, token, password, signed URL, or other
secret value directly in a matrix. The existing AAP matrix contains legacy RHSM
values that require remediation and must not be copied into a new suite.

At minimum, every matrix entry identifies its stable name, product version,
guest operating system, Incus image, topology and node roles, CPU/memory/disk
limits, artifact references, DNS naming inputs, and retention policy. Add
service-specific fields only when they are part of a documented suite contract.

Do not list a service as current validation until its workflow, matrix, runner,
cleanup path, and service documentation exist and have completed successfully.

## Incus Lifecycle Contract

- Use `lit.ubuntu.incus_instance` for reusable Incus instance lifecycle. Do not
  reintroduce product-specific `deploy/incus` shell helpers in collection
  repositories.
- Keep Incus object names and guest hostnames DNS-safe and run-unique. Include a
  stable short run key derived from the workflow, matrix entry, run ID, and run
  attempt.
- Use a persistent, dedicated nightly Incus project and managed network with
  run-unique instances and ownership metadata. A suite may use a project per run
  only after project, profile, network, and failed-run cleanup are automated and
  validated. Until capacity permits parallel execution, use a shared
  cross-workflow concurrency group for the runner.
- Treat generated inventories as ephemeral artifacts. For DNS- and TLS-aware
  validation, use the guest FQDN as `inventory_hostname`; an IP address may
  still be used as `ansible_host` for transport.
- Store generated inventories, DNS record IDs, SSH keys, extra-vars files, and
  other run state in a run-owned temporary directory with mode `0600` wherever
  the file can contain sensitive data. Remove that state during finalization.
- Run cleanup from an unconditional finalizer and also provide a scheduled
  stale-resource collector. Shell traps alone do not cover runner loss or
  forced job termination.
- Retained failure environments must have an explicit expiry. Retain their DNS
  records and address allocation for the same period.

## Nightly DNS and TLS Contract

The private nightly namespace is:

```text
nightly.lab.l-it.io
```

Do not introduce `nightly.l-it.io` as another peer domain. `nightly` is a
validation namespace below the existing lab boundary, not a stage or exposure
boundary. Keep each runner and control-plane hostname in its actual inventory
stage and zone. The AAP Incus runner migrated from
`ciwkr01.prd.dmz.corp.l-it.io` to `ciwkr01.prd.edge.pub.l-it.io`; the protected
GitHub runner labels still gate the suite.

Use run-unique names such as:

```text
vault01-r123456.nightly.lab.l-it.io
wunderbox-r123456.nightly.lab.l-it.io
sat01-r123456.nightly.lab.l-it.io
```

Keep the first DNS label at or below 22 characters when a suite includes AAP,
because AAP EDA imposes a short-hostname constraint.

The target provider is Cloudflare Internal DNS through Cloudflare Gateway:

- create the internal forward zone and its DNS view once; do not create a zone
  for every run
- confirm Cloudflare feature entitlement and current service status during
  platform bootstrap and document the selected DNS view and resolver policy
- create an internal reverse zone for each routed Incus test subnet
- create A and PTR records, plus AAAA records when supported, after the
  instance address is allocated and before product deployment
- require the runner and guests to reach the matching Cloudflare Gateway
  resolver path before creating any service resources
- verify forward and reverse resolution from both the runner and the guest
- use the node FQDN consistently for cloud-init and inventory identity; use each
  run-scoped service endpoint FQDN consistently in application URLs and
  certificate SANs
- keep nightly records private and unproxied; never publish private guest
  addresses through the public Cloudflare zone or `pub.l-it.io`
- treat routing as a separate prerequisite: DNS does not make a NAT-only Incus
  address reachable outside the runner

If Cloudflare Internal DNS is unavailable, use an approved private
authoritative resolver and document the resolver path. Do not silently fall
back to public DNS or `/etc/hosts` when DNS behavior is part of the validation.
This is a target contract for new and migrated suites. Do not report DNS or TLS
coverage for an existing workflow until the complete record and certificate
lifecycle has been implemented and validated.

Cloudflare record lifecycle must be ownership-safe:

- use a runtime token restricted to DNS read/write access for the exact nightly
  forward and reverse zones; keep zone/view/bootstrap administration out of
  test jobs
- store the token in a protected GitHub Environment Secret or an external Vault
  and mark every task that handles it with `no_log: true`
- use `CLOUDFLARE_NIGHTLY_DNS_TOKEN` as the GitHub secret name and expose it as
  `CLOUDFLARE_TOKEN` only to the task that calls the provider
- document the exact nonsecret zone, view, and resolver identifiers and the
  secret references required by each suite
- attach the manager, service, run ID, attempt, instance, and expiry as record
  tags or comments and persist the returned record ID
- refuse to overwrite a record owned by another run
- delete by verified record ID and ownership metadata, never by a broad prefix
  or a destructive "only record" operation
- explicitly delete records during finalization; a short TTL controls caching
  but does not delete a record
- run a scheduled garbage collector for expired, positively identified records
  and matching Incus resources

Product teardown must run while DNS still resolves. Delete DNS records before
releasing the instance address and destroying the VM. If DNS deletion fails,
stop and retain the VM/address until the cleanup retry or garbage collector can
remove the record safely.

Cloudflare Internal DNS does not issue application certificates. Use an
approved internal test CA or an approved ACME DNS-01 flow, install the required
trust chain on the runner and guests, and validate the certificate chain,
hostname, and expiry. Do not use a proxy-only origin certificate for endpoints
that clients access directly. Never upload private keys, tokens, generated
passwords, Vault unseal or root material, signed URLs, or decrypted secret
output as diagnostics or workflow artifacts.

## Service-Specific Requirements

- **AAP:** preserve the existing EDA hostname limit, unregister RHEL before VM
  destruction, and validate the gateway through its FQDN with certificate
  verification enabled in DNS/TLS coverage profiles.
- **HashiCorp Vault:** do not use the ephemeral Vault target as its own bootstrap
  secret backend. Use the run FQDN in API and cluster addresses and TLS SANs,
  keep certificate validation enabled, isolate storage and secret paths by run,
  and revoke or remove test credentials and PKI leases during teardown.
- **Wunderbox:** treat it as a composed service suite. Give every exposed
  component a run-scoped FQDN, keep generated state isolated, and verify both
  individual services and cross-service integration.
- **Satellite:** require working forward and reverse DNS before installation,
  isolate subscription and content state, and unregister clients and remove
  test host records before DNS and VM cleanup.

## AAP Incus Nightly

The AAP Incus nightly workflow owns its matrix in:

```text
inventories/nightly/host_vars/ciwkr01.prd.edge.pub.l-it.io/aap_ci_matrix.yml
```

The workflow must:

- run only on runners with `self-hosted`, `linux`, `x64`, `incus`,
  `nested-virt`, and `aap`
- use short guest hostnames for AAP EDA safety
- keep `hub_seed_collections: false` by default for compatibility tests
- unregister RHEL guests before destroying Incus VMs
- destroy temporary Incus instances by default
- fail early on stale `aap-ci-*` instances

If `rhel_teardown.yml` succeeds, do not run a second RHSM unregister through
`incus exec` during destroy. Incus VM agent availability is not reliable during
late teardown.

## Validation

For workflow and shell changes, run:

```bash
shellcheck .github/scripts/*.sh
git diff --check
```

When `actionlint` is available, run:

```bash
actionlint
```

## Push-ready Agent Contract

Every pushed change is governed by this file and must be reviewed locally by
both Codex and GitHub Copilot CLI through:

```text
python3 scripts/lit-push-ready.py push-ready
```

Run it only for a clean, committed candidate. The gate fetches the
authoritative `origin/develop`, constructs the synthetic integration change,
runs the one repository-owned CI profile, and gives that exact diff plus these
instructions to both agents in read-only sandboxes. Copilot CLI must run only
inside the immutable Devtool container; do not install or invoke an
uncontrolled host Copilot binary. Codex must use its isolated read-only
configuration. Neither agent may mutate the reviewed tree or waive a failed
check.

Reconcile every actionable local finding, amend the candidate, and rerun the
complete gate until both agents and the deterministic profile pass. Push only
the reviewed branch and `HEAD` authorized by the fresh evidence. A pre-commit
hook may provide faster formatting feedback, but it is not the acceptance
boundary and must not trigger authenticated agent reviews.

GitHub Actions and the server-side GitHub Copilot pull-request review remain
authoritative. After any server finding or code change, update the candidate,
rerun the same local gate, and obtain a new current-head server review. The goal
is a first successful required pipeline run; do not use the PR as the first
place to discover locally reproducible failures.

The one-time v2 policy bootstrap cannot use its changed engine as its own trust
root. For that bootstrap only, run the committed canonical profile and
`python3 scripts/lit-push-ready.py review`; protected current-head GitHub
Actions and Copilot checks authorize merge. The exception ends once v2 is on
`develop`.

## Secret Storage Rule

- Never commit secret values, tokens, passwords, private keys, activation codes, or decrypted Vault output.
- When an external HashiCorp Vault (HC Vault) is configured for a role or runbook, generated credentials must be read from HC Vault first, generated only when missing, written back to HC Vault, and then consumed by the application from the Vault-backed Ansible variables. Do not keep generated plaintext secret files on the managed host unless a role has an explicit break-glass option such as `*_allow_local_secret_files=true`.
- A HashiCorp Vault validation suite must not depend on the ephemeral Vault target for bootstrap credentials. Bootstrap from an approved external secret backend or a workflow-scoped GitHub Secret, then keep all target state run-scoped.
- When an external HC Vault is not configured, required application credentials must be supplied from Ansible Vault encrypted inventory variables. Workflow-only provider credentials may use scoped GitHub Secrets. Do not add new plaintext generated-secret fallbacks.
- Tasks that read, generate, write, template, or compare secret material must use `no_log: true`.

<!-- LIT REP-60 review governance: start -->
<!-- cspell:ignore litroc -->

## REP-60 current-revision review governance

- Local validation is deterministic only. It must never invoke Codex, GitHub
  Copilot, another model, or an external AI endpoint. Authoritative AI review
  runs only in the protected GitHub pipeline and binds the exact PR head.
- Lightning IT automation may request and fund one GitHub Copilot review only
  when the exact PR author is `litroc`, and only at the finalization boundary;
  intermediate `synchronize` pushes must not trigger AI review. Any finding
  requires correction and a final current-head re-review. The request is
  consumed once per head; unavailable or quota-blocked reviews fail closed
  without an automatic retry. Organization-funded Codex remediation and its
  single re-review are likewise restricted to `litroc`.
- Every other human or external contributor supplies any required current-head
  Copilot review under their own entitlement and cost. Lightning IT verifies
  valid evidence but never requests or funds that review, and personal tokens or
  provider keys never enter Actions.
- A same-repository PR authored exactly by
  `lightning-it-release-automation[bot]` uses only the protected MLX-90 §7.2
  Exact-Revision Codex check. It must never request Copilot or synthesize a
  Copilot success.
- A proven ancestry-only main-to-develop backmerge uses the deterministic
  evidence-bound exemption and performs zero AI calls. Unknown automation
  identities fail closed.
- The only neutral merge-gate result is `Current revision review`. Missing,
  stale, ambiguous, or unresolved review evidence blocks the merge.

<!-- LIT REP-60 review governance: end -->

<!-- LIT REP-60 evidence lifecycle: start -->

### REP-60 evidence lifecycle (mandatory)

- Every pull request into `develop` retains its exact-final-head native GitHub
  CI, required-check, and review history as the authoritative evidence for
  acceptance into `develop`.
- A pull request into `develop` MUST NOT create or retain an additional durable
  release-evidence package, duplicate WORM artifact, or second AI-review
  evidence outside that native GitHub history.
- Only the protected `develop` to `main` promotion creates exactly one durable,
  complete release-evidence package. It binds the full integrated promotion
  diff, base, head, merge base, integration tree, policy, reviewer result, and
  all release and audit checks.
- Agents, workflows, and repository-local rules MUST NOT duplicate that durable
  evidence per `develop` pull request or invoke local AI to create evidence.
  Repository-local rules may only make this lifecycle stricter.

<!-- LIT REP-60 evidence lifecycle: end -->

<!-- LIT Devtools container governance: start -->

## Devtools container execution boundary

- Every deterministic lint, format, type-check, test, build, packaging,
  policy, and validation workload runs in the digest-pinned Lightning IT
  Devtools image, locally and in CI. Host-language runtimes never provide
  acceptance evidence.
- The host boundary is limited to Git, the supported container engine, and the
  centrally managed Devtools, push-ready, and pre-commit dispatchers. A
  dispatcher may inspect Git state and start the pinned container, but it must
  not execute a repository validator through host Python, Node.js, Ansible,
  Ruff, a Python type checker, markdownlint, Renovate, or a comparable host
  runtime.
- If a required command or compatible version is absent, fail closed. Add and
  pin it in `container-ee-wunder-devtools-ubi9`, release that image normally,
  update the centrally managed digest, and rerun the gate. Host fallbacks,
  ad-hoc virtual environments, and unpinned helper images are forbidden.
- Repository-owned tests derive the exact full Devtools image reference from
  the centrally managed push-ready engine when checking the installed wrapper;
  they never hard-code an independent release tag that can drift during a
  normal image rollout.
- A target-specific regression test that asserts managed Devtools-wrapper
  arguments is the same atomic managed unit as the wrapper. Both synchronize
  through an exact source binding, and only an explicitly digest-allowlisted
  predecessor may be replaced; unknown target test content fails closed.
- Defaults stay read-only, offline, socket-free, capability-dropped, and
  non-privileged. A gate may opt into only its explicit tested minimum. Linked
  Git metadata remains read-only and container Git may trust only
  `/workspace`, never `*`. Executable temporary fixtures use the isolated
  container home while generic `/tmp` remains non-executable.
- The Devtools boundary never makes local Codex, Copilot, or other model calls
  and never receives personal AI credentials.

<!-- LIT Devtools container governance: end -->

<!-- LIT AI task governance: start -->

## AI model and token governance

Apply `LIT-GEN-GDR-GOV-30-Budget-Conscious-AI-Model-Selection` to every
substantive Codex or ChatGPT-assisted task. Before investigation, planning, tool
use, implementation, or delegation, record a compact task profile in the task
chat: work item, risk (`low`, `normal`, or `high`), smallest sufficient
model/reasoning choice, rationale, and a concrete escalation condition.

- Use the balanced, lowest reliable capability by default. Escalate to a
  premium/frontier model or higher reasoning only for a high-risk decision,
  complex architecture/debugging/dependencies, or a documented focused failure
  of the standard approach. Restrict that escalation to the difficult subtask.
- Never use Speed Mode. Do not replace verification with a more expensive model
  or sacrifice quality to reduce elapsed time.
- Retrieve only relevant issue, files, logs, and source records; avoid broad
  repository or chat-history loading, speculative analysis, and unbounded retry
  loops. Delegate only independent, bounded work that reduces total effort.
- For GitHub or Jira work, include the task profile in the issue/task record
  when AI assistance materially affects execution. Close with verification and
  remaining risks; preserve durable decisions in Confluence, Jira, or GitHub.

<!-- LIT AI task governance: end -->

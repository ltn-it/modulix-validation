# AAP Incus Nightly Matrix

# Internal Use Only

This workflow validates that the Lightning IT AAP automation stack can deploy
supported AAP/RHEL combinations on ephemeral Incus VMs.

## Repository Boundary

This repository owns the private validation harness:

- GitHub Actions workflow
- runner script
- validation inventory
- AAP/RHEL test matrix
- private artifact references

Reusable automation remains in `modulix-automation` and the collection
repositories. Human operator documentation remains in `modulix-operations-lit`.

## Workflow Files

Workflow:

```text
.github/workflows/aap-incus-nightly.yml
```

Runner script:

```text
.github/scripts/aap-incus-matrix-run.sh
```

Validation matrix:

```text
inventories/nightly/host_vars/ciwkr01.prd.dmz.corp.l-it.io/aap_ci_matrix.yml
```

The nightly schedule runs at `02:00 UTC` from the default branch. The workflow
can also be started manually with `workflow_dispatch`.

## Tested Matrix

The active matrix currently covers:

- AAP 2.7 on RHEL 9
- AAP 2.7 on RHEL 10

The AAP 2.6 entries remain documented in the matrix but are disabled because
the current `lit.supplementary.aap_deploy` role supports AAP 2.7 only.

## GitHub Secrets

Required:

- `RELEASE_AUTOMATION_APP_CLIENT_ID`: organization variable for the bounded
  cross-repository checkout App.
- `RELEASE_AUTOMATION_APP_PRIVATE_KEY`: organization secret for that App. The
  workflow mints a short-lived `contents:read` token limited to the three source
  repositories used during matrix preparation, and a separate token limited to
  the five source repositories used by each matrix job.
- `RH_AUTOMATION_HUB_TOKEN`: Red Hat offline token for certified collection
  installation.

Optional secrets:

- `RHSM_ORG_ID`: overrides the validation inventory RHSM org.
- `AAP_CI_ADMIN_PASSWORD`: fixed test admin password. If omitted, the workflow
  generates a per-run password.

Artifact sync secrets are optional. When all of them are present, the workflow
downloads/verifies the AAP bundles and RHEL Incus images before preflight. When
one or more are missing, the workflow expects the files and Incus aliases to
already exist on the runner.

- `AAP_26_BUNDLE_URL`
- `AAP_26_BUNDLE_SHA256`
- `AAP_27_BUNDLE_URL`
- `AAP_27_BUNDLE_SHA256`
- `RHEL_9_INCUS_METADATA_URL`
- `RHEL_9_INCUS_METADATA_SHA256`
- `RHEL_9_INCUS_QCOW2_URL`
- `RHEL_9_INCUS_QCOW2_SHA256`
- `RHEL_10_INCUS_METADATA_URL`
- `RHEL_10_INCUS_METADATA_SHA256`
- `RHEL_10_INCUS_QCOW2_URL`
- `RHEL_10_INCUS_QCOW2_SHA256`

## Runner Requirements

The runner must match these labels:

```text
self-hosted, linux, x64, incus, nested-virt, aap
```

On the runner, verify:

```bash
test -e /dev/kvm
incus info >/dev/null
incus image info local:rhel9-aap-ci >/dev/null
incus image info local:rhel10-aap-ci >/dev/null
test -f /srv/aap/bundles/aap-2.6-containerized-setup-bundle.tar.gz
test -f /srv/aap/bundles/aap-2.7-containerized-setup-bundle.tar.gz
```

If object-storage secrets are configured, these files and aliases are managed by
`modulix-automation/ansible/runbooks/40-platforms/incus/20-image-artifacts.yml`
from the validation inventory.

## Manual Run

Run a single matrix entry:

```bash
gh workflow run "AAP Incus Nightly Matrix" \
  --repo lightning-it/modulix-validation \
  -f matrix_filter=aap27-rhel10 \
  -f destroy_instances=true
```

Watch the run:

```bash
gh run list \
  --repo lightning-it/modulix-validation \
  --workflow "AAP Incus Nightly Matrix" \
  --limit 5
```

## Lifecycle

For each matrix entry the workflow:

1. Creates a unique Incus VM through `lit.ubuntu.incus_instance`.
2. Sizes the inherited root disk and configures MAC-matched cloud-init DHCP.
3. Generates a temporary SSH key and waits for authenticated SSH and cloud-init.
4. Registers the RHEL guest and runs `06-base-os-prepare.yml`.
5. Starts the native AAP installer asynchronously as `svc_aap`.
6. Polls the installer async job with short Ansible calls.
7. Reruns `modulix-automation/ansible/runbooks/50-applications/aap/10-deploy.yml`
   with `aap_deploy` tags for deployment verification without reinstalling.
8. Unregisters RHSM through Ansible teardown.
9. Destroys the Incus VM through `lit.ubuntu.incus_instance`.

If the Ansible teardown succeeds, the final Incus destroy step skips a second
RHSM unregister attempt. This avoids false CI failures when the Incus VM agent
is unavailable during late teardown.

## Operational Defaults

- `max-parallel: 1`
- VM sizing is matrix-owned.
- guest hostnames are kept short for AAP EDA queue safety.
- `hub_seed_collections` defaults to `false` for compatibility validation.
- the current IP-based smoke profile requires guest IPv4 and disables AAP DNS
  preflight until the private nightly DNS lifecycle is implemented.
- stale `aap-ci-*` instances fail the run early.
- failed runs collect AAP and Incus diagnostics before destroying the VM.

Increase parallelism only after the runner has enough CPU, memory, disk, and
Red Hat subscription capacity for parallel AAP installs.

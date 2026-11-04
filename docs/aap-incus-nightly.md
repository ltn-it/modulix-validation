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
inventories/nightly/host_vars/ciwkr01.prd.edge.pub.l-it.io/aap_ci_matrix.yml
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
downloads/verifies the active AAP 2.7 bundle and RHEL Incus images before preflight. When
one or more are missing, the workflow expects the files and Incus aliases to
already exist on the runner.

For a one-time manual bundle stage, set `AAP_STAGE_SOURCE_URL` to a short-lived
Red Hat download URL and `AAP_STAGE_S3_PUT_URL` to a short-lived, exact-key S3
PUT URL. Dispatch this workflow with `stage_aap27_bundle=true`. That job checks
the fixed AAP 2.7-11 SHA-256 before placing the bundle in the runner account's
`~/.cache/lit/aap` directory
and uploading it to private storage. It does not run the AAP matrix. Remove
the temporary secrets after the job. The scheduled workflow does not use them.

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

On the bare metal runner `ciwkr01.prd.edge.pub.l-it.io`, verify:

```bash
test -e /dev/kvm
incus info >/dev/null
incus image info local:rhel9-aap-ci >/dev/null
incus image info local:rhel10-aap-ci >/dev/null
test -f ~/.cache/lit/aap/aap-2.7-containerized-setup-bundle.tar.gz
```

If object-storage secrets are configured, these files and aliases are managed by
`modulix-automation/ansible/runbooks/40-platforms/incus/20-image-artifacts.yml`
from the validation inventory.

### Build and stage RHEL guest images

Red Hat Image Builder can produce x86_64 Virtualization guest qcow2 images for
RHEL 9 and 10. Choose **Register later** so the AAP test registers each new VM
at boot. The separate `Stage RHEL guest image for AAP Incus CI` manual workflow
uses the pinned `lit.rhel.cloud_image` and `lit.ubuntu.incus_image` roles to
verify and import one release at a time. Select `redhat_url` and set the
temporary `RHEL_STAGE_SOURCE_URL` secret for a new Image Builder download, or
select `runner_cache` to reuse a previously verified original qcow2 retained
on the runner. The workflow checks the exact size and SHA-256, enables SSH and
Incus cloud-init in the output, and replaces the `local:rhel9-aap-ci` or
`local:rhel10-aap-ci` image alias without privileged workflow access. The host
playbook must first install `guestfs-tools` and grant the runner account read
access to the installed kernels.

To archive the result, also set exact-key, short-lived S3 PUT URLs in
`RHEL_STAGE_QCOW2_PUT_URL` and `RHEL_STAGE_METADATA_PUT_URL`. The job uploads
both verified artifacts to the private bucket using Content-MD5. With both PUT
URLs absent, the import still succeeds and the objects remain pending archive.
Remove all temporary URL secrets after staging and record the SHA-256 values
shown in the job log. The builder's major-release selection does not prove a
specific minor release; inspect the running guest before claiming one.

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

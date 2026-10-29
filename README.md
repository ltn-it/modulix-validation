# modulix-validation

<!-- BEGIN LIT_SHARED_RELEASE_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.

See [RELEASE.md](./RELEASE.md) for:

- branch and release flow
- required quality checks
- test matrix
- release evidence
- artifact publishing
- supported repository-specific release behavior

Repository classification: **Shared-Assets-Managed Repository**.
Required test profiles: `pre-commit, validation-matrix, integration-incus, secret-safe-validation`.
Publishing targets: `none`.

## Supported and Tested Platforms

| Platform / Product |                  Status | Validation       |
| ------------------ | ----------------------: | ---------------- |
| ubuntu-latest      |               Supported | Molecule / Incus |
| rhel-9             |               Supported | Molecule / Incus |
| rhel-10            |               Supported | Molecule / Incus |
| aap-2.6            | Tested where applicable | Molecule / Incus |
| aap-2.7            | Tested where applicable | Molecule / Incus |
| incus              | Tested where applicable | Molecule / Incus |

<!-- END LIT_SHARED_RELEASE_MODEL -->

<!-- BEGIN LIT_QUALITY_BADGES -->

[![CI](https://github.com/lightning-it/modulix-validation/actions/workflows/repository-quality.yml/badge.svg?branch=develop)](https://github.com/lightning-it/modulix-validation/actions/workflows/repository-quality.yml)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/lightning-it/modulix-validation/badge)](https://scorecard.dev/viewer/?uri=github.com/lightning-it/modulix-validation)
[![OpenSSF Best Practices](https://www.bestpractices.dev/projects/13888/badge)](https://www.bestpractices.dev/projects/13888)

<!-- END LIT_QUALITY_BADGES -->

# Validation Harness

Public Lightning IT validation harnesses for ModuLix. Environment credentials,
private artifact locations, and generated evidence remain outside Git.

This repository owns real nightly and integration validation workflows. It is
separate from:

- `modulix-automation`: public reusable runbooks and orchestration code
- `ansible-collection-*`: role implementation and collection-level tests
- `modulix-operations-lit`: internal operator documentation and procedures

## Current Validation

- AAP Incus Nightly Matrix
- Reusable collection Heavy and Application Acceptance execution
- Protected, read-only PGE Confluence documentation conformance

The versioned, collection-neutral caller contract is documented in
[`docs/collection-molecule-profile.md`](docs/collection-molecule-profile.md).
The governed documentation audit is documented in
[`docs/pge-confluence-conformance.md`](docs/pge-confluence-conformance.md).

HashiCorp Vault, Wunderbox, Satellite, and other service suites are planned
extensions. They are not part of the current validated matrix yet.

The AAP workflow manages its ephemeral VMs through
`lit.ubuntu.incus_instance`, including run ownership metadata, MAC-matched
cloud-init networking, root-disk sizing, readiness checks, and unconditional
teardown. It currently uses IP-based transport and does not yet implement the
private Cloudflare DNS or strict TLS lifecycle described below. Do not report
the current AAP suite as DNS/TLS coverage.

## Extensible Nightly Validation

This repository is the private composition-test layer for ModuLix. Each service
suite deploys a supported product combination on real ephemeral infrastructure,
verifies the service, reruns the reusable automation for idempotence where
applicable, collects failure evidence, and removes all run-owned resources.

Collection repositories continue to own role implementation and lightweight
Molecule coverage. `modulix-automation` owns reusable orchestration. This
repository owns only the private matrices, workflow composition, runner
contracts, environment-specific inputs, and lifecycle finalizers needed for
real-infrastructure validation.

Use the following convention when adding a service suite:

```text
.github/workflows/<service>-incus-nightly.yml
.github/scripts/<service>-incus-matrix-run.sh
inventories/nightly/host_vars/<runner>/<service>_ci_matrix.yml
docs/<service>-incus-nightly.md
```

The service-specific script is optional and must remain a thin adapter. Shared
Incus, DNS, secret, and product lifecycle behavior belongs in reusable roles and
runbooks rather than duplicated suite scripts.

A complete suite covers this lifecycle:

1. Validate runner capacity, artifacts, routes, DNS, and secret availability.
2. Create run-unique Incus instances and wait for address and SSH readiness.
3. Create private forward and reverse DNS records and verify resolution.
4. Deploy the service through reusable ModuLix runbooks and collection roles.
5. Verify functional health, TLS, and idempotent reruns where supported.
6. Collect product, guest, and Incus diagnostics after a failure.
7. Perform product-specific cleanup while DNS is still available.
8. Delete DNS records, release addresses, and destroy the Incus resources.
9. Reconcile expired resources with a scheduled garbage collector.

Run-owned resources must carry enough metadata to correlate them with the
workflow, matrix entry, run ID, attempt, service, FQDN, and expiry. Retained
failure environments must retain their matching DNS records and address
allocation for the same bounded period.

## Private Nightly DNS

Nightly guests use the private namespace:

```text
nightly.lab.l-it.io
```

`nightly` is a validation namespace inside the existing `lab.l-it.io` boundary;
it is not a new peer domain or a fifth deployment stage. The stable Incus runner
and control plane keep their real `corp.l-it.io` names.

Run-specific examples:

```text
a27r10-r123456.nightly.lab.l-it.io
vault01-r123456.nightly.lab.l-it.io
wunderbox-r123456.nightly.lab.l-it.io
sat01-r123456.nightly.lab.l-it.io
```

The target DNS service is Cloudflare Internal DNS through Cloudflare Gateway.
Cloudflare feature entitlement and current availability must be confirmed when
the platform is bootstrapped. The forward zone, DNS view, resolver policy, and
the reverse zone for each Incus test subnet are persistent infrastructure.
Workflows create only run-specific A and PTR records, plus AAAA records when
available, through the Cloudflare API.

DNS records must remain private and unproxied. Public Cloudflare DNS and
`pub.l-it.io` are not used for private Incus guest addresses. Cloudflare DNS
availability does not provide network reachability; consumers outside a local
NAT bridge still need a routed LAB network, WARP, or an approved tunnel.

Every workflow must:

- use a least-privilege runtime token limited to DNS reads and writes for the
  exact nightly forward and reverse zones
- store tokens in a protected GitHub Environment Secret or an external Vault,
  never in Git or generated plaintext files
- attach owner, service, run, instance, and expiry metadata to records
- verify that the runner and guests can use the selected Cloudflare Gateway
  resolver path before creating service resources
- verify forward and reverse resolution from the runner and guest before deploy
- use the node FQDN consistently for guest and inventory identity, and use each
  run-scoped endpoint FQDN consistently in application URLs and certificate SANs
- delete records by verified record ID during unconditional cleanup
- leave a scheduled garbage collector to remove expired records after runner
  loss or forced termination

A short TTL reduces stale caching but does not remove a record. Product teardown
must therefore finish before DNS deletion, and DNS deletion must finish before
the VM address is released. If Cloudflare Internal DNS is unavailable, suites
must use an explicitly approved private authoritative resolver rather than
falling back to public RFC1918 records or `/etc/hosts`.

This is the target contract for new and migrated suites. The current AAP
workflow must not be reported as DNS/TLS coverage until that lifecycle has been
implemented and validated end to end.

Cloudflare Internal DNS does not provide application certificates. Suites must
use an approved internal test CA or approved ACME DNS-01 flow, install the trust
chain on the required clients, and validate certificate chain, hostname, and
expiry. Secret material and private keys must never be uploaded with diagnostic
artifacts.

See the Cloudflare documentation for
[Internal DNS](https://developers.cloudflare.com/dns/internal-dns/),
[Internal DNS connectivity](https://developers.cloudflare.com/dns/internal-dns/connectivity/),
and the [DNS Records API](https://developers.cloudflare.com/api/resources/dns/subresources/records/).

## Future Service Suites

The shared lifecycle is intentionally product-neutral. Expected extensions
include:

- **HashiCorp Vault:** deploy with run-scoped FQDNs, strict TLS verification,
  isolated storage and secret paths, and cleanup of credentials and PKI leases.
- **Wunderbox:** validate the composed platform, its individual services, and
  their cross-service dependencies with run-isolated state and DNS names.
- **Satellite:** require forward and reverse DNS, manage subscription and
  content state explicitly, and unregister test clients before teardown.
- **Additional services:** add a separate, reviewable matrix and documentation
  while reusing the same Incus, DNS, secret, diagnostic, and cleanup contracts.

## Layout

```text
.github/workflows/                         GitHub Actions workflows
.github/scripts/                           workflow runner scripts
inventories/nightly/                       validation inventory and matrices
docs/                                      validation documentation
```

## Current AAP Workflow Secrets

Set these secrets on `lightning-it/modulix-validation` for the current AAP
suite:

- `LIT_REPOSITORY_READ_TOKEN`: read-only token for cross-repository checkouts.
- `RH_AUTOMATION_HUB_TOKEN`: Red Hat offline token for certified collection
  installation.

Optional:

- `RHSM_ORG_ID`: overrides the validation inventory RHSM org.
- `AAP_CI_ADMIN_PASSWORD`: fixed test admin password.
- `AAP_26_BUNDLE_URL` / `AAP_26_BUNDLE_SHA256`: AAP 2.6 bundle artifact.
- `AAP_27_BUNDLE_URL` / `AAP_27_BUNDLE_SHA256`: AAP 2.7 bundle artifact.
- `RHEL_9_INCUS_METADATA_URL` / `RHEL_9_INCUS_METADATA_SHA256`: RHEL 9 Incus metadata artifact.
- `RHEL_9_INCUS_QCOW2_URL` / `RHEL_9_INCUS_QCOW2_SHA256`: RHEL 9 Incus qcow2 artifact.
- `RHEL_10_INCUS_METADATA_URL` / `RHEL_10_INCUS_METADATA_SHA256`: RHEL 10 Incus metadata artifact.
- `RHEL_10_INCUS_QCOW2_URL` / `RHEL_10_INCUS_QCOW2_SHA256`: RHEL 10 Incus qcow2 artifact.

The checked-in AAP matrix still contains legacy RHSM organization and
activation-key values. They require migration to approved secret references and
must not be copied into future service matrices.

## Target DNS Provider Secret

Future DNS-enabled service suites also require a dedicated Cloudflare runtime
token with DNS read/write access restricted to the private nightly forward and
reverse zones. Zone/view administration must use a separate bootstrap identity;
do not grant those permissions to nightly test jobs.

Store the runtime credential as the protected GitHub Environment Secret
`CLOUDFLARE_NIGHTLY_DNS_TOKEN`. Map it to `CLOUDFLARE_TOKEN` only for the DNS
provider task and do not expose it to unrelated workflow steps.

## License

This repository is publicly visible but remains proprietary. Its
repository-specific license grants no redistribution rights.

## Security

See [SECURITY.md](./SECURITY.md) for supported versions and vulnerability reporting.

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution and review expectations.

<!-- BEGIN LIT_RELEASE_QUALITY_MODEL -->

## Release and Quality Model

This repository follows the Lightning IT shared release and quality model.
The README shows the current supported and tested matrix.
Exact per-version validation proof is stored with each GitHub Release as `release-evidence.md` and `release-evidence.json`.
Releases are created from the protected `main` branch after a reviewed `develop -> main` release promotion.
Repository checks validate the managed structure, documentation, and release model for this repository type.

See:

- [RELEASE.md](./RELEASE.md)
- [TESTING.md](./TESTING.md)
- [GitHub Releases](../../releases)

Repository classification: **Private Infrastructure Repository**.
Required test profiles: `pre-commit, validation-matrix, integration-incus, secret-safe-validation`.
Publishing targets: `none`.

Private repository note: generated docs must stay generic and secret-safe.
<!-- END LIT_RELEASE_QUALITY_MODEL -->

<!-- BEGIN LIT_COMPATIBILITY_MATRIX -->

## Compatibility Matrix

| Platform / Product | Status | Validation |
|---|---:|---|
| ubuntu-latest | Supported | Molecule / Incus |
| rhel-9 | Supported | Molecule / Incus |
| rhel-10 | Supported | Molecule / Incus |
| aap-2.6 | Tested where applicable | Molecule / Incus |
| aap-2.7 | Tested where applicable | Molecule / Incus |
| incus | Tested where applicable | Molecule / Incus |

Validation proof for each released version is stored in the corresponding GitHub Release evidence.

For asynchronous Heavy and Application Acceptance evidence, see
[Prevalidated Candidate Evidence](./docs/prevalidated-candidate-evidence.md).

<!-- END LIT_COMPATIBILITY_MATRIX -->

## Release Evidence

This repository does not publish release artifacts by default; release evidence is recorded when artifact releases are enabled.
The evidence records:

- tested matrix combinations
- GitHub Actions run links
- artifact references
- publish status
- security scan status

See [GitHub Releases](../../releases), [RELEASE.md](./RELEASE.md), and [TESTING.md](./TESTING.md) for the release process and validation model.

## Collection release transition

The manual `collection-release-transition.yml` receiver accepts the six fixed
`ansible-collection-*` repositories under `ltn-it` and their historical
`lightning-it` names. It preserves the supplied source name and requires its
live GitHub repository ID to match the known Collection object before recording
transition evidence. The destination must remain repository `1269461997`.

The receiver preserves its existing runner and records an explicit transition no-op. It
does not run Heavy/Application Acceptance or publish to Galaxy; its evidence
keeps validation and release eligibility false. A dispatch recovery for an
already published release keeps the original source commit, version, artifact
filename and SHA-256.

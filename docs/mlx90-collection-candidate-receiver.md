# MLX-90 collection candidate receiver

LI-359 owns the paired receiver for Supplementary's v2 validation request.
The workflow `mlx90-collection-candidate-validation.yml` implements the paired
request boundary, authenticated exact-byte Nexus readback, real supported
Heavy/Application matrices and keyless v2 receipt signing. Its controller
adapters are `scripts/collection_candidate_request.py` and
`scripts/collection_candidate_receiver.py`. Code delivery and independent
checks proceed under the owner's workflow-first decision. Runtime activation,
Nexus/Galaxy cutover and operational acceptance remain later work under
LI-371/LI-118; code presence is not an operational or release-eligible result.

The request adapter validates canonical compact JSON and its SHA-256 before
using request fields. It rejects duplicate keys, unexpected fields, boolean
integer substitutions, unsafe names, foreign identities, human action counts,
and a Nexus endpoint that differs from protected controller configuration.
The independent producer-run check binds both App actors, exact source SHA,
workflow, run and attempt; the producer must still be in progress while it
waits for the receiver.

## Confirmed infrastructure and remaining configuration

On 2026-10-17, the existing Protected Incus runner group allowed this
repository and contained five online Incus runners. The repository-level
runner inventory alone omits those organization runners.

The existing `mlx90-final-acceptance` environment already permits only `main`
and has no required human reviewers. Reusing this environment needs no change
to its protection rules. The separate collection runtime environments have
human reviewers and must retain them.

On 2026-10-17, the owner confirmed directly that Nexus has not yet been
provisioned. There is consequently no existing service endpoint or reader
configuration to discover. Foundation or host provisioning is outside LI-359.
The upstream service must deliver the Nexus target before runtime acceptance;
it does not block fail-closed workflow code delivery.

Repository, organization, and all seven existing environment metadata lists
contained no Nexus endpoint or reader credential configuration. No existing
workflow references a Nexus reader. A runner-local credential or a separately
approved external secret source has not been established by that inspection.
An App token is not a Nexus reader credential.

This is not evidence that the worker needs broader GitHub rights, nor proof
that a service is unreachable. There is no confirmed endpoint to probe. The
authoritative deployment record
[Nexus PRD Target](https://lit.atlassian.net/wiki/spaces/LIT/pages/2897838457)
(version 11) describes a planned target, without an installed or accepted
service, FQDN, TLS, repository, or credential baseline. The
[service project](https://lit.atlassian.net/wiki/spaces/LIT/pages/2897969321)
(version 14) likewise keeps applicability, design, and installation open.
The accepted
[MLX-70 ADR](https://lit.atlassian.net/wiki/spaces/LIT/pages/2893119515)
(version 7) explicitly keeps Nexus cutover and technical acceptance open.
The smallest missing prerequisite is now the actual provisioned service,
followed by its as-built repository reference and approved reader delivery
mechanism. There is no further secret or endpoint search in this increment.
Deploying a new service is outside this paired receiver increment.

The concrete configuration decision for the existing environment is:

| Type | Proposed reference | Exact boundary |
| --- | --- | --- |
| Variable | `NEXUS_GALAXY_READ_REPOSITORY` | One existing hosted ansiblegalaxy repository |
| Variable | `NEXUS_GALAXY_READ_REPOSITORY_URL` | Its credential-free HTTPS repository URL |
| Secret | `NEXUS_GALAXY_READ_USERNAME` | A dedicated reader for that repository |
| Secret | `NEXUS_GALAXY_READ_PASSWORD` | Its password or user-token secret |

These are proposed references, not configured or granted credentials. An
existing approved external-secret delivery path can replace these proposed
GitHub Secret references without changing the exact repository-read scope.
No secret value should be requested or copied into the chat. The
reader requires only browse/read on the exact existing repository. It must
have no upload, delete, redeploy, or administration privilege. Provisioning or
delegating this access requires the authorized credential custodian; no
publisher credential, anonymous fallback, or new App permission is allowed.
No secret value belongs in this document, Jira, or generated evidence.

## Native code path and later runtime acceptance

The workflow exposes exactly `request_id` and `request_json`, binds
the protected controller SHA and App identity, and validates the fresh producer
run before reading a protected credential. Empty configuration fails before
credential, download or publication effects. Authenticated Nexus readback
rejects redirects and proves exact size and digest without rebuilding or
changing the candidate. Existing read-only Release App scope retrieves the
exact producer-run/attempt stage artifact and tested runtime dependency bundle;
checksums bind staged and independently downloaded candidate bytes. No new App
permission or personal token is needed.

Matrices come from the exact protected source registry. The immutable
validation-owned quality action executes real scenarios with owned cleanup,
JUnit/Allure and strict evidence gates. Signing requires every prior native job
to have completed successfully in the same run/attempt, including actual Heavy
and Application Acceptance cells. Missing, failed, skipped, duplicate or
foreign-attempt results cannot authorize a receipt. There is no no-op fallback.
Only the protected main workflow receives the signing OIDC permission.

Local validation stays deterministic in read-only pinned Devtools. Protected
runtime readback explicitly enables network and workspace output; receipt
construction enables workspace output only. A trap removes the temporary
reader file, which is excluded from every artifact. The final receipt artifact
contains exactly the canonical JSON and its Sigstore bundle.

Supplementary remains responsible for verifying that receipt and publishing
the same candidate bytes to Galaxy. Its existing #1167/#1168 integration is
prepared separately against current protected develop; it has no operational
receiver acceptance merely because local integration tests pass.

The transition workflow and existing release functions remain until the paired
runtime path is accepted. Code delivery requires current-head native review and
normal protected integration. Later LI-371/LI-118 runtime evidence must prove
real infrastructure/configuration, real profiles and the exact signed receipt
before Galaxy cutover. LI-360 retains the separately recorded native workflow
and release acceptance boundary. Local tests and code delivery are not runtime
acceptance.

## Protected Devtools execution contract

The quality action delegates container creation exclusively to the centrally
managed `scripts/wunder-devtools-ee.sh`. Its `protected-incus-v1` extension and
matching boundary tests must be delivered through the approved Source adoption
path before this action can execute. The local action adapter does not invoke a
container engine or provide a fallback. The REP-120 distribution hold and the
missing Incus client in the currently inspected released image remain real
prerequisites; this code does not claim that either has been resolved.

The dispatcher and its managed companion come from `scripts` at the native
SHA-pinned ModuLix external action archive root. They do not come from
`GITHUB_WORKSPACE`, which is the Supplementary source checkout at `source-sha`.
Both the initial preflight and cell-run steps forward the same complete action
input set plus fixed native `github.action_repository`, `github.action_ref`,
`github.action_path`, and controller `github.sha` contexts. The preflight runs
before candidate download. Native SHA-pinned transport and the protected
runner form the platform trust boundary; local environment/path checks do not
claim independent cryptographic provenance. Final native review must verify
the actual external-action pins bind the reviewed archive.

The admitted context uses one container for the complete matrix cell. Source
is read-only at `/workspace`, the exact downloaded candidate and tested runtime
bundle are read-only at `/candidate`, and the immutable action is read-only at
`/controller`. Only the run-owned cell directory is writable at `/quality`.
Its temporary state is `/quality/tmp`; artifacts, Molecule state, extracted
collections, logs and final packages never use writable source-tree paths.
Root, source, controller, candidate and the private Incus context stay
read-only. The managed launcher binds the actual image digest and effective
UID/GID; host-native interpreters and dependency installations are absent.

The launcher supplies only the declared action inputs, bound GitHub run
identities, necessary runner metadata and private runtime paths. Neither a
host home nor a Docker socket nor GitHub command-file directories are mounted.
The complete cell keeps generated masked secrets and private command files in
the isolated `/tmp/wunder` home tmpfs. After owned capture and destruction, raw
cell state is removed; only the redacted package and nonsecret result survive.
Its private environment file cannot replace PATH, HOME, Incus configuration,
image identity, command-file paths or launcher-owned UID bindings. The central
dispatcher accepts only the fixed result schema from `/quality/control/result.json`,
maps `/quality/package` back to that cell's host directory and emits the two
artifact outputs. Upload success is independently mandatory after cell success.

Later LTN-371 runtime activation must supply a private run-bound HTTPS Incus
context, mounted read-only at `/incus`, without granting general host access.
The context contains exactly `binding.json`, `config.yml`, `client.crt`,
`client.key`, and `servercerts/quality.crt`. Files are ordinary controller-owned
0600 files; directories are 0700. The binding schema is 1 and contains exactly
`repository`, `run_id`, `run_attempt`, `server`, `project`, and `expires_at` in
addition to `schema`. Its identities match the actual current run; its expiry
must be in the future and at most 90 minutes away. The Incus configuration
contains the authenticated HTTPS remote `quality`, selects it by default
and binds the same server and project, with pre-provisioned server trust.
Its only other remote is `images`, with exactly
`addr: https://images.linuxcontainers.org`, `protocol: simplestreams`, and
`public: true`, so the registry's `images:ubuntu/24.04` reference resolves
without inheriting a global client configuration. Foreign image servers and
additional remote keys fail closed in both admission and execution.
The VM phase queries `quality:/1.0` and requires the server's `qemu` driver;
the Devtools client does not receive a local KVM device or privileged mode.
Its exact remote keys are `addr`, `auth_type: tls`, `project`, `protocol: incus`
and `public: false`, following the
[pinned Incus schema](https://github.com/lxc/incus/blob/01f81e5e607bbb5818410318e4b3496ad1820824/shared/cliconfig/remote.go).
The CLI-style `auth-type` spelling and unknown keys fail closed. The central
offline container preflight parses the private binding/configuration and
loads the client key/certificate and server trust before any target contact.
Docker and rootful Podman preserve the nonroot runner UID/GID; rootless Podman
is unsupported by this context version and stops before any mount.
Missing, foreign, expired, public, linked or permissive context fails before
candidate installation or infrastructure effects. This is a proposed delivery
contract for the credential custodian, not configured access or a request for
credentials in this code increment.

All initialization, candidate integrity checks, Molecule phases, dependency
inventories, evidence validators and packaging execute inside that container.
The test phase retains its 1800-second limit, followed by unconditional
600-second evidence capture and 600-second owned destruction, with the existing
30-second kill grace. A failed or timed-out phase cannot become a successful
receipt input. Diagnostics precede destruction; lifecycle and evidence failures
remain independently fatal. Runner-loss recovery still requires the established
ownership-aware stale-resource collector; a container lifetime is not proof of
cleanup after runner loss.

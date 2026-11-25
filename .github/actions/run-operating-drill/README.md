# Closed operating cases

This fixture tests operating behavior, not Keycloak or collection role coverage.
Only the initial protected Source Main transition and its three independently
prepared native jobs enter the Root `operating` kind. Business matrices,
ordinary resource limits and quality receipts remain separate.

Root seals `QUALITY_OPERATING_CASE` and the exact `QUALITY_OPERATING_SPEC` into
the engine policy. The spec fixes the actual cached Ubuntu image fingerprint,
Root-derived instance name, one CPU, 2 GiB memory, 5 GiB root, 500 MiB state,
6 GiB VM reservation, 4 GiB image reservation and 10 GiB project reservation.
Root copies and reads back that pinned image into the owned project before
granting execution. No public alias, inherited image pool or caller sizing is
accepted. If real reservations do not fit, admission holds; it does not reduce
ordinary quotas or shorten failed-cell custody.

The immutable controller invokes only the verified Source shared Incus create
playbook, then reads the actual owned VM through its scoped TLS context. It
waits for Root's one-time readiness acknowledgment before the failure case
actually exits 23. The other cases leave the VM running for the broker/client
or real authorization expiry to stop. The controller never destroys a VM.
Its `operating-result.json` is diagnostic input: Root independently joins the
actual engine exit, original native identity, instance UUID, cancellation or
deadline, fence withdrawal and stopped state. Controller observations grant no
authority, retention claim, or quality PASS.

The native action calls the installed trusted `run-operating --case` client.
After Root's READY event, the client requests cancellation for `broker-cancel`
or stops sending heartbeats for `expiry-controller-loss`. Root's supervisor
remains alive. The execution check requires actual failure, cancellation or
expiry and proof that Root withdrew access and stopped the VM.

A distinct `Operating result / <case>` native job calls read-only
`observe-operating --case` after execution ends. It verifies the original
native outcome and Root's safety evidence. Root can clean up as soon as it
verifies the stopped VM, withdrawn access and preserved evidence for the
original job. The observer reads the bound proof even after cleanup.

Operating acceptance includes independent verification of resource absence,
local Root-mail delivery and unchanged foreign resources. Ambiguous safety
or ownership blocks cleanup.

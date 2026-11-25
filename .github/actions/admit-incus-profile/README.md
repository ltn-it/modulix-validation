# Protected Incus admission compiler

This immutable action owns hosted caller admission and the scheduling matrix
schema. It runs only its own `admission.py` in the digest-pinned Devtools image,
read-only, offline, non-root, without candidate checkout, credentials or a
service socket. Validation completes before any output is emitted.

The consumer must pin this action's real commit and use its canonical
`matrix-json` output for `strategy.matrix`; the raw input is never scheduled.
All outer/cell keys and every scalar, boolean, role, image selector and runner
list are checked. JSON duplicates/nonfinite values, unknown axes/fields and
duplicate scenario/target cells are refused. Input and canonical output are
bounded at 64 KiB, and a matrix has at most 256 cells, matching the
[GitHub matrix ceiling](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstrategymatrix).

The closed cell fields, identifier/role/image patterns and two runner label sets
follow Supplementary's `build_matrix` and registry schema. Only supported,
release-required rows enter the protected Main route. Candidate rows need a
separate contract. Resource limits stay at the commissioned 4 CPU/12 GiB/24 GiB.

Both registry-supported `container` and `vm` types are typed compatibility
inputs. Compatibility with an older protected Main container row does not prove
G06 VM acceptance: G06's pending physical profile rows and both Root-prepared
cells must remain VMs. The installed runtime action and its independent native
identity, ownership, expiry and lifecycle checks are unchanged.

The hosted check accepts two complete GitHub caller identities. The existing
MLX90 Main dispatch uses the release App and an `mlx90-candidate-<request-id>`
artifact. The direct Supplementary route uses a protected Main push through
`collection-ci.yml` in repository `1103407173`, attempt one, with `litroc`
(`76040632`) or `litdeg` (`247824904`) as the User actor and the same triggering
login. Its source SHA equals the GitHub caller SHA, and its artifact is exactly
`collection-candidate-<source-sha>`. Both routes use the same matrix compiler
and fixed limits. Mixed caller fields and a caller-supplied mode grant no route.

The additional context comes from GitHub expressions in the immutable action,
not from action inputs. Hosted compilation binds the workflow path. The
installed Root runtime independently verifies the actual run and workflow ID
(`214182490` for Supplementary), both native actor identities, OIDC claims,
Runner01 identity, and the private policy before admitting a cell.

The compiler also derives `worker-group` from that fully validated caller:
the original Validation domain retains `lit-pis-prd-isolated`, while direct
Supplementary uses only `lit-pis-prd-supplementary-isolated`. A matrix label,
environment variable or workflow input cannot choose a different group.

The additional `operating` profile is not a business matrix. It requires the
complete direct Source identity, an empty include matrix, and exactly one of
`failure`, `broker-cancel`, or `expiry-controller-loss`. The Main push `before`
must be exactly the historical `90e7216b5d085ca4ac6238e44dcdbaa51e847d5f`,
its recorded follow-up `14e3abd5d1fa0cfad14d52ec83483b761de207f0`, the
client-protocol correction `f27c1d4edff75377f285275cec9bfec6bc3081f6`, or the
recorded failed successors `3d84e26d90cc778fb8c4f462ce481584da57fb5a` and
`f138a227d9eee41ea698b1a6f3b9a05f7ae3e18d`, plus the failed-with-effects
predecessors `8926e7f535f158d4af89e4ac68149ff0b8ab740d` and
`086d039c8c58bc91edfeacadf508c207a03a58b5`, and the failed native-authentication
predecessor `cfd2e8ca4cbcf58a1a22cf37f2a8336bba19cb85` and the failed catalogue-reader
predecessor `8345d447e65609e66eac616afbeb3b5d4bc362be`, and the separately retired
partial-preparation predecessor `86f3cb46e5856c4066cac14e73f46c3cefb8453e`.
The original push at `5604f19544f97b572272496fd61f5c4949d45fba` ended before lease allocation and is also an eligible predecessor.
The failed preparation at `e403e0fffa9318be82718b29e854ab7a3a6da98c`
is eligible after its retained resources were verified absent. Root must
independently verify the closed predecessor and the new run binding.
The Main push at `69d2ccf034dfe5c64c0fda8fc037569fc9b96ff6` failed at the
Podman startup boundary. Root must verify the separate retirement of its
original resources and bind a new push before it can allocate any lease.
The Main push at `e42b0cdd65536e3749f6c405ec23955e5aaa419b` stopped in the
host namespace census after the source intake was sealed. The run created no
configuration, lease or VM. Root must preserve the sealed intake, verify the
terminal run and bind the new protected push before it can allocate a lease.
The Main push at `8edd19c61a8faffe10d6c570cc3ad8338750f475` reached the
authorization deadline after sealing both source intake and configuration.
It created no lease or VM. Root verifies both sealed entries, the empty
predecessor bank, and the exact new run before allowing any lease.
The Main push at `5759a628d9fadb258036390483cb158c8ea36570` failed at Podman startup before
creating a VM. Root must verify expiry and separate retirement of the retained
lease resources, preserve the original outcome, and bind the next protected push.
This closed set is not a generic retry or future-Main allowance. Original
failures remain failures; no rerun, dispatch or attempt reset is admitted.
Ordinary profiles reject a nonempty operating case, and the original receiver
cannot enter this domain. Root independently verifies the genuine native job,
commit parent and, for the follow-up, its separately approved exact continuation
binding. The hosted caller condition alone grants no operating lease. Other
later ordinary Main deliveries do not repeat these operating cases.

The earlier authentication predecessor's original run
[`43947870949`, attempt 1](https://github.com/ltn-it/ansible-collection-supplementary/actions/runs/43947870949)
failed during bootstrap authentication before a lease or VM was created. Its
failure remains part of the native history. The additional exact parent permits
scheduling a genuine subsequent Main push; attempt 2, reruns, arbitrary parents,
and other caller identities remain refused. Root must separately authenticate
the original terminal graph and preserve its existing intake/catalogue state.

The catalogue-reader predecessor's original run
[`44153750769`, attempt 1](https://github.com/ltn-it/ansible-collection-supplementary/actions/runs/44153750769)
failed before creating a lease. Its completed configuration and intake remain
preserved historical inputs, and its failure is not a passed Heavy test. The
additional exact parent permits only a genuinely subsequent Main push; Root
must independently authenticate the complete history and the new published
caller/callee pair. No old attempt, stage or execution is retried or adopted.

The partial-preparation predecessor's original run
[`44427583641`, attempt 1](https://github.com/ltn-it/ansible-collection-supplementary/actions/runs/44427583641)
failed before an instance or engine start. Its preparation effects and unknown
fence outcome remain recorded. Separate Root retirement removed the owned
resources after the full retention window; the original failure stays failed.
Scheduling this exact subsequent Main transition does not repeat, clear or
reclassify the old operation. Root must independently join the native terminal
history, immutable original bootstrap, retirement receipts and resource absence
with the genuinely published new caller/callee pair.

Operating resources are prepared by Root, outside the caller's business limits:
one CPU, 2 GiB RAM, 5 GiB root and 500 MiB VM state within a 6 GiB VM budget.
The exact cached 4 GiB Ubuntu image is journaled and copied into the owned
project before execution; the complete project reserves 10 GiB. Actual physical
and retained reservations still gate every case. The ordinary two business
profiles remain at 4 CPU, 12 GiB RAM and 24 GiB disk.

## Admission change record

2026-11-13: retain the two additional exact failed Main predecessors in hosted
admission and bind the workflow to the immutable action containing this list.
The action grants scheduling eligibility only; actual Root admission, original
attempts, retained failure histories, resource limits and deadlines are unchanged.

2026-11-14: admit the exact functional successor after the original 8926 Main
run failed with six verified preparation effects. This is scheduling eligibility
for the same two business profiles and three operating cases. It does not
classify the old run as no-work, clear its effects, reset attempts or reviews,
or replace the independent Root proof of cleanup, custody and retired history.

2026-11-16: retain the exact 086d failed-after-context-publication predecessor
for a separately published functional successor. This changes hosted scheduling
only; it does not retry the original run, classify its effects as no-work, or
replace Root-native retirement, custody, identity and per-job authorization.

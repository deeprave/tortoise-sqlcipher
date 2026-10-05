# Design

## Context

See proposal.md. The current pull-request workflow runs the full test suite on
Ubuntu for CPython 3.11 through 3.14. The package uses `sqlcipher3>=0.6.3`,
whose published wheels include supported CPython Windows targets, but the
package has not declared Windows support. The encryption test intentionally
inspects a live WAL sidecar before Tortoise closes its connection.

## Goals / Non-Goals

**Goals:**

- Obtain reproducible Windows evidence for installation, ORM integration, and
  live-WAL inspection.
- Decide whether Windows belongs in the package's supported-platform contract.
- Preserve the encrypted-storage test's requirement to observe a live sidecar.

**Non-Goals:**

- Declare Windows support before the probe passes and its limitations are
  reviewed.
- Expand the normal pull-request matrix to every Windows/Python combination
  during investigation.
- Change the backend's runtime behavior solely to accommodate a test runner.

## Decisions

- Use a focused GitHub-hosted `windows-latest` probe on CPython 3.13, the
  current development interpreter, before deciding on an ongoing Windows
  matrix. This supplies a concrete signal without multiplying normal PR cost.
- Run the complete package test suite in the probe, including the live-WAL
  encrypted-storage assertion. A passing installation alone is insufficient.
- If live-WAL reads fail because of Windows sharing semantics, investigate a
  synchronization approach that keeps the WAL live. Do not simply close the
  database before inspection, because that would stop testing the intended
  boundary.
- Treat a passing probe as evidence for that runner, interpreter, and wheel
  combination only. A separate support decision determines whether to add a
  maintained Windows matrix, platform documentation, and a backend-spec delta.

## Risks / Trade-offs

- Windows file sharing blocks raw reads of an open WAL → capture the exact
  exception and evaluate a synchronization design that retains live-WAL
  evidence.
- `sqlcipher3` wheel availability differs by Python architecture or release →
  record the resolved wheel and interpreter before generalizing results.
- A Windows probe increases CI time → keep the exploratory job focused on one
  CPython version until support is explicitly approved.

## Migration Plan

No runtime or data migration applies. Remove any exploratory-only workflow if
Windows is declined; otherwise create a follow-up support change that promotes
the verified probe to the chosen maintained CI matrix and updates the platform
contract.

## Open Questions

- Does the live-WAL assertion pass on GitHub-hosted Windows with CPython 3.13
  and the resolved `sqlcipher3` wheel?
- If it fails, can a synchronization method retain an open WAL while allowing
  byte inspection without weakening the encryption assertion?

# Proposal

## Why

The package has no explicit Windows support decision while its SQLCipher
dependency publishes Windows wheels. The encrypted-storage test reads a live
WAL sidecar, whose file-sharing behavior may differ on Windows from the
currently verified macOS environment.

## What Changes

- Establish whether supported CPython and `sqlcipher3` combinations install
  and pass the package test suite on GitHub-hosted Windows runners.
- Determine whether Windows permits the live-WAL inspection needed for the
  encrypted-storage assertion, and identify a behavior-preserving test design
  if it does not.
- Document the evidence and make an explicit recommendation to support or
  exclude Windows; do not add a Windows compatibility claim until that decision
  is approved.

## Capabilities

### New Capabilities

- None. This is a decision-focused compatibility investigation, not a new
  runtime contract.

### Modified Capabilities

- None. A later support decision may modify `sqlcipher-tortoise-backend`.

## Impact

Investigation may use GitHub Actions Windows runners and temporary test
instrumentation. It does not change the package API, supported-platform
contract, production dependencies, or current Ubuntu CI matrix.

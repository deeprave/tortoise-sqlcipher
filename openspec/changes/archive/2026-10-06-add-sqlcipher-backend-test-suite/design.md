# Design

## Context

See proposal.md and the `sqlcipher-backend-tests` delta. The source exploration uses
a disposable Tortoise model and migration package so it can exercise the
backend without coupling tests to an application model.

## Goals / Non-Goals

**Goals:**
- Port the established behaviors into package-owned integration tests.
- Keep encryption assertions about observable files and query behavior rather
  than SQLCipher implementation details.

**Non-Goals:**
- Treat a unit test or generic GitHub Actions runner as platform certification.
- Test a consuming application's secret storage or recovery workflow.

## Decisions

- Use disposable models and a dedicated migration fixture under the test
  package. This preserves native migration coverage without shipping models.
- Build Tortoise configuration in the test suite with the package engine and a
  deterministic 32-byte test key. Test keys remain fixtures only and do not
  model production key handling.
- Use a parameterized field-compatibility matrix covering every built-in
  Tortoise data field and standard relation variant that the SQLite backend
  supports. Include `TimeField` and `TimeDeltaField` explicitly because their
  Python values can cross the driver binding boundary without prior string
  conversion. Record `TimeField` as an expected upstream SQLite limitation;
  other failures identify backend compatibility gaps and do not silently
  narrow the package's field contract.
- Inspect the database plus discovered sidecar files for schema/record
  plaintext, then attempt ordinary SQLite access. Both checks are necessary:
  byte inspection alone does not prove ordinary SQLite rejection.
- Exercise rekey and backup through SQLCipher's native DB-API in tests,
  not as public package helpers.

## Risks / Trade-offs

- WAL creation timing differs by platform → discover sidecars after model
  writes and fail if the expected live WAL evidence is absent.
- Global Tortoise state leaks between async tests → always close connections in
  test cleanup.
- Native SQLCipher packaging differs by host → record each verified host and
  interpreter; CI remains a regression signal, not an unsupported-platform
  claim.

## Migration Plan

The suite is added after the backend change. No production data migration is
required; a failing test blocks compatibility claims until the engine is
corrected or the supported matrix is narrowed.

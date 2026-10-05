# Tasks

## 1. Disposable test fixtures

- [x] 1.1 Add package-owned disposable Tortoise model and native migration fixtures; verify native migration can initialize an encrypted test database.
- [x] 1.2 Add reusable SQLCipher connection and Tortoise configuration helpers using only deterministic test keys; verify test setup closes all Tortoise connections.
- [x] 1.3 Add a parameterized SQLite-compatible Tortoise field and relation matrix, including TimeField and TimeDeltaField; verify persisted values round trip or retain their documented upstream SQLite limitation.

## 2. Encrypted storage evidence

- [x] 2.1 Add database/WAL plaintext-inspection and ordinary-SQLite rejection tests; verify every database and discovered sidecar created by the engine is encrypted and exposes neither schema nor record values in plaintext.
- [x] 2.2 Port native migration, rollback, and concurrent-write tests; verify expected records persist or roll back as specified.

## 3. Key replacement and platform evidence

- [x] 3.1 Add SQLCipher rekey and encrypted native backup/restore tests; verify the old key fails and the replacement key reads both databases.
- [x] 3.2 Record verified interpreter/platform results and distinguish them from unexecuted CI cells; verify the README or test documentation contains no unsupported compatibility claim.

## 4. Verification

- [x] 4.1 Run focused implementation tests, the complete configured pre-commit suite, and the supported Python-version matrix; verify all checks pass.

## 5. Review remediation

- [x] 5.1 Refactor integration setup into function-scoped async yield fixtures that close Tortoise connections even when initialization fails; verify cleanup after a forced setup failure.
- [x] 5.2 Extend the parameterized scalar matrix with CharEnumField and IntEnumField cases, using a module-scoped matrix database lifecycle and isolated field rows; verify every case round-trips its own value.
- [x] 5.3 Refactor TimeField coverage to use reusable engine fixtures and verify a rejected TimeField write leaves no persisted row.
- [x] 5.4 Make relation membership assertions order-independent; verify foreign-key, one-to-one, and many-to-many behavior remains covered.
- [x] 5.5 Verify native migration creates encrypted field and relation schemas, including ordinary-SQLite rejection and representative post-migration round trips.
- [x] 5.6 Split migrated rollback and concurrent-write coverage into focused tests; verify each scenario independently.
- [x] 5.7 Move native SQLCipher rekey/backup access into test support and verify the rekeyed source and backup through the package engine using the replacement key.
- [x] 5.8 Run focused remediation tests, the complete configured pre-commit suite, and the supported Python-version matrix; verify all checks pass.
- [x] 5.9 Run scalar-matrix fixture setup inside its fixture-level try/finally so failed initialization closes Tortoise connections without moving cleanup into tests.

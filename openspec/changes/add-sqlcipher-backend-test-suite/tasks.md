# Tasks

## 1. Disposable test fixtures

- [ ] 1.1 Add package-owned disposable Tortoise model and native migration fixtures; verify native migration can initialize an encrypted test database.
- [ ] 1.2 Add reusable SQLCipher connection and Tortoise configuration helpers using only deterministic test keys; verify test setup closes all Tortoise connections.

## 2. Encrypted storage evidence

- [ ] 2.1 Add database/WAL plaintext-inspection and ordinary-SQLite rejection tests; verify every database and discovered sidecar created by the engine is encrypted and exposes neither schema nor record values in plaintext.
- [ ] 2.2 Port native migration, rollback, and concurrent-write tests; verify expected records persist or roll back as specified.

## 3. Key replacement and platform evidence

- [ ] 3.1 Add SQLCipher rekey and encrypted native backup/restore tests; verify the old key fails and the replacement key reads both databases.
- [ ] 3.2 Record verified interpreter/platform results and distinguish them from unexecuted CI cells; verify the README or test documentation contains no unsupported compatibility claim.

## 4. Verification

- [ ] 4.1 Run focused implementation tests, the complete configured pre-commit suite, and the supported Python-version matrix; verify all checks pass.

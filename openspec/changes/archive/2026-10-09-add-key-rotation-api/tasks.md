# Tasks

## 1. Public rotation API

- [x] 1.1 Extend the internal SQLCipher connection protocol with sqlcipher3's native binary `reset_key` operation.
- [x] 1.2 Add asynchronous `rotate_key(replacement_key)` validation that accepts only 32-byte `bytes` values before acquiring exclusive access, and verify unit tests cover invalid types and lengths.
- [x] 1.3 Perform native rekeying through the asynchronous client connection, close and reopen with the replacement key before normal return, and verify the old key is rejected after reopening.
- [x] 1.4 Integrate rotation with the shared maintenance coordination boundary and its cancellation outcome rules, and verify ordinary client work cannot overlap the native rekey.

## 2. Security and lifecycle coverage

- [x] 2.1 Add integration coverage that creates an encrypted database, rotates it only through the public API, and reopens its data with the replacement key.
- [x] 2.2 Add regression coverage for translated driver failure, including replacement-key verification after a native error with a non-secret warning, and cancellation before and during the state-changing phase; verify post-start cancellation is re-raised with non-secret outcome detail only after client-state reconciliation and a later client operation remains usable.
- [x] 2.3 Add diagnostic-log coverage that verifies neither original nor replacement key material is rendered.
- [x] 2.4 Document the public rotation API, caller-managed external key storage, normal-return persistence rule, and post-start cancellation handling in the user-facing README.
- [x] 2.5 Use SQLite's public database metadata to identify databases without backing files, expose that inspection through the client API, and verify URI, temporary, and file-backed database outcomes.

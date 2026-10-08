# Tasks

## 1. Public rotation API

- [ ] 1.1 Extend the internal SQLCipher connection protocol with its native binary rekey operation, and verify static type checks pass.
- [ ] 1.2 Add asynchronous `rotate_key(replacement_key)` validation that accepts only 32-byte `bytes` values before acquiring exclusive access, and verify unit tests cover invalid types and lengths.
- [ ] 1.3 Perform native rekeying through the asynchronous client connection and update the configured key only after success, and verify the old key is rejected after reopening.
- [ ] 1.4 Integrate rotation with the shared maintenance coordination boundary and its cancellation outcome rules, and verify ordinary client work cannot overlap the native rekey.

## 2. Security and lifecycle coverage

- [ ] 2.1 Add integration coverage that creates an encrypted database, rotates it only through the public API, and reopens its data with the replacement key.
- [ ] 2.2 Add regression coverage for translated driver failure and cancellation before and during the state-changing phase, and verify cancellation is re-raised only after client-state reconciliation and a later client operation remains usable.
- [ ] 2.3 Add diagnostic-log coverage that verifies neither original nor replacement key material is rendered.

## 3. Verification

- [ ] 3.1 Run `uv run ruff check .`, `uv run ty check`, and `uv run pytest` and verify all checks pass.

# Proposal

## Why

Applications need to replace a SQLCipher database key without importing the
driver or issuing SQLCipher-specific statements.  A public backend operation
keeps binary-key validation, driver mechanics, error translation, and secret
handling within this package.

## What Changes

- Add an asynchronous public operation that rotates a configured 32-byte
  SQLCipher key to a replacement 32-byte key.
- Preserve the existing bytes-only key contract and keep key material out of
  diagnostic output.
- Define success, failure, and cancellation behaviour so callers can determine
  whether the replacement key is usable.
- Integrate rotation with the package-owned maintenance-coordination contract.

## Capabilities

### New Capabilities

- `sqlcipher-key-rotation`: Rotate an encrypted database's SQLCipher key
  through the public Tortoise client API.

### Modified Capabilities

None.

## Impact

- Affects the SQLCipher client, DB-API protocol boundary, exception handling,
  and integration tests.
- Depends on maintenance coordination to prevent normal Tortoise work from
  using a connection while it is being rekeyed.
- Lets consumers remove direct SQLCipher-driver and `PRAGMA rekey` use.

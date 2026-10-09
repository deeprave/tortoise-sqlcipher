# Tasks

## 1. Client coordination boundary

- [x] 1.1 Characterise the applicable Tortoise connection and transaction lock lifecycle, and verify the documented sequence against the installed dependency version.
- [x] 1.2 Add one internal client-owned maintenance context that excludes ordinary connection use and releases access in all exit paths; verify focused client lifecycle tests pass.
- [x] 1.3 Keep the boundary private for future feature-specific public API changes without exporting a general locking API; verify the client exposes no new public maintenance or locking method.
- [x] 1.4 Coordinate externally requested client closure with the maintenance boundary while retaining an internal non-reentrant close path; verify close-during-maintenance coverage passes.
- [x] 1.5 Document that multiple Tortoise aliases for one database file are unsupported for maintenance operations, and verify the warning is present in package architecture documentation.

## 2. Concurrency regression coverage

- [x] 2.1 Add integration coverage for a normal query overlapping each maintenance-operation test double or public operation, and verify it cannot observe an invalid connection state.
- [x] 2.2 Add coverage that overlapping maintenance operations do not interleave, and verify their observable ordering is deterministic.
- [x] 2.3 Add cancellation and failure coverage that proves a later query and maintenance operation can acquire a usable client state.
- [x] 2.4 Add regression coverage that Tortoise connection closure waits for active maintenance, and verify no operation uses a closed connection.

# Tasks

## 1. Windows evidence probe

- [ ] 1.1 Add a focused `windows-latest` CPython 3.13 probe to the test workflow and verify it installs the locked dependencies and runs the complete package test suite.
- [ ] 1.2 Capture the resolved `sqlcipher3` wheel, interpreter, and runner details from the Windows probe and verify the evidence identifies the exact tested environment.

## 2. Live-WAL assessment

- [ ] 2.1 Verify whether the encrypted-storage test can read the live database and WAL sidecars on the Windows runner; capture the exact failure if file sharing prevents it.
- [ ] 2.2 If live-WAL access fails, evaluate a synchronization design that preserves a live WAL and verify it still detects schema and record plaintext; do not close the database merely to make file reads pass.

## 3. Support decision

- [ ] 3.1 Record a Windows support recommendation based on probe evidence and verify it distinguishes the tested combination from an ongoing support contract.
- [ ] 3.2 If Windows support is approved, create a follow-up change for the maintained Windows CI matrix and platform contract; otherwise remove exploratory CI and verify the package makes no Windows support claim.

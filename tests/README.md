# Integration test evidence

The SQLCipher integration suite was verified locally with CPython 3.11.16,
3.12.13, 3.13.13, and 3.14.7 on macOS 27.0.1 arm64. That is evidence only for
those interpreters and platform.

The GitHub Actions workflow configures tests for CPython 3.11 through 3.14.
Configured but unexecuted workflow cells are regression targets, not verified
platform compatibility claims.

Windows is not yet fully supported. Its SQLCipher/WAL behaviour needs targeted
validation before the package can make a Windows compatibility claim.

# Security Policy

## Supported versions

Security fixes are provided for the latest release on the `main` branch.

## Reporting a vulnerability

Do not open a public issue for a suspected security vulnerability.

Use GitHub's private vulnerability-reporting form for this repository and include:

- a clear description of the impact;
- steps to reproduce or a minimal proof of concept;
- affected version or commit; and
- any suggested mitigation, if known.

Please allow up to 7 days for an acknowledgement. We will coordinate remediation and a disclosure timeline with the reporter before publishing details.

## Scope

Reports about the application source, release scripts, packaged runtime, and dependency integrity are in scope. Reports about third-party projects should also be reported to their upstream maintainers.

## Maintenance and release checks

CI audits the complete runtime/test and build locks on pull requests and weekly, on Python 3.11 and 3.12. Dependabot proposes Python and GitHub Actions updates; FFmpeg and native libraries inside wheels require a separate upstream advisory review. A passing pip-audit result does not cover CPython, Qt, FFmpeg or every bundled native codec.

Regenerate locks with `uv pip compile pyproject.toml --extra dev --python-version 3.11 --generate-hashes -o requirements-test.lock` and `uv pip compile requirements-build.in --python-version 3.11 --generate-hashes -o requirements-build.lock`. Review the resulting versions and hashes and run the media tests before accepting updates.

Portable builds require CPython 3.11.17+ or 3.12.15+ within the supported minor series, exact project dependency pins, the verified self-built FFmpeg 7.1.5 executables, and matching corresponding-source archives. Keep interpreter patch floors current with Python security releases. Do not bypass this check to ship an older Windows interpreter merely because newer official releases are source-only.

Treat media as untrusted: run without administrator privileges and keep the application, plugin directories and process environment under the user's control. Local-only FFmpeg input protocols reduce network exposure; they do not sandbox native decoders or prevent a crafted container from referring to other local files.

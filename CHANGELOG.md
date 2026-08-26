# Changelog

All notable public changes to Infinity Context are documented here.

## Unreleased

### Added

- A versioned, capability-attested, read-only exact document reconciliation API in the
  Python and TypeScript SDKs. It reports bounded canonical and indexed visibility states
  without first-page scans or consumer-specific lifecycle policy.

## 0.1.0 - 2026-08-05

First public alpha release.

See the [public installation and first-run guide](docs/public-installation.md).

### Added

- Apache License 2.0 and complete Python package metadata.
- A release pipeline for PyPI, GitHub release artifacts, provenance attestations,
  checksums, and a multi-architecture GHCR image.
- A safer local installer pinned to the `v0.1.0` release and the verified
  `plugin-kit-ai` 1.2.4 binary.
- Selected-agent onboarding for Codex, Claude, Gemini, OpenCode, and Cursor.
- Review-gated automatic memory capture as the normal onboarding mode, with
  explicit manual and retrieve-only alternatives.
- Automatic opening of the local memory UI after the runtime reports ready.

### Safety defaults

- Captured material is submitted as a suggestion and is never auto-applied.
- Raw tool events and transcript tails are not captured by the default policy.
- Agent configuration reads the service token from the local protected env file
  instead of embedding a development token.
- Agent integration failures remain visible and fall back to generated manual
  MCP configuration instead of being reported as successful.

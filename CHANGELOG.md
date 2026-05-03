# Changelog

All notable changes to Spendif.ai are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- Schema auto-invalidation: cached schemas (Flow 1) producing < 10% parse rate are automatically deleted and retried with Flow 2 (LLM re-classification)
- Orphan schema purge: startup migration removes `document_schema` rows without `header_sha256`, preventing unreachable stale entries
- Header SHA256 always populated on schema before persist, preventing orphan schemas from being created

## [0.1.0] - 2026-04-06

### Added
- Initial release
- Import CSV/XLSX bank statements (9 Italian financial instruments)
- Local AI categorisation via llama.cpp (Qwen3.5, Gemma4, Phi4, Llama3.2)
- NSI/OSI-aware counterpart matching
- History cache, user rules, taxonomy customisation
- macOS .app bundle, Spotlight integration
- Windows installer via winget/PowerShell
- Interactive analytics dashboard (coming soon)

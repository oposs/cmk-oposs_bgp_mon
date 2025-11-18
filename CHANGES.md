# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

### Changed

### Fixed

## 1.0.6 - 2025-11-18
## 1.0.5 - 2025-11-18
### Changed
- require ssl verification setting
- remove OETIKER+PARTNER from plugin name

## 1.0.4 - 2025-11-17
### Changed
- Agent now uses hostname instead of IP address for proper HTTPS/SSL certificate validation
- Added `if __name__ == "__main__"` guard to agent plugin for proper module import behavior

## 1.0.3 - 2025-11-17
### Fixed
- Fixed import error: removed deprecated `cmk.agent_based.v2.type_defs` import, now importing types directly from `cmk.agent_based.v2` for Checkmk 2.4.0+ compatibility

## 1.0.2 - 2025-11-17
### Changed
- Improved error message when pexpect library is missing for Huawei devices

### Fixed
- Fixed import error: changed `from cmk.utils import debug` to `from cmk.ccc import debug` for Checkmk 2.4.0+ compatibility

## 1.0.1 - 2025-11-13
### Fixed
- build correct mkp

## 1.0.0 - 2025-11-13

### Changed
- Ported to cmk api 2 and new plugin structures

### Fixed
- Make ssl security configurable



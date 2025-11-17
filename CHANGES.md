# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### New

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



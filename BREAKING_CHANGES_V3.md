# Breaking Changes for v3.0.0

This document outlines the breaking changes planned for nwp500-python v3.0.0.

## Overview

Version 3.0.0 will be the first major version to include breaking changes since the library's initial release. The primary focus is removing deprecated functionality and improving type safety.

## Scheduled Removals

### OperationMode Enum Removal

**Target**: v3.0.0  
**Current Status**: Deprecated in v2.0.0  
**Migration Period**: v2.x series (minimum 6 months)

The original `OperationMode` enum will be completely removed and replaced with:
- `DhwOperationSetting` for user-configured mode preferences
- `CurrentOperationMode` for real-time operational states

#### Impact Assessment
- **High Impact**: Code using direct enum comparisons
- **Medium Impact**: Type hints and function signatures
- **Low Impact**: Display-only usage (`.name` attribute)

#### Required Actions
1. Replace all `OperationMode` imports with specific enum imports
2. Update enum comparisons to use appropriate enum type
3. Update type hints in function signatures
4. Remove any `OperationMode` references from custom code

#### Migration Tools Available
- `MIGRATION.md` - Comprehensive migration guide
- `migrate_operation_mode_usage()` - Programmatic guidance
- `enable_deprecation_warnings()` - Runtime warning system
- Updated documentation with new enum usage patterns

## Pre-3.0 Checklist

Before releasing v3.0.0, ensure:

### Code Removal
- [ ] Remove `OperationMode` enum class from `models.py`
- [ ] Remove `OperationMode` from package exports (`__init__.py`)
- [ ] Remove deprecation warning infrastructure
- [ ] Update all internal references to use new enums

### Documentation Updates  
- [ ] Update all documentation to remove `OperationMode` references
- [ ] Update `MIGRATION.md` to reflect completed migration
- [ ] Update API documentation
- [ ] Update example scripts if any still reference old enum

### Testing
- [ ] Ensure all tests pass without `OperationMode`
- [ ] Add tests to verify enum removal
- [ ] Test that import errors are clear and helpful
- [ ] Validate all examples work with new enums only

### Communication
- [ ] Update CHANGELOG.rst with breaking changes
- [ ] Release notes highlighting breaking changes
- [ ] GitHub release with migration guidance
- [ ] Consider blog post or announcement for major users

## Timeline

```
v2.0.0 (Current)
├── OperationMode deprecated
├── New enums introduced  
├── Migration tools provided
└── Backward compatibility maintained

v2.1.0 (Optional)
├── Optional deprecation warnings
├── Enhanced migration tools
└── Continued compatibility

v2.x.x (6+ months)
├── Migration period
├── User feedback collection
└── Migration assistance

v3.0.0 (Target)
├── OperationMode removed
├── Breaking changes implemented
└── Type safety improvements
```

## Rollback Plan

If breaking changes cause significant issues:

1. **Emergency Patch**: Revert breaking changes in v3.0.1
2. **Deprecation Extension**: Extend deprecation period to v4.0.0
3. **Enhanced Migration**: Provide additional migration tools
4. **Communication**: Clear messaging about timeline changes

## Version Support

- **v2.x**: Long-term support with security fixes
- **v3.x**: Current development branch
- **v1.x**: End-of-life (security fixes only if critical)

## Migration Support

Migration support will be available:
- **During v2.x**: Full backward compatibility + new enums
- **During v3.0 beta**: Migration warnings and testing
- **After v3.0**: Documentation and examples only

## Contact

For questions about breaking changes or migration assistance:
- File GitHub issues with "migration" label
- Reference `MIGRATION.md` for detailed guidance
- Use `migrate_operation_mode_usage()` for programmatic help

---

*This document will be updated as v3.0.0 approaches with more specific details and timelines.*
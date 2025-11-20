---
description: Run linting and testing before completing tasks
---

# Pre-Completion Testing Workflow

Before marking any code-related task as complete, you MUST run the following checks:

## 1. Linting with Ruff

Run ruff to check for code style and quality issues:

```bash
ruff check src/ tests/ examples/
```

If there are any errors, fix them before proceeding. You can auto-fix many issues with:

```bash
ruff check --fix src/ tests/ examples/
```

## 2. Format Check with Ruff

Verify code formatting is correct:

```bash
ruff format --check src/ tests/ examples/
```

If formatting issues are found, apply formatting:

```bash
ruff format src/ tests/ examples/
```

## 3. Run Unit Tests

Execute the test suite to ensure no regressions:

```bash
pytest tests/
```

All tests must pass before completing the task.

## 4. Type Checking (Optional but Recommended)

If you've modified type annotations or core logic, run mypy:

```bash
mypy src/
```

## Summary

**Required before task completion:**
- ✅ Ruff linting passes (no errors)
- ✅ Ruff formatting check passes
- ✅ All pytest tests pass

**Recommended:**
- ✅ Mypy type checking passes (if types were modified)

## Quick Command

You can run all checks with:

```bash
ruff check src/ tests/ examples/ && ruff format --check src/ tests/ examples/ && pytest tests/
```

**IMPORTANT**: Do not claim a task is complete without running these checks. If any check fails, fix the issues and re-run the checks.

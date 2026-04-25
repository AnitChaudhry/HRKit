## Summary

<!-- 1-2 sentences on what this PR changes and why. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no functional change)
- [ ] Documentation
- [ ] Test improvement
- [ ] Other: ___

## Testing

- [ ] `python -m pytest tests/ -q` passes locally (all 72+ tests green)
- [ ] Added test(s) for new behavior, OR existing tests cover the change
- [ ] Manually smoke-tested by booting `hrkit serve` and exercising the affected flow

## Conventions checklist

- [ ] No hardcoded brand strings (use `branding.app_name()` for UI)
- [ ] No new dependencies added (or justification provided in description)
- [ ] No `print()` for debug — uses `logging`
- [ ] Type hints on public functions
- [ ] `from __future__ import annotations` on new files

## Linked issue

<!-- Closes #123 / Refs #456 -->

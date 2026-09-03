---
name: demo-fix-import
description: Fix ImportError problems by adding missing imports and resolving module paths
---

# Demo Fix Import

Use when Python raises ImportError or ModuleNotFoundError.

## Steps

- Read the traceback and locate the missing module name
- Check whether it is a stdlib module, a project module, or a missing dependency
- Add the import at the top of the file following local import style
- For missing third-party packages, suggest the uv add command instead of editing pyproject by hand
- Run the validation command to confirm the import resolves

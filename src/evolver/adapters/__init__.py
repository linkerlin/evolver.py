"""Adapter subsystem: IDE/editor integrations (Cursor, VS Code, etc.)."""

from evolver.adapters.auth import clear_auth, load_auth, logout, save_auth
from evolver.adapters.cursor import build_hooks_json
from evolver.adapters.cursor import install as cursor_install
from evolver.adapters.cursor import uninstall as cursor_uninstall
from evolver.adapters.hook_adapter import (
    assert_not_symlink,
    assert_safe_config_dir,
    copy_hook_scripts,
    deep_merge,
    detect_platform,
    load_adapter,
    merge_json_file,
    merge_with_hooks_union,
    remove_evolver_hooks,
    remove_hook_scripts,
    resolve_config_root,
    setup_hooks,
)
from evolver.adapters.reset_secret import reset_local_secret
from evolver.adapters.setup_hooks import install_hooks

__all__ = [
    "assert_not_symlink",
    "assert_safe_config_dir",
    "build_hooks_json",
    "clear_auth",
    "copy_hook_scripts",
    "cursor_install",
    "cursor_uninstall",
    "deep_merge",
    "detect_platform",
    "install_hooks",
    "load_adapter",
    "load_auth",
    "logout",
    "merge_json_file",
    "merge_with_hooks_union",
    "remove_evolver_hooks",
    "remove_hook_scripts",
    "reset_local_secret",
    "resolve_config_root",
    "save_auth",
    "setup_hooks",
]

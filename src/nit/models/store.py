"""Profile persistence — read/write `.nit/profile.json` with cache invalidation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from nit.models.profile import ProjectProfile

logger = logging.getLogger(__name__)

_NIT_DIR = ".nit"
_PROFILE_FILENAME = "profile.json"


def _nit_dir(root: str | Path) -> Path:
    """Return the ``.nit/`` directory for a project root."""
    return Path(root) / _NIT_DIR


def profile_path(root: str | Path) -> Path:
    """Return the path to ``.nit/profile.json``."""
    return _nit_dir(root) / _PROFILE_FILENAME


def save_profile(profile: ProjectProfile) -> Path:
    """Serialise *profile* to ``.nit/profile.json``.

    Creates the ``.nit/`` directory if it does not exist.
    Returns the path to the written file.
    """
    out = profile_path(profile.root)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(profile.to_dict(), indent=2) + "\n",
        encoding="utf-8",
    )
    logger.info("Profile saved to %s", out)
    return out


def load_profile(root: str | Path) -> ProjectProfile | None:
    """Load a ``ProjectProfile`` from ``.nit/profile.json``.

    Returns ``None`` when the file is missing or invalid.
    """
    path = profile_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Failed to read profile: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    return ProjectProfile.from_dict(data)


def is_profile_stale(root: str | Path) -> bool:
    """Check whether the cached profile is older than any source file.

    Compares the modification time of ``.nit/profile.json`` against the
    most-recently-modified tracked file (approximated by the git index
    timestamp or direct mtime scan of the root).

    Returns ``True`` when the profile should be regenerated.
    """
    path = profile_path(root)
    if not path.is_file():
        return True

    profile_mtime = path.stat().st_mtime

    # Fast path: compare against the git index timestamp if available.
    git_index = Path(root) / ".git" / "index"
    if git_index.is_file():
        return git_index.stat().st_mtime > profile_mtime

    # Fallback: compare against the root directory mtime.
    return Path(root).stat().st_mtime > profile_mtime

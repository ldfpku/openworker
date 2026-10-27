"""Optional cross-agent behavioral guidance loaded from packaged resources.

``COWORKER_UNIVERSAL_PROMPT`` selects ``balanced`` (the default), ``core``,
``complete``, or ``off``. The value is read for each new engine; prompt file
contents are cached, while switching modes does not require clearing that cache.
"""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import os

ENV_VAR = "COWORKER_UNIVERSAL_PROMPT"
_PROMPT_NAMES = ("core", "balanced", "complete")
_DISABLED = {"", "off", "none"}


@lru_cache(maxsize=3)
def _read_prompt(name: str) -> str:
    return (
        files("coworker")
        .joinpath("prompts", "universal", f"{name}.md")
        .read_text(encoding="utf-8")
        .strip()
    )


def load_universal_prompt() -> str:
    """Return the selected prompt, or an empty string when explicitly disabled."""
    name = os.getenv(ENV_VAR, "balanced").strip().lower()
    if name in _DISABLED:
        return ""
    if name not in _PROMPT_NAMES:
        choices = ", ".join((*_PROMPT_NAMES, "off"))
        raise ValueError(f"{ENV_VAR} must be one of: {choices}")
    return _read_prompt(name)

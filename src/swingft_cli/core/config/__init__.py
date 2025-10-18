"""
Config core package: loader/schema/rules split.
Public re-exports are provided via swingft_cli.config facade.
"""

from __future__ import annotations

from typing import Callable, Optional

# Optional prompt provider for interactive yes/no questions
PROMPT_PROVIDER: Optional[Callable[[str], str]] = None

def set_prompt_provider(provider: Callable[[str], str]) -> None:
    global PROMPT_PROVIDER
    PROMPT_PROVIDER = provider





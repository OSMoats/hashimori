"""Hashimori — a tiny, deterministic rules engine for AI governance.

Design time: review AI use cases (intake JSON → decision).
Runtime: enforce agent tool calls (effects → allow / ask / deny / rewrite).
Policy in YAML. Decisions in milliseconds, with an audit trail.
No model can grant: the engine never calls one, and optional model signals
can only escalate.
"""

from importlib.metadata import PackageNotFoundError, version

from hashimori.engine import evaluate, Decision
from hashimori.loader import load_packs, validate_pack

try:
    __version__ = version("hashimori")
except PackageNotFoundError:  # running from source, not installed -- e.g. a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["evaluate", "Decision", "load_packs", "validate_pack", "__version__"]

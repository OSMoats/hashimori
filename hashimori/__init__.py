"""Hashimori — a tiny, deterministic rules engine for AI use case governance.

Policy in YAML. Intake in JSON. Decision in milliseconds, with an audit trail.
No LLM in the decision path. Ever.
"""

from importlib.metadata import PackageNotFoundError, version

from hashimori.engine import evaluate, Decision
from hashimori.loader import load_packs, validate_pack

try:
    __version__ = version("hashimori")
except PackageNotFoundError:  # running from source, not installed -- e.g. a raw checkout
    __version__ = "0.0.0+unknown"

__all__ = ["evaluate", "Decision", "load_packs", "validate_pack", "__version__"]

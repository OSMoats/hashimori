"""Hashimori — a tiny, deterministic rules engine for AI use case governance.

Policy in YAML. Intake in JSON. Decision in milliseconds, with an audit trail.
No LLM in the decision path. Ever.
"""

from hashimori.engine import evaluate, Decision
from hashimori.loader import load_packs, validate_pack

__version__ = "0.1.0"

__all__ = ["evaluate", "Decision", "load_packs", "validate_pack", "__version__"]

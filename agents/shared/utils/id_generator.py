"""ID generation utilities with prefix-based UUID format."""

import uuid
from agents.shared.constants import (
    ID_PREFIX_BRAIN,
    ID_PREFIX_INGESTION,
    ID_PREFIX_QUALITY,
    ID_PREFIX_PREDICTIVE,
    ID_PREFIX_SUSTAINABILITY,
    ID_PREFIX_TWIN,
    ID_PREFIX_EDGE,
    ID_PREFIX_WORK_ORDER,
)


def generate_id(prefix: str) -> str:
    """Generate a prefixed UUID identifier."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


def generate_brain_id() -> str:
    return generate_id(ID_PREFIX_BRAIN)


def generate_ingestion_id() -> str:
    return generate_id(ID_PREFIX_INGESTION)


def generate_quality_id() -> str:
    return generate_id(ID_PREFIX_QUALITY)


def generate_predictive_id() -> str:
    return generate_id(ID_PREFIX_PREDICTIVE)


def generate_sustainability_id() -> str:
    return generate_id(ID_PREFIX_SUSTAINABILITY)


def generate_twin_id() -> str:
    return generate_id(ID_PREFIX_TWIN)


def generate_edge_id() -> str:
    return generate_id(ID_PREFIX_EDGE)


def generate_work_order_id(sequence: int) -> str:
    """Generate sequential work order ID."""
    return f"{ID_PREFIX_WORK_ORDER}{sequence}"

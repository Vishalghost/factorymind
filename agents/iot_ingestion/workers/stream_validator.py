"""Stream Validator Worker — validates CNC sensor readings against physical ranges.

Rejects readings with:
- Stale timestamps (>60s old)
- Values outside physical ranges for titanium milling
- Invalid machine_id or reading_id patterns
"""

from typing import Any, Optional

from pydantic import ValidationError

from agents.shared.models.sensor import SensorReading


def validate_reading(
    raw_record: dict[str, Any],
) -> tuple[Optional[SensorReading], Optional[str]]:
    """Validate a raw sensor record against physical constraints.

    Args:
        raw_record: Raw dictionary from Kinesis record.

    Returns:
        Tuple of (validated SensorReading or None, error message or None).
        Exactly one will be None.
    """
    try:
        reading = SensorReading(**raw_record)
        return reading, None
    except ValidationError as e:
        # Extract first error message for logging
        errors = e.errors()
        if errors:
            first_error = errors[0]
            field = ".".join(str(loc) for loc in first_error.get("loc", []))
            msg = first_error.get("msg", "validation error")
            return None, f"{field}: {msg}"
        return None, str(e)
    except Exception as e:
        return None, f"Unexpected error: {str(e)}"

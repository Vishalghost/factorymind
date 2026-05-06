"""Brain Agent manager invocation tools.

Provides thin Lambda invoke wrappers for each Manager Agent,
plus a parallel invocation utility for multi-manager delegation.
"""

from agents.brain.tools.invoke_iot_ingestion import invoke_iot_ingestion
from agents.brain.tools.invoke_quality_vision import invoke_quality_vision
from agents.brain.tools.invoke_predictive_maintenance import invoke_predictive_maintenance
from agents.brain.tools.invoke_sustainability import invoke_sustainability
from agents.brain.tools.invoke_digital_twin import invoke_digital_twin
from agents.brain.tools.parallel_invoke import invoke_managers_parallel

__all__ = [
    "invoke_iot_ingestion",
    "invoke_quality_vision",
    "invoke_predictive_maintenance",
    "invoke_sustainability",
    "invoke_digital_twin",
    "invoke_managers_parallel",
]

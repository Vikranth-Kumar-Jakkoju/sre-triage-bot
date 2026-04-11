"""
Data models for the Cloud SRE Triage Environment.

Three tasks of increasing difficulty:
  - Task 1 (easy):   sre-triage-easy   — single alert, one correct action
  - Task 2 (medium): sre-triage-medium — multi-service alert, requires diagnosis
  - Task 3 (hard):   sre-triage-hard   — cascading failure, multi-step resolution
"""

from typing import Literal, Optional
from openenv.core.env_server.types import Action, Observation
from pydantic import Field


# ---------------------------------------------------------------------------
# Shared Action (same schema for all 3 tasks)
# ---------------------------------------------------------------------------

class SREAction(Action):
    """
    An action taken by the SRE agent to resolve an incident.

    Fields:
        action_type: One of 'check_logs', 'restart_service', 'scale_up',
                     'rollback_deploy', 'page_oncall', 'no_op'
        target_service: Which service to act on (e.g. 'api', 'database', 'cache')
        reasoning: Short justification for the action (used for partial credit)
    """
    action_type: Literal[
        "check_logs",
        "restart_service",
        "scale_up",
        "rollback_deploy",
        "page_oncall",
        "no_op",
    ] = Field(..., description="The remediation action to take")
    target_service: str = Field(
        default="api",
        description="The service to act on",
    )
    reasoning: str = Field(
        default="",
        description="Agent's reasoning for choosing this action",
    )


# ---------------------------------------------------------------------------
# Shared Observation (same schema for all 3 tasks)
# ---------------------------------------------------------------------------

class SREObservation(Observation):
    """
    Observation returned to the agent after each step.

    Fields:
        alert_summary:    Current active alerts description
        service_statuses: Dict mapping service name -> status string
        step_count:       Current step number within the episode
        last_action_result: What happened as a result of the last action
        score:            Current cumulative score in (0, 1) — used by grader
    """
    alert_summary: str = Field(
        default="",
        description="Summary of active alerts",
    )
    service_statuses: dict = Field(
        default_factory=dict,
        description="Map of service -> status",
    )
    step_count: int = Field(default=0, description="Current step number")
    last_action_result: str = Field(
        default="",
        description="Result of the last action taken",
    )
    incident_resolved: bool = Field(
        default=False,
        description="Whether the incident has been fully resolved",
    )
    hint: Optional[str] = Field(
        default=None,
        description="Optional hint to guide the agent",
    )

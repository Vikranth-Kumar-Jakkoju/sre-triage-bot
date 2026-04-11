"""
SRE Triage Medium Environment.

Scenario: Database connection pool exhausted, causing cascading failures
in the API and worker services. The agent must:
  1. check_logs on 'api' or 'database' to discover root cause
  2. restart_service on 'database' OR scale_up on 'database'

Partial credit is given for useful diagnostic steps.

Difficulty: MEDIUM
Max steps:  6
Score range: strictly (0, 1)
"""

from uuid import uuid4
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import SREAction, SREObservation
except ImportError:
    from models import SREAction, SREObservation

MAX_STEPS = 6
ROOT_CAUSE_SERVICE = "database"
RESOLUTION_ACTIONS = {"restart_service", "scale_up"}


class SREMediumEnvironment(Environment):
    """
    Medium SRE triage: cascading failure from DB connection pool exhaustion.

    Multiple services are degraded. The agent must diagnose the root cause
    (database connection pool) before taking the correct remediation.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._resolved = False
        self._diagnosed = False       # True after agent checks DB logs
        self._partial_credit = 0.0
        self._diag_services: set[str] = set()

    def reset(self, seed=None, episode_id=None, **kwargs) -> SREObservation:
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        self._resolved = False
        self._diagnosed = False
        self._partial_credit = 0.0
        self._diag_services = set()
        return SREObservation(
            alert_summary=(
                "[CRITICAL] api-gateway: 502 Bad Gateway — upstream timeout | "
                "[WARNING]  worker-service: job queue backlog 5000+ | "
                "[WARNING]  database: connection pool 98% utilized"
            ),
            service_statuses={
                "api": "CRITICAL - 502 errors",
                "worker": "WARNING - queue backlog",
                "database": "WARNING - connection pool near limit",
                "cache": "OK",
            },
            step_count=0,
            last_action_result="Multi-service incident detected. Investigate root cause.",
            incident_resolved=False,
            done=False,
            reward=0.0,
            hint="Multiple services are affected. Which one might be the root cause?",
        )

    def step(self, action: SREAction, **kwargs) -> SREObservation:  # type: ignore[override]
        self._state.step_count += 1
        step = self._state.step_count
        reward = 0.0
        result_msg = ""
        hint = None

        if self._resolved:
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses={s: "OK" for s in ["api", "worker", "database", "cache"]},
                step_count=step,
                last_action_result="Incident already resolved.",
                incident_resolved=True,
                done=True,
                reward=0.0,
            )

        act = action.action_type
        svc = action.target_service.lower().strip()

        if act == "check_logs":
            self._diag_services.add(svc)
            if svc == ROOT_CAUSE_SERVICE:
                self._diagnosed = True
                reward = 0.18
                result_msg = (
                    "📋 database logs: 'Too many connections' error — max_connections=100 "
                    "reached. All new connection attempts are being refused. "
                    "API and worker services are timing out waiting for DB connections."
                )
                hint = "Root cause identified: DB connection pool exhausted. What do you do?"
            elif svc == "api":
                reward = 0.08
                result_msg = (
                    "📋 api logs: 'upstream connect error' — DB connection timed out. "
                    "The API is healthy but cannot reach the database."
                )
                hint = "The API is fine — the problem is upstream. Check the database."
            else:
                reward = 0.03
                result_msg = f"📋 {svc} logs: No anomalies found locally."
                hint = "Look at the services showing warnings in the alert summary."

        elif act in RESOLUTION_ACTIONS and svc == ROOT_CAUSE_SERVICE:
            if self._diagnosed:
                # Correct action after proper diagnosis — maximum score
                step_bonus = max(0, MAX_STEPS - step)
                base = 0.55
                bonus = step_bonus * 0.06        # up to 0.30
                reward = round(min(base + bonus, 0.94), 4)
            else:
                # Correct action but no diagnosis — lower score
                reward = 0.40
            self._resolved = True
            action_word = "Restarted" if act == "restart_service" else "Scaled up"
            result_msg = (
                f"✅ {action_word} database successfully. "
                "Connection pool cleared. API error rate → 0%. Worker queue draining."
            )
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses={s: "OK" for s in ["api", "worker", "database", "cache"]},
                step_count=step,
                last_action_result=result_msg,
                incident_resolved=True,
                done=True,
                reward=reward,
            )

        elif act in RESOLUTION_ACTIONS and svc != ROOT_CAUSE_SERVICE:
            reward = 0.04
            result_msg = (
                f"⚠️ {act} on '{svc}' completed, but DB connection pool still exhausted. "
                "API errors continue."
            )
            hint = "Wrong service. The database is the root cause."

        elif act == "rollback_deploy":
            reward = 0.05
            result_msg = (
                "⚠️ Rollback attempted, but no recent deployment found. "
                "This is a resource exhaustion issue, not a bad deploy."
            )
            hint = "No recent deploy to rollback. Investigate the database."

        elif act == "page_oncall":
            reward = 0.06
            result_msg = "📟 On-call paged. They're reviewing the alerts now."
            hint = "Good escalation, but try to resolve it yourself."

        else:
            reward = 0.01
            result_msg = f"Action '{act}' on '{svc}' had no meaningful effect."
            hint = "Try investigating the services that are showing warnings."

        self._partial_credit += reward
        capped = round(min(self._partial_credit, 0.45), 4)
        done = step >= MAX_STEPS

        return SREObservation(
            alert_summary=(
                "[CRITICAL] api-gateway: 502 Bad Gateway | "
                "[WARNING] database: connection pool exhausted"
                if not done
                else "[TIMEOUT] Incident escalated — SLA breached."
            ),
            service_statuses={
                "api": "CRITICAL" if not done else "DEGRADED",
                "worker": "WARNING",
                "database": "WARNING - connection pool near limit",
                "cache": "OK",
            },
            step_count=step,
            last_action_result=result_msg,
            incident_resolved=False,
            done=done,
            reward=capped if done else reward,
            hint=hint,
        )

    @property
    def state(self) -> State:
        return self._state

    def get_metadata(self):
        from openenv.core.env_server.interfaces import EnvironmentMetadata
        return EnvironmentMetadata(
            name="sre-triage-medium",
            description=(
                "Medium SRE triage: multiple services are degraded due to a "
                "database connection pool exhaustion. Diagnose then remediate."
            ),
            version="1.0.0",
        )

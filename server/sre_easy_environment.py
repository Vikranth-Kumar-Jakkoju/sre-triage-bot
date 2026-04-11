"""
SRE Triage Easy Environment.

Scenario: A single microservice (API gateway) is returning 5xx errors.
The correct action is 'restart_service' targeting 'api'.

Difficulty: EASY
Max steps:  5
Score range: strictly (0, 1) — never 0.0 or 1.0
"""

from uuid import uuid4
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import SREAction, SREObservation
except ImportError:
    from models import SREAction, SREObservation

CORRECT_ACTION = "restart_service"
CORRECT_TARGET = "api"
MAX_STEPS = 5


class SREEasyEnvironment(Environment):
    """
    Easy SRE triage: single-service incident, one correct action.

    The agent sees high error-rate alerts on the API service and must
    restart it to resolve the incident.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._resolved = False
        self._partial_credit = 0.0   # accumulated across steps
        self._actions_taken: list[str] = []

    def reset(self, seed=None, episode_id=None, **kwargs) -> SREObservation:
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        self._resolved = False
        self._partial_credit = 0.0
        self._actions_taken = []
        return SREObservation(
            alert_summary=(
                "[CRITICAL] api-gateway: HTTP 5xx error rate 87% (threshold: 5%) | "
                "Latency p99=12s | Pod restarts: 0 in last 10m"
            ),
            service_statuses={
                "api": "CRITICAL - high error rate",
                "database": "OK",
                "cache": "OK",
                "queue": "OK",
            },
            step_count=0,
            last_action_result="Incident opened. Awaiting first action.",
            incident_resolved=False,
            done=False,
            reward=0.0,
            hint="Check which service has the highest error rate first.",
        )

    def step(self, action: SREAction, **kwargs) -> SREObservation:  # type: ignore[override]
        self._state.step_count += 1
        step = self._state.step_count
        reward = 0.0
        result_msg = ""

        if self._resolved:
            # Episode already done — penalise extra steps lightly
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses={"api": "OK", "database": "OK", "cache": "OK", "queue": "OK"},
                step_count=step,
                last_action_result="Incident already resolved. No further action needed.",
                incident_resolved=True,
                done=True,
                reward=0.0,
            )

        act = action.action_type
        svc = action.target_service.lower().strip()
        self._actions_taken.append(f"{act}:{svc}")

        if act == CORRECT_ACTION and svc == CORRECT_TARGET:
            # Perfect resolution
            # Score formula: higher reward for fewer steps (never reaches 1.0 exactly)
            step_bonus = max(0, MAX_STEPS - step)          # 0-4
            base = 0.60
            bonus = step_bonus * 0.07                       # 0.0 – 0.28
            reward = round(min(base + bonus, 0.96), 4)     # max 0.88, strictly < 1
            self._resolved = True
            result_msg = (
                f"✅ API gateway restarted successfully. "
                f"Error rate dropped to 0.1%. Incident resolved in {step} step(s)."
            )
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses={"api": "OK", "database": "OK", "cache": "OK", "queue": "OK"},
                step_count=step,
                last_action_result=result_msg,
                incident_resolved=True,
                done=True,
                reward=reward,
            )

        elif act == "check_logs" and svc == CORRECT_TARGET:
            # Useful diagnostic — partial credit
            reward = 0.12
            result_msg = (
                "📋 Logs show: OOMKilled events in api-gateway pod 3m ago. "
                "Memory usage at 98%. Consider restarting the service."
            )
            hint = "Logs confirm memory issue. What should you do next?"

        elif act == "check_logs":
            reward = 0.04
            result_msg = f"📋 Logs for '{svc}': No anomalies found."
            hint = "The problem seems to be in the api service."

        elif act == "restart_service" and svc != CORRECT_TARGET:
            reward = 0.02
            result_msg = f"⚠️ Restarted '{svc}', but error rate on api unchanged."
            hint = "You restarted the wrong service. Check which one has alerts."

        elif act == "scale_up" and svc == CORRECT_TARGET:
            reward = 0.08
            result_msg = (
                "⚠️ Scaled API replicas to 3. Error rate reduced to 42% but not resolved. "
                "Root cause (memory leak) still active."
            )
            hint = "Scaling helped partially. A restart might clear the memory leak."

        elif act == "page_oncall":
            reward = 0.05
            result_msg = "📟 On-call engineer paged. ETA 10 minutes."
            hint = "On-call notified, but try to resolve it yourself first."

        else:
            reward = 0.01
            result_msg = f"Action '{act}' on '{svc}' had no effect on the incident."
            hint = "Think about which service is failing and what would fix it."

        self._partial_credit += reward
        # Cap partial credit so episode-end score stays < 1.0
        episode_score = round(min(self._partial_credit, 0.45), 4)

        done = step >= MAX_STEPS
        return SREObservation(
            alert_summary=(
                "[CRITICAL] api-gateway: HTTP 5xx error rate 87% | Latency p99=12s"
                if not done else "[TIMEOUT] Incident auto-escalated after max steps."
            ),
            service_statuses={
                "api": "CRITICAL - high error rate",
                "database": "OK",
                "cache": "OK",
                "queue": "OK",
            },
            step_count=step,
            last_action_result=result_msg,
            incident_resolved=False,
            done=done,
            reward=episode_score if done else reward,
            hint=hint if "hint" in dir() else None,
        )

    @property
    def state(self) -> State:
        return self._state

    def get_metadata(self):
        from openenv.core.env_server.interfaces import EnvironmentMetadata
        return EnvironmentMetadata(
            name="sre-triage-easy",
            description=(
                "Easy SRE triage: a single microservice is down. "
                "Identify and restart the correct service to resolve the incident."
            ),
            version="1.0.0",
        )

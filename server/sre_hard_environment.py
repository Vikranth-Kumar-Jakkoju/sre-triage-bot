"""
SRE Triage Hard Environment.

Scenario: A bad deployment triggered a cascading failure:
  - New code has a memory leak  → pods OOMKill repeatedly
  - Cache invalidated by restart → database gets overwhelmed (thundering herd)
  - Circuit breaker opened       → API returns 503 to all clients

Optimal resolution sequence (3 specific steps):
  1. rollback_deploy  on 'api'       (stops the leak source)
  2. restart_service  on 'cache'     (warms up cache, reduces DB load)
  3. restart_service  on 'database'  (clears overwhelmed connections)

Partial credit for correct sub-sequences or close approaches.

Difficulty: HARD
Max steps:  8
Score range: strictly (0, 1)
"""

from uuid import uuid4
from openenv.core.env_server.interfaces import Environment
from openenv.core.env_server.types import State

try:
    from ..models import SREAction, SREObservation
except ImportError:
    from models import SREAction, SREObservation

MAX_STEPS = 8

# The three stages of resolution
STAGE_1 = ("rollback_deploy", "api")
STAGE_2 = ("restart_service", "cache")
STAGE_3 = ("restart_service", "database")


class SREHardEnvironment(Environment):
    """
    Hard SRE triage: cascading failure from bad deployment.

    Requires correct multi-step root-cause analysis and remediation
    in the right sequence. Tests planning and prioritisation.
    """

    SUPPORTS_CONCURRENT_SESSIONS: bool = True

    def __init__(self):
        self._state = State(episode_id=str(uuid4()), step_count=0)
        self._stage = 0          # 0=none, 1=rollback done, 2=cache done, 3=resolved
        self._checked: set[str] = set()
        self._partial_credit = 0.0

    def _status_for_stage(self) -> dict:
        if self._stage == 0:
            return {
                "api": "CRITICAL - 503 circuit-breaker open, OOMKill loop",
                "cache": "CRITICAL - empty, cache miss rate 100%",
                "database": "CRITICAL - connection saturation 99%",
                "worker": "WARNING - retrying failed jobs",
            }
        elif self._stage == 1:
            return {
                "api": "DEGRADED - rollback complete, circuit-breaker still open",
                "cache": "CRITICAL - still empty",
                "database": "CRITICAL - connections still saturated",
                "worker": "WARNING",
            }
        elif self._stage == 2:
            return {
                "api": "DEGRADED - circuit-breaker recovering",
                "cache": "OK - warming up",
                "database": "WARNING - load reducing",
                "worker": "OK",
            }
        else:
            return {s: "OK" for s in ["api", "cache", "database", "worker"]}

    def _alert_for_stage(self) -> str:
        if self._stage == 0:
            return (
                "[CRITICAL] api: 503 Service Unavailable — circuit-breaker OPEN | "
                "[CRITICAL] api: OOMKilled 7 times in 5 minutes | "
                "[CRITICAL] cache: miss rate 100% — cache appears empty | "
                "[CRITICAL] database: max_connections reached"
            )
        elif self._stage == 1:
            return (
                "[WARNING] api: circuit-breaker still open — needs cache/DB recovery | "
                "[CRITICAL] cache: still empty | "
                "[CRITICAL] database: connections saturated"
            )
        elif self._stage == 2:
            return (
                "[WARNING] database: connections still elevated — restart recommended"
            )
        return "[RESOLVED] All systems nominal."

    def reset(self, seed=None, episode_id=None, **kwargs) -> SREObservation:
        self._state = State(episode_id=episode_id or str(uuid4()), step_count=0)
        self._stage = 0
        self._checked = set()
        self._partial_credit = 0.0
        return SREObservation(
            alert_summary=self._alert_for_stage(),
            service_statuses=self._status_for_stage(),
            step_count=0,
            last_action_result="Cascading failure detected. Full system degradation. Investigate.",
            incident_resolved=False,
            done=False,
            reward=0.0,
            hint="Multiple critical alerts. Identify which recent change might have caused this.",
        )

    def step(self, action: SREAction, **kwargs) -> SREObservation:  # type: ignore[override]
        self._state.step_count += 1
        step = self._state.step_count
        reward = 0.0
        hint = None
        result_msg = ""

        if self._stage == 3:
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses=self._status_for_stage(),
                step_count=step,
                last_action_result="Incident already resolved.",
                incident_resolved=True,
                done=True,
                reward=0.0,
            )

        act = action.action_type
        svc = action.target_service.lower().strip()

        # --- Correct stage transitions ---
        if act == STAGE_1[0] and svc == STAGE_1[1] and self._stage == 0:
            self._stage = 1
            reward = 0.22
            result_msg = (
                "✅ Rollback to v1.4.2 successful. OOMKill loop stopped. "
                "Circuit-breaker still open — cache and DB need recovery."
            )
            hint = "Rollback done. Now fix the cache stampede."

        elif act == STAGE_2[0] and svc == STAGE_2[1] and self._stage == 1:
            self._stage = 2
            reward = 0.22
            result_msg = (
                "✅ Cache restarted and warming up. "
                "Cache miss rate falling. DB connection load reducing."
            )
            hint = "Cache recovering. One more step — clear the database connections."

        elif act == STAGE_3[0] and svc == STAGE_3[1] and self._stage == 2:
            # Final correct step — compute full score
            self._stage = 3
            step_bonus = max(0, MAX_STEPS - step)
            base = 0.50
            # Each correct prior step earned 0.22; final step brings it home
            bonus = step_bonus * 0.05
            reward = round(min(base + bonus + self._partial_credit * 0.3, 0.95), 4)
            result_msg = (
                "✅ Database connections cleared. Circuit-breaker closed. "
                "All services returning to healthy state. Incident resolved!"
            )
            return SREObservation(
                alert_summary="[RESOLVED] All systems nominal.",
                service_statuses=self._status_for_stage(),
                step_count=step,
                last_action_result=result_msg,
                incident_resolved=True,
                done=True,
                reward=reward,
            )

        # --- Partial credit paths ---
        elif act == "check_logs":
            self._checked.add(svc)
            if svc == "api" and self._stage == 0:
                reward = 0.10
                result_msg = (
                    "📋 api logs: OOMKilled repeatedly. Memory usage 100%. "
                    "Deploy timestamp: 14:32 UTC (22 minutes ago). "
                    "Prior version: v1.4.2 (stable). Current: v1.5.0."
                )
                hint = "Recent deploy looks suspicious. Consider rolling it back."
            elif svc == "cache" and self._stage >= 1:
                reward = 0.08
                result_msg = (
                    "📋 cache logs: Flushed during api restart storm. "
                    "All keys expired. Thundering herd toward DB."
                )
                hint = "Cache is empty — restart it to start warming up."
            elif svc == "database":
                reward = 0.07
                result_msg = (
                    "📋 database logs: Connection saturation from cache miss. "
                    "10,000 cache-miss queries/s (normal: 200/s)."
                )
                hint = "DB overload is caused by cache misses. Fix cache first."
            else:
                reward = 0.03
                result_msg = f"📋 {svc} logs: No additional information."

        elif act == STAGE_1[0] and svc != STAGE_1[1]:
            reward = 0.04
            result_msg = f"⚠️ Rolled back '{svc}', but api OOMKill loop continues."
            hint = "Wrong service. Which service had the recent deployment?"

        elif act == STAGE_3[0] and svc == STAGE_3[1] and self._stage == 0:
            # Trying DB restart without rollback first
            reward = 0.07
            result_msg = (
                "⚠️ Database connections cleared temporarily, but cache is still empty. "
                "Thundering herd will saturate DB again in ~30s. "
                "And API is still OOMKilling."
            )
            hint = "You need to fix the memory leak first, then the cache."

        elif act == "page_oncall":
            reward = 0.05
            result_msg = "📟 Senior SRE paged. They're joining the incident bridge."
            hint = "Good escalation. Keep troubleshooting while they join."

        elif act == "scale_up":
            reward = 0.04
            result_msg = (
                f"⚠️ Scaled '{svc}' up, but the root cause (bad deploy + cache storm) "
                "is still active. Scaling won't fix it."
            )
            hint = "Scaling masks the symptom. Find and fix the root cause."

        else:
            reward = 0.01
            result_msg = f"Action '{act}' on '{svc}' had no effect at this stage."
            hint = "Review the alerts carefully. What changed recently?"

        self._partial_credit += reward
        capped = round(min(self._partial_credit, 0.48), 4)
        done = step >= MAX_STEPS

        return SREObservation(
            alert_summary=self._alert_for_stage(),
            service_statuses=self._status_for_stage(),
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
            name="sre-triage-hard",
            description=(
                "Hard SRE triage: cascading failure from bad deployment. "
                "Requires multi-step root-cause analysis and correct remediation sequence."
            ),
            version="1.0.0",
        )

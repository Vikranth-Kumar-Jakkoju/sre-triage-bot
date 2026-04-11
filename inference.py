"""
inference.py — Cloud SRE Triage Agent
======================================
Runs the LLM agent against all 3 SRE triage tasks and emits the
EXACT stdout format required by the OpenEnv hackathon validator:

    [START] task=<task_name> env=<benchmark> model=<model_name>
    [STEP]  step=<n> action=<action_str> reward=<0.00> done=<true|false> error=<msg|null>
    [END]   success=<true|false> steps=<n> score=<score> rewards=<r1,r2,...,rn>

Rules enforced:
  - One [START] per episode
  - One [STEP] per step immediately after env.step() returns
  - One [END] after env.close(), always emitted (even on exception)
  - reward / rewards formatted to 2 decimal places
  - done / success are lowercase booleans
  - score in (0, 1) — never 0.0, never 1.0
  - All fields on a single line, no newlines within
"""

import os
import sys
import json
from typing import Optional

from openai import OpenAI

# ---------------------------------------------------------------------------
# Config — set these as HF Space secrets before submitting
# ---------------------------------------------------------------------------
API_KEY: str = os.getenv("HF_TOKEN") or os.getenv("API_KEY", "dummy-key")
API_BASE_URL: str = os.getenv("API_BASE_URL", "https://router.huggingface.co/v1")
MODEL_NAME: str = os.getenv("MODEL_NAME", "Qwen/Qwen2.5-72B-Instruct")

MAX_STEPS = 8          # safety cap per episode
SUCCESS_SCORE_THRESHOLD = 0.10   # score > this → success=true

# ---------------------------------------------------------------------------
# Task definitions — (task_name, benchmark, env_class)
# ---------------------------------------------------------------------------
def _load_tasks():
    """Import env classes. Works from both root and server/ sub-dirs."""
    try:
        from server.sre_easy_environment import SREEasyEnvironment
        from server.sre_medium_environment import SREMediumEnvironment
        from server.sre_hard_environment import SREHardEnvironment
    except ImportError:
        from sre_easy_environment import SREEasyEnvironment
        from sre_medium_environment import SREMediumEnvironment
        from sre_hard_environment import SREHardEnvironment
    return [
        ("sre-triage-easy",   "cloud-sre-triage", SREEasyEnvironment),
        ("sre-triage-medium", "cloud-sre-triage", SREMediumEnvironment),
        ("sre-triage-hard",   "cloud-sre-triage", SREHardEnvironment),
    ]


# ---------------------------------------------------------------------------
# Logging helpers — exact format from spec
# ---------------------------------------------------------------------------
def log_start(task: str, env_name: str, model: str) -> None:
    print(f"[START] task={task} env={env_name} model={model}", flush=True)


def log_step(step: int, action: str, reward: float, done: bool,
             error: Optional[str]) -> None:
    err_val = error if error else "null"
    done_val = str(done).lower()
    # Sanitise action string — remove newlines
    action_clean = action.replace("\n", " ").replace("\r", "")[:200]
    print(
        f"[STEP] step={step} action={action_clean} "
        f"reward={reward:.2f} done={done_val} error={err_val}",
        flush=True,
    )


def log_end(success: bool, steps: int, score: float,
            rewards: list[float]) -> None:
    rewards_str = ",".join(f"{r:.2f}" for r in rewards)
    print(
        f"[END] success={str(success).lower()} steps={steps} "
        f"score={score:.3f} rewards={rewards_str}",
        flush=True,
    )


# ---------------------------------------------------------------------------
# LLM call — returns a SREAction-compatible dict; falls back on any error
# ---------------------------------------------------------------------------
def get_llm_action(client: OpenAI, obs_dict: dict, step: int) -> dict:
    """
    Ask the LLM to pick the next action.
    Always returns a valid action dict even if the API call fails.
    """
    fallback = {"action_type": "check_logs", "target_service": "api",
                "reasoning": "fallback due to API error"}

    alert = obs_dict.get("alert_summary", "")
    statuses = obs_dict.get("service_statuses", {})
    last_result = obs_dict.get("last_action_result", "")
    hint = obs_dict.get("hint", "")

    system_prompt = (
        "You are an expert SRE agent. You must respond with ONLY a JSON object "
        "containing exactly these keys:\n"
        '  "action_type": one of "check_logs"|"restart_service"|"scale_up"|'
        '"rollback_deploy"|"page_oncall"|"no_op"\n'
        '  "target_service": one of "api"|"database"|"cache"|"worker"\n'
        '  "reasoning": one short sentence (max 20 words)\n'
        "No markdown, no code fences, just raw JSON."
    )

    user_prompt = (
        f"Step {step}.\n"
        f"ALERTS: {alert}\n"
        f"SERVICE STATUSES: {json.dumps(statuses)}\n"
        f"LAST ACTION RESULT: {last_result}\n"
        f"HINT: {hint}\n\n"
        "What is your next action? Respond with JSON only."
    )

    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            max_tokens=120,
            temperature=0.0,
        )
        raw = (response.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw.strip())

        valid_actions = {
            "check_logs", "restart_service", "scale_up",
            "rollback_deploy", "page_oncall", "no_op",
        }
        valid_services = {"api", "database", "cache", "worker"}

        act = str(parsed.get("action_type", "check_logs")).lower()
        svc = str(parsed.get("target_service", "api")).lower()

        if act not in valid_actions:
            act = "check_logs"
        if svc not in valid_services:
            svc = "api"

        return {
            "action_type": act,
            "target_service": svc,
            "reasoning": str(parsed.get("reasoning", ""))[:100],
        }

    except Exception as exc:
        print(f"[DEBUG] LLM error at step {step}: {type(exc).__name__}: {exc}",
              flush=True)
        # Smart fallback: escalate through useful actions
        fallback_sequence = [
            {"action_type": "check_logs",      "target_service": "api",      "reasoning": "fallback"},
            {"action_type": "check_logs",      "target_service": "database", "reasoning": "fallback"},
            {"action_type": "restart_service", "target_service": "api",      "reasoning": "fallback"},
            {"action_type": "rollback_deploy", "target_service": "api",      "reasoning": "fallback"},
            {"action_type": "restart_service", "target_service": "database", "reasoning": "fallback"},
        ]
        return fallback_sequence[min(step - 1, len(fallback_sequence) - 1)]


# ---------------------------------------------------------------------------
# Single episode runner
# ---------------------------------------------------------------------------
def run_episode(client: OpenAI, task_name: str, benchmark: str,
                EnvClass) -> float:
    """
    Run one episode and return the final score (strictly in (0, 1)).
    Always emits [START] … [STEP]* … [END], even on exception.
    """
    log_start(task=task_name, env_name=benchmark, model=MODEL_NAME)

    env = EnvClass()
    rewards: list[float] = []
    steps_taken = 0
    score = 0.0
    success = False

    try:
        obs = env.reset()
        obs_dict = obs.model_dump()

        for step in range(1, MAX_STEPS + 1):
            if obs_dict.get("done", False):
                break

            action_dict = get_llm_action(client, obs_dict, step)
            action_label = (
                f"{action_dict['action_type']}('{action_dict['target_service']}')"
            )

            try:
                from models import SREAction
            except ImportError:
                try:
                    from server.models import SREAction  # type: ignore
                except ImportError:
                    # Inline fallback: just import from known path
                    import importlib, sys as _sys
                    _sys.path.insert(0, os.path.dirname(__file__))
                    _m = importlib.import_module("models")
                    SREAction = _m.SREAction

            action_obj = SREAction(**action_dict)
            obs = env.step(action_obj)
            obs_dict = obs.model_dump()

            reward = float(obs_dict.get("reward", 0.0))
            done   = bool(obs_dict.get("done", False))
            error  = obs_dict.get("last_action_error", None)  # null if none

            rewards.append(reward)
            steps_taken = step

            log_step(step=step, action=action_label, reward=reward,
                     done=done, error=error)

            if done:
                break

        # Compute final normalised score strictly in (0, 1)
        if rewards:
            raw_score = max(rewards)   # best single-step reward (already in 0-1)
        else:
            raw_score = 0.0

        # Clamp to (0.001, 0.999) so it is NEVER exactly 0.0 or 1.0
        score = round(max(0.001, min(raw_score, 0.999)), 3)
        success = score >= SUCCESS_SCORE_THRESHOLD

    except Exception as exc:
        print(f"[DEBUG] Episode error in {task_name}: {type(exc).__name__}: {exc}",
              flush=True)
        score = 0.001   # minimum valid score
        success = False

    finally:
        try:
            env.close()
        except Exception:
            pass
        log_end(success=success, steps=steps_taken, score=score, rewards=rewards)

    return score


# ---------------------------------------------------------------------------
# Main — runs all 3 tasks sequentially
# ---------------------------------------------------------------------------
def main() -> None:
    client = OpenAI(api_key=API_KEY, base_url=API_BASE_URL)
    tasks = _load_tasks()

    all_scores: list[float] = []
    for task_name, benchmark, EnvClass in tasks:
        score = run_episode(client, task_name, benchmark, EnvClass)
        all_scores.append(score)

    # Summary line (not part of the official format, but useful in logs)
    avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
    print(f"[SUMMARY] tasks={len(all_scores)} avg_score={avg:.3f} "
          f"scores={','.join(f'{s:.3f}' for s in all_scores)}", flush=True)


if __name__ == "__main__":
    main()

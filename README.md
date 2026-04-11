---
title: SRE Triage Bot
emoji: 🤖
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# Cloud SRE Triage Environment

An OpenEnv RL environment simulating real-world Site Reliability Engineering
incident triage. An AI agent must diagnose and resolve cloud infrastructure
incidents by choosing remediation actions.

---

## Environment Description

The environment models a multi-service cloud system under incident conditions.
The agent observes alert summaries and service statuses, then selects actions
to resolve the incident as efficiently as possible.

**Domain:** Cloud / DevOps / SRE  
**Framework:** OpenEnv (openenv-core)  
**Inference API:** HuggingFace Router (OpenAI-compatible)

---

## Action Space

| `action_type`     | Description                                      |
|-------------------|--------------------------------------------------|
| `check_logs`      | Inspect logs for a target service                |
| `restart_service` | Restart a target service                         |
| `scale_up`        | Increase replica count for a target service      |
| `rollback_deploy` | Roll back the most recent deployment             |
| `page_oncall`     | Escalate to on-call engineer                     |
| `no_op`           | Take no action this step                         |

`target_service` is one of: `api`, `database`, `cache`, `worker`

---

## Observation Space

| Field                | Type    | Description                                  |
|----------------------|---------|----------------------------------------------|
| `alert_summary`      | string  | Active alert descriptions                    |
| `service_statuses`   | dict    | Map of service → status string               |
| `step_count`         | int     | Current step number                          |
| `last_action_result` | string  | Result of the previous action                |
| `incident_resolved`  | bool    | Whether the incident is fully resolved       |
| `hint`               | string  | Optional guidance for the agent              |
| `done`               | bool    | Episode termination flag                     |
| `reward`             | float   | Step reward in (0, 1)                        |

---

## Tasks

### Task 1 — `sre-triage-easy` (Easy)
**Scenario:** A single API gateway is returning 5xx errors.  
**Objective:** Identify and restart the correct service.  
**Max steps:** 5  
**Optimal score:** ~0.88 (restart in step 1)

### Task 2 — `sre-triage-medium` (Medium)
**Scenario:** Database connection pool exhaustion causes cascading failures
across API and worker services.  
**Objective:** Diagnose root cause via log inspection, then remediate the database.  
**Max steps:** 6  
**Optimal score:** ~0.85 (diagnose + fix in 2 steps)

### Task 3 — `sre-triage-hard` (Hard)
**Scenario:** A bad deployment triggers a cascading failure:
memory leak → cache stampede → database saturation → circuit breaker open.  
**Objective:** Multi-step resolution: rollback deploy → restart cache → restart database.  
**Max steps:** 8  
**Optimal score:** ~0.90 (correct 3-step sequence)

---

## Reward Function

- Per-step rewards reflect quality of the action (diagnostic vs remediation, correct service)
- Partial credit is awarded for useful diagnostic steps
- Final episode score is normalised to strictly `(0, 1)` — never exactly `0.0` or `1.0`
- Faster resolution yields higher scores via a step-efficiency bonus

---

## Setup & Usage

### Environment Variables (set as HF Space secrets)

```
HF_TOKEN        Your Hugging Face API key
API_BASE_URL    LLM endpoint (default: https://router.huggingface.co/v1)
MODEL_NAME      Model identifier (default: Qwen/Qwen2.5-72B-Instruct)
SRE_TASK        Which task to serve: easy | medium | hard (default: easy)
```

### Run Locally

```bash
# Install dependencies
pip install openenv-core openai fastapi uvicorn pydantic

# Start server (serves easy task by default)
uvicorn server.app:app --host 0.0.0.0 --port 7860

# Run inference against all 3 tasks
python inference.py
```

### Run with Docker

```bash
docker build -t sre-triage-env .
docker run -p 7860:7860 \
  -e HF_TOKEN=your_key \
  -e API_BASE_URL=https://router.huggingface.co/v1 \
  -e MODEL_NAME=Qwen/Qwen2.5-72B-Instruct \
  sre-triage-env
```

### Validate

```bash
openenv validate
```

---

## Baseline Scores

| Task            | Model                    | Score  |
|-----------------|--------------------------|--------|
| sre-triage-easy | Qwen2.5-72B-Instruct     | ~0.72  |
| sre-triage-medium | Qwen2.5-72B-Instruct   | ~0.55  |
| sre-triage-hard | Qwen2.5-72B-Instruct     | ~0.38  |

---

## Team
Vikranth Jakkoju's team — CBIT  
Meta PyTorch × Scaler School of Technology OpenEnv Hackathon, Round 1

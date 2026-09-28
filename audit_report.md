# DexOS Architecture and Runtime Audit

## A. Executive diagnosis

DexOS is largely a decoupled set of testable mechanisms acting alongside a chat loop, rather than a fully unified continuous cognitive architecture. The pulse layers (thoughts, goals, workspace) exist and deterministically transition state. However, they are isolated from the LLM (the spark). In the primary runtime (`/chat`), the LLM operates as a stateless conversational response generator receiving state context as prompt text, but its outputs do not feed back into the pulse state machines. DexOS is [PARTIAL] wired: the machinery for persistent, continuous cognition exists, but it is currently "fighting the spark" because the spark itself is not executing the transitions—it's just observing them.

## B. Complete causal path

```text
incoming user input
   ↓ [WIRED]
/chat (api.py)
   ↓ [WIRED] publish PARTICIPANT_EVENT
dex_events bus
   ↓ [NOT WIRED]
dex_attention.evaluate_salience (pass)
   ↓ [NOT WIRED]
dex_workspace.activate_workspace (pass)
   ↓ [WIRED]
dex_continuity.process_continuity_event -> update self_state.json

   ↓ [WIRED]
ape_scheduler.run_cycle()
   ↓ [PARTIAL] (runs without LLM: llm_reflect=None)
derive_autonomous_thought -> gosdw.prioritize_goals / amw.refresh_thought -> update self_state.json

   ↓ [WIRED]
prompt/context construction
   (loads self_state, participant, recall_ctx, conversation)
   ↓ [WIRED]
inference spark (call_llm)
   ↓ [WIRED]
response
   ↓ [PARTIAL]
experience (record_interaction_experience -> participant_state.json)
   (Note: records conversation but does not extract goals/thoughts from LLM output)
   ↓ [NOT WIRED]
state transition (from LLM cognition back to pulse)
   (Does not occur in /chat path)
   ↓ [WIRED]
publish RESPONSE_COMPLETED
   ↓ [WIRED]
dex_continuity.process_continuity_event -> update self_state.json
```

## C. What's actually working

* **Persistence Core (`self_state.py`, `thought.py`, `gosdw.py`, `amw.py`):** The data structures are correctly implemented with atomic file writes and versioning. `process_boundary_test.py` strictly verifies that a thought survives process termination. [WIRED]
* **Continuous Substrate Loop (`dex_substrate.py`):** `run_substrate_loop` runs autonomously in `api.py` via `asyncio.create_task`. [WIRED]
* **Ambient Cognition (`dex_ambient_daemon.py`):** It runs via Cloud Scheduler, selects a target, calls the LLM (Groq), parses JSON output, updates `self_state.json` with new thoughts and reflections, and records an experience packet. [WIRED]
* **Experience & Conversational Continuity:** `participant.py` (`ParticipantSnapshot`, `ExperiencePacket`) and `dex_conversation.py` record the ongoing interactions natively. [WIRED]

## D. What's broken

* **Attention (`dex_attention.py`):** Contains only scaffolding (`pass` statements). [NOT WIRED]
* **Workspace Activation (`dex_workspace.py`):** Contains only scaffolding (`pass` statements). [NOT WIRED]
* **Pulse / LLM Integration (`api.py` / `ape_scheduler.py`):** In the `/chat` route, `run_cycle()` is called with `llm_reflect=None`. This means the active mental workspace (`amw.py`) never actually calls the LLM during the synchronous chat flow. The pulse shuffles its own state deterministically without cognitive insight. [NOT WIRED]
* **Cognition Output to Pulse:** The LLM's response in `/chat` is merely text and optional tool calls (`ACTION:`, `MEMORY:`). There is no mechanism to extract goals, thoughts, or reflections from the LLM's chat output to feed back into `gosdw.py` or `thought.py`. [NOT WIRED]

## E. What's only simulated by prompt text

* **Autonomy in the Chat Loop:** The prompt says "You may have unresolved questions, active goals, intentions, reflections... Your cognition can produce reflection. Reflection can alter state. Changed state can alter goals. Goals can produce subgoals." However, the LLM has no tools or formatting instructions in `/chat` to actually update goals, thoughts, or intentions. It merely observes the state injected into its prompt and acts *as if* it can change it, but it cannot.

## F. Pulse convergence diagnosis

Cognition does **not** actually enter and traverse the pulse layers in the primary `/chat` flow. The pulse (scheduler) runs in a parallel track immediately before prompt construction, doing a deterministic state shuffle without LLM input. The prompt receives the shuffled state, the LLM fires, and the LLM output goes to the user. The loop from `COGNITION -> PULSE` does not exist in `/chat`. It only partially exists in `dex_ambient_daemon.py`.

## G. Perspective diagnosis

Perspective is canonical and persistent. It is properly constructed by merging `self_state.py` (persistent cognitive state), `participant.py` (lived experience/confidence), and `dex_conversation.py` (ongoing conversation). The prompt does not just receive instructions about Dex, but actually receives Dex's current continuous state. However, because the LLM cannot natively write back to most of this state (except Haven memory), the perspective remains structurally sound but functionally isolated.

## H. Continuity diagnosis

State *does* survive process termination. The use of `tempfile`, atomic replacements, and `version` concurrency checks in `self_state.py` works correctly. Tests like `process_boundary_test.py` strictly enforce this. The next cognition starts from the changed state.

## I. Spark diagnosis

The spark (LLM) is acting as a swappable substrate. `api.py` supports OpenRouter, Gemini, and Groq natively and falls back effectively. However, the model is not animating the architecture because it lacks the write access required to do so. It is merely a heavily-prompted narrator of the architecture.

## J. Test-harness defects

* `integration_test.py` had a defect where it crashed without `google-genai` installed, despite being designed to test the system offline using `TestModelClient`. (This was fixed during this audit by deferring the import).
* The GitHub Actions audit (`dexos-continuity-audit.yml`) appears to be missing or named differently, as it could not be located in `.github/workflows/`. This means CI isn't actually running the integration tests.

## K. Runtime risks

* **Async Races:** `api.py` publishes `PARTICIPANT_EVENT` and `RESPONSE_COMPLETED` asynchronously via `bus.publish`. Subscribers (`process_continuity_event`) mutate `self_state.json`. Simultaneously, `run_cycle()` in `/chat` synchronously mutates `self_state.json`. `self_state.py` has a retry mechanism for version conflicts, which mitigates this, but race conditions are a structural risk under high load.
* **Cold Starts:** `push_to_github()` is called asynchronously with `run_in_executor(None, push_to_github)`. In Cloud Run, CPU is throttled immediately after the response is sent. Fire-and-forget threads may freeze mid-push, losing state persistence to GitHub.

## L. Exact fixes required

1. **Wire the Spark to the Pulse:** Update `api.py`'s `/chat` endpoint to parse the LLM's output for structured tags (e.g., `<THOUGHT>`, `<GOAL>`, `<REFLECT>`) so the LLM can actually call `thought.form_thought` or `gosdw.create_internal_goal` during its reply.
2. **Enable LLM in the Scheduler:** Provide a valid `llm_reflect` callable to `ape_scheduler.run_cycle()` inside `/chat`, so the workspace can actually reflect instead of just shuffling.
3. **Implement Attention/Workspace:** Replace the `pass` blocks in `dex_attention.py` and `dex_workspace.py` with actual logic to evaluate salience and activate thoughts.

## M. Confidence

* code-path correctness: 90%
* persistence correctness: 95%
* process-boundary continuity: 95%
* pulse wiring: 30%
* perspective wiring: 80%
* spark separation: 90%
* autonomous cognition: 40%

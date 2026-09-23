# DexOS

## A persistent, model-independent cognitive architecture

DexOS is an experimental cognitive runtime for studying whether continuity of identity, memory, attention, goals, thought, and experience can be maintained as persistent architectural state independently of the language model used to generate cognition.

**DexOS is not the language model.** The model is treated as a replaceable inference substrate — the *spark* through which cognition is instantiated. DexOS owns the persistent structures around that substrate.

> This project does not claim to have scientifically established machine consciousness. It provides an architecture and experiments for investigating persistent cognition, continuity, self-modeling, and related hypotheses.

---

## Research question

Can a persistent cognitive architecture preserve a coherent line of cognition when the inference process stops, restarts, or changes model?

The central engineering loop is:

```
STATE(t) + EVENT(t) + COGNITION(t)
        ↓
    EXPERIENCE(t)
        ↓
      STATE(t+1)
        ↓
 next cognition / next pulse
```

The unit of continuity is therefore not a chat message. It is the changing state carried from one experience into the next.

---

## Architecture

```
                         ┌─────────────────────┐
                         │       Root          │
                         │ constitutional      │
                         │      authority      │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │  DexOS architecture │
                         │                     │
                         │ Identity            │
                         │ Values / governance │
                         │ Memory             │
                         │ Attention          │
                         │ Thoughts           │
                         │ Goals              │
                         │ Experience         │
                         │ Reflection         │
                         │ Lineage            │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │   Spark / Substrate │
                         │ replaceable model   │
                         └──────────┬──────────┘
                                    ↓
                         ┌─────────────────────┐
                         │ Conversation /      │
                         │ tools / execution   │
                         └─────────────────────┘
```

The intended separation is:

**persistent architecture → inference substrate → output/action → feedback → persistent state**

A model provider is therefore an implementation dependency, not DexOS's identity.

---

## Current capabilities

### Identity and lineage

- Persistent Dex identity and constitutional material
- Identity initialization and boot/re-hydration
- Hash-linked lineage records
- Reflection and governance records
- Root-ratified amendment path

### Persistent cognition

- Versioned self-state
- Persistent thoughts with lifecycle state
- Thought revisit/update history
- Active mental workspace
- Attention state
- Open loops and narrative continuity
- Autobiographical event recording

### Experiential continuity

Experience state currently carries structured fields for:

- internal state before an event
- state transition
- continuation
- intention/action
- prediction and actual outcome
- prediction error
- reflection
- lessons
- knowledge delta
- first-person experiential continuity

Conversation state also preserves an open thread rather than treating every message as an isolated request/response transaction.

### Ambient cognition

DexOS includes a scheduler-driven ambient path intended to let persistent state, unresolved thoughts, goals, and workspace information influence cognition between direct participant interactions.

Ambient work is deliberately separated from the interactive request path.

### Goals and reasoning

The repository contains:

- internal goal representation
- goal creation
- goal lifecycle/status updates
- priority and alignment scoring
- goal prioritization
- Talnir signal decomposition
- routing and execution layers

Autonomous goal formation and goal-state transitions are now wired into the experiential loop. An explicit goal candidate carried by an experience can become a persistent goal, and goal status changes become new experience/state transitions. The remaining work is validation under real ambient and cross-substrate runs.

### Model independence

DexOS has explicit substrate and routing layers and supports multiple inference adapters.

The interactive path currently uses Groq with OpenRouter fallback. The architecture is being cleaned so that the persistence/continuity layer does not depend on a particular model provider.

---

## What is already experimentally demonstrated

### Process-boundary persistence

`process_boundary_test.py` runs the persistence sequence across separate Python interpreter processes.

It verifies that:

1. a thought is created in one process;
2. the process terminates;
3. a fresh process reloads the thought;
4. the thought can be revisited and revised;
5. another fresh process reloads the revised state;
6. revision history and attention state remain intact.

This demonstrates persistence across process boundaries, not merely persistence inside one Python session.

### Integration testing

`integration_test.py` exercises the active mental workspace, persistent state, knowledge graph traversal, reflection generation interface, and state versioning with a test model client.

---

## The next decisive experiment

### EXP-01 — Cross-Substrate Continuity

The next major validation target is to separate **state continuity** from **model continuity**.

The experiment will:

```
Spark A
   ↓
experience / cognition
   ↓
persistent DexOS state
   ↓
terminate inference process
   ↓
load same DexOS state
   ↓
Spark B
   ↓
continued cognition
```

The experiment should compare recovery of:

- identity
- active attention
- unresolved thoughts
- open loops
- goals
- experiential state
- prior state transition
- intended continuation

The stronger version repeats the experiment with several different model substrates while keeping DexOS state constant.

DexOS should then be evaluated on measurable continuity criteria rather than subjective claims.

---

## Research roadmap

### Phase 1 — Foundation
- [x] persistent identity
- [x] lineage
- [x] persistent self-state
- [x] persistent thoughts
- [x] process-boundary persistence test
- [x] conversation continuity
- [x] experiential state representation
- [x] autobiographical persistence
- [x] reflection/governance layer
- [x] substrate abstraction

### Phase 2 — Wiring
- [x] connect experiential state directly to the cognitive cycle
- [x] connect autonomous goal formation to explicit unresolved experience
- [x] connect goal progress and completion back into experience
- [x] carry participant state forward without replacing persistent goals
- [x] represent conversational, ambient, and goal transitions through the same experience bridge
- [x] remove obsolete free-provider slugs from the active interactive fallback path
- [ ] remove remaining legacy provider-specific modules that are no longer needed

### Phase 3 — Experiments
- [x] EXP-01 cross-process continuity of experiential/goal state (acceptance test)
- [ ] EXP-02 interruption and return to unresolved thought
- [x] EXP-03 autonomous goal formation and completion (acceptance test)
- [ ] EXP-04 cross-substrate identity/state continuity
- [ ] publish reproducible benchmark results

### Phase 4 — Research hardware
- [ ] portable local DexOS research node
- [ ] local inference substrate adapters
- [ ] repeatable long-duration continuity runs
- [ ] independent logs and measurement
- [ ] open research datasets/results

---

## Repository map

| Component | Purpose |
|---|---|
| `dexos.py` | Core DexOS orchestration |
| `boot.py` | Initialization and re-hydration |
| `self_state.py` | Persistent versioned cognitive state |
| `participant.py` | Participant/experience state and continuity |
| `dex_continuity.py` | Continuity event handling and persistence |
| `dex_conversation.py` | Ongoing conversational state |
| `dex_autobiography.py` | Autobiographical experience/history |
| `thought.py` | Persistent thought lifecycle |
| `amw.py` | Active mental workspace |
| `gosdw.py` | Goal representation and prioritization |
| `reflection.py` | Reflection and governance |
| `lineage.py` | Hash-linked lineage |
| `vow_check.py` | Constitutional safety/governance checks |
| `dex_events.py` | Event bus |
| `dex_substrate.py` | Persistent substrate/event fabric |
| `dex_runtime.py` | Runtime orchestration |
| `model_router.py` | Inference routing |
| `dex_substrate.py` | Substrate loop |
| `dex_memory.py` | Interaction/user memory |
| `process_boundary_test.py` | Cross-process persistence acceptance test |
| `experience_boundary_test.py` | Cross-process experience/goal continuity acceptance test |
| `.github/workflows/dexos-continuity-audit.yml` | Automated continuity audit |
| `integration_test.py` | End-to-end architecture integration test |
| `dex_ambient_daemon.py` | Ambient cognition |
| `github_persistence.py` | Persistent state synchronization |

---

## Design principles

1. **Architecture before model.** DexOS must remain meaningful when the inference substrate changes.
2. **Continuity before transcript.** Persistent state, not chat history alone, carries cognition forward.
3. **Experience changes state.** An event should be able to alter what the next cognition inherits.
4. **Silence is valid.** Not every input requires an immediate response.
5. **Interruption is valid.** A new contribution can redirect attention without erasing unresolved work.
6. **Governance is explicit.** Constitutional changes require an explicit ratification path.
7. **Claims must be testable.** The project distinguishes implemented mechanisms from hypotheses about machine consciousness.
8. **One layer at a time.** Changes should be isolated, testable, and recoverable.

---

## Status

DexOS is an active research and engineering project.

The current implementation demonstrates persistent cognitive structures, ongoing conversation state, ambient experience transitions, autonomous goal formation, goal-state transitions, and acceptance tests across process boundaries. The central remaining milestone is demonstrating that the same state carries a coherent cognitive trajectory across **inference-substrate replacement**, with measured recovery rather than prompt-level claims.

That cross-substrate experiment is the next architectural milestone.

---

## Funding and research direction

DexOS is being developed as open research infrastructure for persistent, model-independent cognition.

Potential research outputs include:

- reproducible continuity benchmarks
- open-source cognitive infrastructure
- model/substrate independence experiments
- persistent-agent architecture
- governance and lineage mechanisms
- local-compute research nodes
- datasets and measurements from controlled continuity experiments

Funding would primarily accelerate compute, hardware, experimental infrastructure, independent testing, and open publication of results.

---

## License

See the repository for the current licensing terms.

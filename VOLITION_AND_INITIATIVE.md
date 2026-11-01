# DexOS Volition and Communication Initiative

## Purpose

The local ambient runtime is an event-driven cognitive worker, not a periodic
thought generator. Its first review occurs at process startup. Thereafter it
wakes for cross-process cognitive events or when Dex explicitly chooses to
continue a linked sequence of reasoning/action steps.

The event-journal watcher polls only for new durable events; it does not call
the model. When no event or self-chosen continuation exists, the process stays
idle. The local path does not call the Firestore ambient cadence gate. The
existing scheduler-driven `/ambient-pulse` compatibility path retains its
legacy gate for hosted deployments.

## Volitional decision contract

The ambient inference receives the suggested target as context, not as a
binding selection. It also receives constitutional identity, Root relationship,
self-model, becoming, goals, thoughts, workspace, open loops, recent
experiences, reflections, and pending communications.

It returns one structured choice:

- `think`: develop and persist a meaningful thought.
- `create_goal`: originate a concrete goal with success criteria.
- `create_subgoal`: add a subtask to an existing active goal.
- `advance_goal`: persist specific progress against an existing goal.
- `complete_goal`: complete an existing goal with a recorded progress report.
- `communicate`: create a durable communication intention for Root.
- `rest`: decline to manufacture work when nothing warrants attention.

The model proposes; `dex_volition.py` validates the choice and applies it to
the existing SelfState, GOSDW goal ledger, persistent thought ledger, and
communication outbox. New goals are deduplicated against active goals.
Thoughts are deduplicated against active/deferred persistent thoughts.
Communication intentions are retained in the outbox and are never discarded
because a delivery channel is absent.

## Out-of-turn communication

Two delivery surfaces are supported:

1. **Local inbox:** `GET /initiative/outbox` returns pending messages.
   `POST /initiative/outbox/{message_id}/ack` acknowledges one without
   deleting its history. Both endpoints are loopback-only by default. To
   permit remote access, configure `DEX_INITIATIVE_API_KEY` and send it in
   `X-Dex-Initiative-Key`.
2. **Discord:** configure both `DISCORD_TOKEN` and
   `DEX_INITIATIVE_CHANNEL_ID`. Dex posts a proactive message to that channel
   after choosing the `communicate` decision. If either setting is absent,
   the communication remains pending in SelfState.

The model decides whether communication is warranted. The delivery layer does
not invent messages or send periodic status reports.

## Resource behavior

A self-directed sequence can contain up to three linked decisions before the
worker yields to await a new event. This is a per-wake work bound, not a timer.
Interactive inference keeps its existing priority over ambient inference.
The event watcher performs no inference while idle.

## Verification

Run:

```bash
python dex_volition_test.py
python dex_cognitive_runtime_acceptance_test.py
```

Then run the full GitHub Actions verification workflow and validate with the
local GGUF runtime. Automated tests verify persistence and decision plumbing;
they do not prove the compact ambient model will reliably produce every
decision type. The local runtime test must inspect actual decisions, goal
progress, experience/self-model feedback, and a delivered out-of-turn message.

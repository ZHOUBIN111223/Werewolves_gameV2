# Summary Memory System

## Goal

Reduce memory pollution from raw event accumulation and make cross-game comparison experiments easier.

## Runtime Layout

Each agent now keeps two memory files:

- `memory.json`: long-term reusable memory only.
  - Stores post-game `strategy_rule` style reflections.
  - Also stores anti-patterns extracted from failed games.
- `summary_memory.json`: current-game and per-game summary memory.
  - Stores rolling phase summaries.
  - Stores key facts, role claims, open questions, and recent speeches.

## Design

### Long-term memory

Long-term memory should only keep information that can transfer across games:

- reusable strategy rules
- role-specific heuristics
- anti-patterns to avoid

It should not store raw per-game factual event streams.

### Short-term memory

Short-term memory is summary-first and game-scoped:

- current request focus
- alive-player summary
- key claims and hard facts
- recent phase summaries
- recent speeches

Prompt construction reads only the current game's summary memory plus long-term strategy rules.

## Why this is safer

- avoids mixing raw factual notes across games
- reduces prompt bloat from full observation history
- keeps long-term evolution focused on reusable behavior rather than noisy logs

## Comparison Experiments

The old implementation was archived in:

- `docs/experiments/memory_system_baseline_20260327/`

Use that snapshot as the baseline when comparing:

- win rate
- role-specific accuracy
- rule adherence
- prompt token usage
- reflection quality

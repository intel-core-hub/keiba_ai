# Production Readiness Evaluation

- readiness score: 87.11/100
- production modules checked: 64
- production modules ready: 58
- circular dependencies: 0
- shadow wrappers: 9
- risky production modules: simulation.live_simulation, main, core.auto_operator, validation.walk_forward_validation, infrastructure.api_server, execution.phase2_loop

## Interpretation

The production path is partially isolated but still carries research leakage via top-level entrypoints and shadow wrappers.
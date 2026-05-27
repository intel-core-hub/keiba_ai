# Migration Plan

1. Freeze production imports behind the new `production` boundary.
2. Quarantine research-only modules under the `research` boundary.
3. Remove or lazy-load production entrypoints that currently import research code.
4. Replace shadow wrappers with single-source modules or explicit facades.
5. Add dependency checks to CI for production modules.

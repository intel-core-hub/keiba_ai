"""Production scheduler entrypoint.

The dashboard never imports or starts this module. Run it as a separate
process when operating Survival OS.
"""

from core.execution.scheduler import SurvivalScheduler


def main() -> None:
    scheduler = SurvivalScheduler()
    print(scheduler.diagnostics())
    scheduler.run_forever()


if __name__ == "__main__":
    main()

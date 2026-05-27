# core/state_manager.py

import os
import json
import pickle

from datetime import datetime


class StateManager:
    """
    Persistence Layer

    目的:
    - state persistence
    - restart recovery
    - historical continuity
    - long-term survival

    最重要:
    「再起動しても記憶を失わない」
    """

    def __init__(

        self,

        state_dir="state",
    ):

        self.state_dir = (
            state_dir
        )

        os.makedirs(

            self.state_dir,

            exist_ok=True,
        )

    # =================================================
    # Paths
    # =================================================

    def json_path(
        self,
        name,
    ):

        return os.path.join(

            self.state_dir,

            f"{name}.json"
        )

    def pickle_path(
        self,
        name,
    ):

        return os.path.join(

            self.state_dir,

            f"{name}.pkl"
        )

    # =================================================
    # JSON Save
    # =================================================

    def save_json(

        self,

        name,
        data,
    ):

        payload = {

            "saved_at":
                datetime.utcnow()
                .isoformat(),

            "data":
                data,
        }

        path = self.json_path(
            name
        )

        with open(

            path,

            "w",

            encoding="utf-8",
        ) as f:

            json.dump(

                payload,

                f,

                ensure_ascii=False,

                indent=2,
            )

        print(
            f"[STATE SAVED] "
            f"{path}"
        )

        return path

    # =================================================
    # JSON Load
    # =================================================

    def load_json(
        self,
        name,
        default=None,
    ):

        path = self.json_path(
            name
        )

        if not os.path.exists(
            path
        ):

            return default

        try:

            with open(

                path,

                "r",

                encoding="utf-8",
            ) as f:

                payload = json.load(
                    f
                )

            return payload.get(
                "data",
                default,
            )

        except Exception as e:

            print(
                "[LOAD JSON ERROR]",
                e,
            )

            return default

    # =================================================
    # Pickle Save
    # =================================================

    def save_pickle(

        self,

        name,
        obj,
    ):

        path = self.pickle_path(
            name
        )

        with open(
            path,
            "wb",
        ) as f:

            pickle.dump(
                obj,
                f,
            )

        print(
            f"[PICKLE SAVED] "
            f"{path}"
        )

        return path

    # =================================================
    # Pickle Load
    # =================================================

    def load_pickle(
        self,
        name,
        default=None,
    ):

        path = self.pickle_path(
            name
        )

        if not os.path.exists(
            path
        ):

            return default

        try:

            with open(
                path,
                "rb",
            ) as f:

                obj = pickle.load(
                    f
                )

            return obj

        except Exception as e:

            print(
                "[LOAD PICKLE ERROR]",
                e,
            )

            return default

    # =================================================
    # Save Regime State
    # =================================================

    def save_regime(
        self,
        detector,
    ):

        data = {

            "current_regime":
                detector.current_regime,

            "previous_regime":
                detector.previous_regime,

            "history":
                detector.regime_history,
        }

        return self.save_json(

            "regime_state",

            data,
        )

    # =================================================
    # Load Regime State
    # =================================================

    def load_regime(
        self,
        detector,
    ):

        data = self.load_json(
            "regime_state"
        )

        if not data:
            return detector

        detector.current_regime = (
            data.get(
                "current_regime",
                "NORMAL",
            )
        )

        detector.previous_regime = (
            data.get(
                "previous_regime",
                "NORMAL",
            )
        )

        detector.regime_history = (
            data.get(
                "history",
                [],
            )
        )

        return detector

    # =================================================
    # Save Orchestrator
    # =================================================

    def save_orchestrator(
        self,
        orchestrator,
    ):

        data = {

            "cycle_count":
                orchestrator.cycle_count,

            "last_cycle":
                orchestrator.last_cycle,

            "last_error":
                orchestrator.last_error,

            "shutdown":
                orchestrator.shutdown,

            "health_history":
                orchestrator.health_history,
        }

        return self.save_json(

            "orchestrator_state",

            data,
        )

    # =================================================
    # Load Orchestrator
    # =================================================

    def load_orchestrator(
        self,
        orchestrator,
    ):

        data = self.load_json(
            "orchestrator_state"
        )

        if not data:
            return orchestrator

        orchestrator.cycle_count = (
            data.get(
                "cycle_count",
                0,
            )
        )

        orchestrator.last_cycle = (
            data.get(
                "last_cycle"
            )
        )

        orchestrator.last_error = (
            data.get(
                "last_error"
            )
        )

        orchestrator.shutdown = (
            data.get(
                "shutdown",
                False,
            )
        )

        orchestrator.health_history = (
            data.get(
                "health_history",
                [],
            )
        )

        return orchestrator

    # =================================================
    # Save Simulation State
    # =================================================

    def save_simulation(
        self,
        simulation,
    ):

        data = {

            "bankroll":
                simulation.bankroll,

            "peak_bankroll":
                (
                    simulation
                    .peak_bankroll
                ),

            "trade_count":
                simulation.trade_count,

            "skip_count":
                simulation.skip_count,

            "shutdown":
                simulation.shutdown,

            "current_regime":
                (
                    simulation
                    .current_regime
                ),

            "equity_curve":
                (
                    simulation
                    .equity_curve
                ),
        }

        return self.save_json(

            "simulation_state",

            data,
        )

    # =================================================
    # Load Simulation State
    # =================================================

    def load_simulation(
        self,
        simulation,
    ):

        data = self.load_json(
            "simulation_state"
        )

        if not data:
            return simulation

        simulation.bankroll = (
            data.get(
                "bankroll",
                simulation.bankroll,
            )
        )

        simulation.peak_bankroll = (
            data.get(
                "peak_bankroll",
                simulation.peak_bankroll,
            )
        )

        simulation.trade_count = (
            data.get(
                "trade_count",
                0,
            )
        )

        simulation.skip_count = (
            data.get(
                "skip_count",
                0,
            )
        )

        simulation.shutdown = (
            data.get(
                "shutdown",
                False,
            )
        )

        simulation.current_regime = (
            data.get(
                "current_regime",
                "NORMAL",
            )
        )

        simulation.equity_curve = (
            data.get(
                "equity_curve",
                [],
            )
        )

        return simulation

    # =================================================
    # Save Generic Object
    # =================================================

    def save_object(

        self,

        name,
        obj,
    ):

        return self.save_pickle(
            name,
            obj,
        )

    # =================================================
    # Load Generic Object
    # =================================================

    def load_object(
        self,
        name,
        default=None,
    ):

        return self.load_pickle(
            name,
            default,
        )

    # =================================================
    # Snapshot
    # =================================================

    def snapshot(
        self,
        orchestrator=None,
        detector=None,
        simulation=None,
    ):

        print("\n====================")
        print("STATE SNAPSHOT")
        print("====================")

        if detector:

            self.save_regime(
                detector
            )

        if orchestrator:

            self.save_orchestrator(
                orchestrator
            )

        if simulation:

            self.save_simulation(
                simulation
            )

        print(
            "[SNAPSHOT COMPLETE]"
        )

    # =================================================
    # Restore
    # =================================================

    def restore(

        self,

        orchestrator=None,
        detector=None,
        simulation=None,
    ):

        print("\n====================")
        print("STATE RESTORE")
        print("====================")

        if detector:

            detector = (
                self.load_regime(
                    detector
                )
            )

        if orchestrator:

            orchestrator = (
                self.load_orchestrator(
                    orchestrator
                )
            )

        if simulation:

            simulation = (
                self.load_simulation(
                    simulation
                )
            )

        print(
            "[RESTORE COMPLETE]"
        )

        return {

            "orchestrator":
                orchestrator,

            "detector":
                detector,

            "simulation":
                simulation,
        }

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        files = []

        if os.path.exists(
            self.state_dir
        ):

            files = os.listdir(
                self.state_dir
            )

        return {

            "state_dir":
                self.state_dir,

            "files":
                files,

            "count":
                len(files),
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    manager = (
        StateManager()
    )

    manager.save_json(

        "test_state",

        {
            "survival": 0.91,
            "regime": "NORMAL",
        }
    )

    state = manager.load_json(
        "test_state"
    )

    print(state)

    print(
        manager.diagnostics()
    )
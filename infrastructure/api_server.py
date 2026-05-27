# infrastructure/api_server.py

import os
import uvicorn

from datetime import datetime
from typing import Dict, Any

from fastapi import (
    FastAPI,
    HTTPException,
)

from pydantic import BaseModel

from core.executive_controller import (
    ExecutiveController
)

from core.state_manager import (
    StateManager
)

from core.alert_manager import (
    AlertManager
)

from core.audit_logger import (
    AuditLogger
)

ENABLE_RESEARCH = os.getenv("KEIBA_ENABLE_RESEARCH", "0") == "1"


class _NullStrategyEvolver:
    def diagnostics(self):
        return {"status": "SKIPPED", "reason": "research_disabled"}


class _NullMetaLearner:
    def diagnostics(self):
        return {"status": "SKIPPED", "reason": "research_disabled"}


if ENABLE_RESEARCH:
    from learning.strategy_evolver import (
        StrategyEvolver
    )

    from learning.meta_learner import (
        MetaLearner
    )
else:
    StrategyEvolver = _NullStrategyEvolver
    MetaLearner = _NullMetaLearner

from memory.knowledge_graph import (
    KnowledgeGraph
)


# =====================================================
# FastAPI App
# =====================================================

app = FastAPI(

    title=(
        "Survival Operating System"
    ),

    version="1.0.0",

    description=(
        "Self-Evolving Survival Infrastructure"
    ),
)


# =====================================================
# Global Systems
# =====================================================

executive = (
    ExecutiveController()
)

state_manager = (
    StateManager()
)

alerts = (
    AlertManager()
)

audit = (
    AuditLogger()
)

evolver = (
    StrategyEvolver()
)

meta = (
    MetaLearner()
)

knowledge = (
    KnowledgeGraph()
)


# =====================================================
# Request Models
# =====================================================

class MetricsRequest(
    BaseModel
):

    survival_score: float = 0.5

    volatility: float = 0.5

    drawdown: float = 0.0

    confidence: float = 0.5


class OutcomeRequest(
    BaseModel
):

    fitness: float

    result: str

    survival: float

    accuracy: float


class AlertRequest(
    BaseModel
):

    level: str

    title: str

    message: str


# =====================================================
# Root
# =====================================================

@app.get("/")
def root():

    return {

        "system":
            "Survival OS",

        "status":
            "RUNNING",

        "timestamp":
            datetime.utcnow()
            .isoformat(),
    }


# =====================================================
# Health
# =====================================================

@app.get("/health")
def health():

    return {

        "healthy":
            True,

        "shutdown":
            executive.shutdown,

        "timestamp":
            datetime.utcnow()
            .isoformat(),
    }


# =====================================================
# Executive Decision
# =====================================================

@app.post("/decision")
def decision(
    request: MetricsRequest
):

    metrics = request.dict()

    result = (
        executive.decide(
            metrics
        )
    )

    return result


# =====================================================
# Learn Outcome
# =====================================================

@app.post("/learn")
def learn(
    outcome: OutcomeRequest
):

    if not executive.last_decision:

        raise HTTPException(

            status_code=400,

            detail=(
                "no previous decision"
            ),
        )

    executive.learn_outcome(

        executive.last_decision,

        outcome.dict(),
    )

    return {

        "status":
            "LEARNED",

        "timestamp":
            datetime.utcnow()
            .isoformat(),
    }


# =====================================================
# Executive Summary
# =====================================================

@app.get("/summary")
def summary():

    return executive.summary()


# =====================================================
# Diagnostics
# =====================================================

@app.get("/diagnostics")
def diagnostics():

    return {

        "executive":
            executive.diagnostics(),

        "meta":
            meta.diagnostics(),

        "knowledge":
            knowledge.diagnostics(),
    }


# =====================================================
# State
# =====================================================

@app.get("/state")
def state():

    try:

        state = (
            state_manager.load_state()
        )

        return {

            "status":
                "OK",

            "state":
                state,
        }

    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e),
        )


# =====================================================
# Save State
# =====================================================

@app.post("/state/save")
def save_state():

    try:

        state_manager.save_state({

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "executive":
                executive.summary(),
        })

        return {

            "saved":
                True
        }

    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e),
        )


# =====================================================
# Alerts
# =====================================================

@app.post("/alerts")
def create_alert(
    request: AlertRequest
):

    alerts.emit(

        level=request.level,

        title=request.title,

        message=request.message,
    )

    return {

        "alert":
            "EMITTED"
    }


# =====================================================
# Emergency Shutdown
# =====================================================

@app.post("/shutdown")
def shutdown():

    result = (
        executive
        .emergency_shutdown(
            "api shutdown"
        )
    )

    return result


# =====================================================
# Restore
# =====================================================

@app.post("/restore")
def restore():

    result = (
        executive
        .restore_operation()
    )

    return result


# =====================================================
# Knowledge Graph
# =====================================================

@app.get("/knowledge")
def knowledge_summary():

    return {

        "diagnostics":
            knowledge.diagnostics(),

        "intelligence":
            (
                knowledge
                .survival_intelligence()
            ),

        "failures":
            (
                knowledge
                .failure_patterns()
            )[:20],
    }


# =====================================================
# Meta Recommendations
# =====================================================

@app.get("/recommendation")
def recommendation(
    regime: str = "NORMAL"
):

    return {

        "regime":
            regime,

        "recommendations":
            meta.recommend(
                regime=regime
            ),
    }


# =====================================================
# Audit Logs
# =====================================================

@app.get("/audit")
def audit_logs():

    try:

        logs = audit.load_logs()

        return {

            "count":
                len(logs),

            "logs":
                logs[-50:],
        }

    except Exception as e:

        raise HTTPException(

            status_code=500,

            detail=str(e),
        )


# =====================================================
# Evolution Trigger
# =====================================================

@app.post("/evolve")
def evolve():

    return {

        "status":
            "NOT_IMPLEMENTED",

        "message":
            (
                "dataset injection "
                "required"
            ),
    }


# =====================================================
# Runtime Info
# =====================================================

@app.get("/runtime")
def runtime():

    return {

        "mode":
            executive.executive_mode,

        "shutdown":
            executive.shutdown,

        "decision_count":
            len(
                executive
                .decision_history
            ),

        "timestamp":
            datetime.utcnow()
            .isoformat(),
    }


# =====================================================
# Config
# =====================================================

@app.get("/config")
def config():

    return {

        "min_survival":
            (
                executive
                .min_survival_score
            ),

        "max_risk":
            executive.max_risk,

        "min_confidence":
            (
                executive
                .min_confidence
            ),
    }


# =====================================================
# Startup Event
# =====================================================

@app.on_event("startup")
def startup_event():

    audit.log(

        category="SYSTEM",

        action="STARTUP",

        severity="INFO",

        metadata={

            "timestamp":
                datetime.utcnow()
                .isoformat()
        },
    )

    print(
        "[API SERVER STARTED]"
    )


# =====================================================
# Shutdown Event
# =====================================================

@app.on_event("shutdown")
def shutdown_event():

    audit.log(

        category="SYSTEM",

        action="SHUTDOWN",

        severity="WARNING",

        metadata={

            "timestamp":
                datetime.utcnow()
                .isoformat()
        },
    )

    print(
        "[API SERVER STOPPED]"
    )


# =====================================================
# Run
# =====================================================

if __name__ == "__main__":

    os.makedirs(
        "infrastructure",
        exist_ok=True,
    )

    uvicorn.run(

        "infrastructure.api_server:app",

        host="0.0.0.0",

        port=8000,

        reload=True,
    )
# core/alert_manager.py

import os
import json
import smtplib

from email.mime.text import (
    MIMEText
)

from email.mime.multipart import (
    MIMEMultipart
)

from datetime import datetime


class AlertManager:
    """
    Survival Alert System

    目的:
    - 異常通知
    - emergency awareness
    - human escalation
    - operational survival

    最重要:
    「壊れたことを伝える」
    """

    def __init__(

        self,

        log_path=(
            "logs/alerts.jsonl"
        ),
    ):

        self.log_path = log_path

        os.makedirs(
            "logs",
            exist_ok=True,
        )

        # =================================================
        # email config
        # =================================================

        self.smtp_server = os.getenv(
            "SMTP_SERVER"
        )

        self.smtp_port = int(

            os.getenv(
                "SMTP_PORT",
                587,
            )
        )

        self.smtp_user = os.getenv(
            "SMTP_USER"
        )

        self.smtp_password = os.getenv(
            "SMTP_PASSWORD"
        )

        self.alert_email = os.getenv(
            "ALERT_EMAIL"
        )

        # =================================================
        # thresholds
        # =================================================

        self.max_drawdown = 0.30

        self.min_survival_score = (
            0.35
        )

        self.allowed_regimes = {

            "NORMAL",

            "FAVORABLE",
        }

    # =================================================
    # Save Alert
    # =================================================

    def save_alert(
        self,
        alert,
    ):

        with open(

            self.log_path,

            "a",

            encoding="utf-8",
        ) as f:

            f.write(

                json.dumps(
                    alert,
                    ensure_ascii=False,
                )
                + "\n"
            )

    # =================================================
    # Build Alert
    # =================================================

    def build_alert(

        self,

        level,
        title,
        message,
        metadata=None,
    ):

        alert = {

            "timestamp":
                datetime.utcnow()
                .isoformat(),

            "level":
                level,

            "title":
                title,

            "message":
                message,

            "metadata":
                metadata or {},
        }

        return alert

    # =================================================
    # Send Email
    # =================================================

    def send_email(
        self,
        alert,
    ):

        if not all([

            self.smtp_server,

            self.smtp_user,

            self.smtp_password,

            self.alert_email,
        ]):

            print(
                "[EMAIL DISABLED]"
            )

            return False

        try:

            msg = MIMEMultipart()

            msg["From"] = (
                self.smtp_user
            )

            msg["To"] = (
                self.alert_email
            )

            msg["Subject"] = (

                f"[{alert['level']}] "
                f"{alert['title']}"
            )

            body = f"""
TIME:
{alert['timestamp']}

LEVEL:
{alert['level']}

TITLE:
{alert['title']}

MESSAGE:
{alert['message']}

METADATA:
{json.dumps(alert['metadata'], indent=2)}
"""

            msg.attach(
                MIMEText(
                    body,
                    "plain",
                )
            )

            server = smtplib.SMTP(

                self.smtp_server,

                self.smtp_port,
            )

            server.starttls()

            server.login(

                self.smtp_user,

                self.smtp_password,
            )

            server.send_message(
                msg
            )

            server.quit()

            print(
                "[EMAIL SENT]"
            )

            return True

        except Exception as e:

            print(
                "[EMAIL ERROR]",
                e,
            )

            return False

    # =================================================
    # Emit Alert
    # =================================================

    def emit(

        self,

        level,
        title,
        message,
        metadata=None,
    ):

        alert = self.build_alert(

            level=level,

            title=title,

            message=message,

            metadata=metadata,
        )

        # =================================================
        # save
        # =================================================

        self.save_alert(
            alert
        )

        # =================================================
        # email
        # =================================================

        self.send_email(
            alert
        )

        # =================================================
        # console
        # =================================================

        print("\n====================")
        print("ALERT")
        print("====================")

        print(
            json.dumps(
                alert,
                indent=2,
                ensure_ascii=False,
            )
        )

        return alert

    # =================================================
    # Survival Check
    # =================================================

    def check_survival(

        self,

        survival_score,
        drawdown,
        regime,
    ):

        # =================================================
        # collapse
        # =================================================

        if regime == "COLLAPSE":

            return self.emit(

                level="CRITICAL",

                title="REGIME COLLAPSE",

                message=(
                    "system entered "
                    "collapse regime"
                ),

                metadata={

                    "regime":
                        regime,

                    "drawdown":
                        drawdown,

                    "survival_score":
                        survival_score,
                },
            )

        # =================================================
        # drift
        # =================================================

        if regime == "DRIFT":

            return self.emit(

                level="WARNING",

                title="CALIBRATION DRIFT",

                message=(
                    "prediction "
                    "calibration degraded"
                ),

                metadata={

                    "regime":
                        regime,

                    "survival_score":
                        survival_score,
                },
            )

        # =================================================
        # low survival
        # =================================================

        if (

            survival_score
            < self.min_survival_score

        ):

            return self.emit(

                level="WARNING",

                title="LOW SURVIVAL",

                message=(
                    "survival score "
                    "below threshold"
                ),

                metadata={

                    "survival_score":
                        survival_score,

                    "drawdown":
                        drawdown,
                },
            )

        # =================================================
        # high drawdown
        # =================================================

        if drawdown > self.max_drawdown:

            return self.emit(

                level="CRITICAL",

                title="MAX DRAWDOWN",

                message=(
                    "drawdown exceeded "
                    "safe limit"
                ),

                metadata={

                    "drawdown":
                        drawdown
                },
            )

        return None

    # =================================================
    # Generic Exception Alert
    # =================================================

    def exception(
        self,
        error,
        context=None,
    ):

        return self.emit(

            level="ERROR",

            title="SYSTEM EXCEPTION",

            message=str(error),

            metadata={
                "context":
                    context or {}
            },
        )

    # =================================================
    # Recovery Alert
    # =================================================

    def recovery(
        self,
        result,
    ):

        status = result.get(
            "status",
            "UNKNOWN",
        )

        if status == "PROMOTED":

            return self.emit(

                level="INFO",

                title="MODEL RECOVERED",

                message=(
                    "new model promoted"
                ),

                metadata=result,
            )

        elif status == "REJECTED":

            return self.emit(

                level="WARNING",

                title="MODEL REJECTED",

                message=(
                    "candidate model "
                    "failed safety checks"
                ),

                metadata=result,
            )

        elif status == "ERROR":

            return self.emit(

                level="ERROR",

                title="RETRAIN FAILED",

                message=(
                    "auto retraining failed"
                ),

                metadata=result,
            )

        return None

    # =================================================
    # Diagnostics
    # =================================================

    def diagnostics(
        self,
    ):

        return {

            "smtp_enabled":
                bool(
                    self.smtp_server
                ),

            "log_path":
                self.log_path,

            "max_drawdown":
                self.max_drawdown,

            "min_survival_score":
                self.min_survival_score,
        }


# =====================================================
# Example
# =====================================================

if __name__ == "__main__":

    alerts = AlertManager()

    alerts.check_survival(

        survival_score=0.22,

        drawdown=0.41,

        regime="COLLAPSE",
    )
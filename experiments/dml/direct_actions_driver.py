"""Generate the fixed-history Quint wrapper for the two DML snapshots."""

DRIVER_MODULE = "dml_direct_actions"
DRIVER_FILE = f"{DRIVER_MODULE}.qnt"
HISTORIES = {
    4: ("stage_alternate", "publish_alternate_expected_3"),
    5: ("stage_alternate", "publish_alternate_expected_minus_2"),
}

WRAPPER = """module dml_direct_actions {{
  import recorded_return_design as dml from "./recorded_return_design"

  // Common prefix 0..3, then one distinct end phase per public history.
  var reviewPhase: int

  action init = all {{
    dml::init,
    reviewPhase' = 0,
  }}

  // Select the scheduler context, leaving the operation guards to the model.
  val hasReport = dml::event.command != ""
  val sourceReady = dml::returning and not(hasReport)

  action step = any {{
    all {{ reviewPhase == 0, not(dml::returning), dml::startReturn, reviewPhase' = 1 }},
    all {{ reviewPhase == 1, sourceReady, dml::stage(dml::alternate), reviewPhase' = 2 }},
    all {{
      reviewPhase == 2,
      // Select the original scheduler's event-clear branch, not its chooser.
      dml::returning,
      hasReport,
      dml::step,
      reviewPhase' = 3,
    }},
    all {{ reviewPhase == 3, sourceReady, {mismatch}, reviewPhase' = 4 }},
    all {{ reviewPhase == 3, sourceReady, {matching}, reviewPhase' = 5 }},
  }}
}}
"""


def render_driver(side: str) -> str:
    """Bind a common pair of public histories to the selected revision's actions."""
    if side not in ("old", "new"):
        raise ValueError(f"unknown DML snapshot side: {side}")

    def publish(factor: str) -> str:
        # OLD did not take a factor argument. Keep the two requests distinct in
        # the driver even though they invoke the same action on that snapshot.
        factor_argument = f"dml::{factor}, " if side == "new" else ""
        return f"dml::publish(dml::alternate, dml::previousMain, {factor_argument}false, 0)"

    return WRAPPER.format(mismatch=publish("plannedFactor"), matching=publish("alternateFactor"))

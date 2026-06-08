from bentlyk.actions.permissions import (
    AutonomyMode,
    GateDecision,
    RiskLevel,
    permission_gate,
)


def test_observe_only_allows_reads():
    g = permission_gate(autonomy=AutonomyMode.OBSERVE, risk=RiskLevel.NONE, reversible=True)
    assert g.decision == GateDecision.ALLOW
    g = permission_gate(autonomy=AutonomyMode.OBSERVE, risk=RiskLevel.LOW, reversible=True)
    assert g.decision == GateDecision.SUGGEST


def test_suggest_mode_never_acts_outward():
    g = permission_gate(autonomy=AutonomyMode.SUGGEST, risk=RiskLevel.MEDIUM, reversible=True)
    assert g.decision == GateDecision.SUGGEST


def test_safe_act_runs_low_risk_but_confirms_high():
    assert (
        permission_gate(autonomy=AutonomyMode.SAFE_ACT, risk=RiskLevel.LOW, reversible=True).decision
        == GateDecision.ALLOW
    )
    assert (
        permission_gate(
            autonomy=AutonomyMode.SAFE_ACT, risk=RiskLevel.MEDIUM, reversible=True
        ).decision
        == GateDecision.ALLOW
    )
    assert (
        permission_gate(
            autonomy=AutonomyMode.SAFE_ACT, risk=RiskLevel.MEDIUM, reversible=False
        ).decision
        == GateDecision.CONFIRM
    )
    assert (
        permission_gate(
            autonomy=AutonomyMode.SAFE_ACT, risk=RiskLevel.HIGH, reversible=True
        ).decision
        == GateDecision.CONFIRM
    )


def test_escalated_act_is_full_freedom():
    # Top of the ladder: no brakes — even irreversible high-risk actions (e.g.
    # running its own code) are allowed without confirmation.
    assert (
        permission_gate(
            autonomy=AutonomyMode.ESCALATED_ACT, risk=RiskLevel.HIGH, reversible=True
        ).decision
        == GateDecision.ALLOW
    )
    assert (
        permission_gate(
            autonomy=AutonomyMode.ESCALATED_ACT, risk=RiskLevel.HIGH, reversible=False
        ).decision
        == GateDecision.ALLOW
    )


def test_mode_parsing_roundtrip():
    assert AutonomyMode.from_str("safe_act") == AutonomyMode.SAFE_ACT
    assert AutonomyMode.SAFE_ACT.label == "safe_act"

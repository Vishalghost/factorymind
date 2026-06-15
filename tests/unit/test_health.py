from agents.shared.utils.health import derive_status_health


def test_critical_severity_is_fault_and_low_health():
    status, health = derive_status_health("CRITICAL", {
        "vibration_mms": 9.5, "current_amps": 20, "coolant_lmin": 12, "acoustic_db": 80})
    assert status == "FAULT"
    assert 0.0 <= health <= 0.3

def test_high_severity_is_warning():
    status, health = derive_status_health("HIGH", {
        "vibration_mms": 8.6, "current_amps": 20, "coolant_lmin": 45, "acoustic_db": 80})
    assert status == "MAINTENANCE"
    assert 0.3 <= health <= 0.7

def test_no_anomaly_is_running_high_health():
    status, health = derive_status_health(None, {
        "vibration_mms": 3.4, "current_amps": 18, "coolant_lmin": 45, "acoustic_db": 78})
    assert status == "RUNNING"
    assert health >= 0.85

def test_health_is_clamped():
    _, health = derive_status_health(None, {
        "vibration_mms": 0, "current_amps": 0, "coolant_lmin": 50, "acoustic_db": 70})
    assert 0.0 <= health <= 1.0

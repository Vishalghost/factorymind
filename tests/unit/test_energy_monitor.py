from unittest.mock import MagicMock
from agents.sustainability.workers.energy_monitor import _query_energy_readings


def test_query_parses_timestream_rows():
    client = MagicMock()
    client.query.return_value = {
        "Rows": [
            {"Data": [{"ScalarValue": "CNC-AERO-01"}, {"ScalarValue": "14.2"}]},
            {"Data": [{"ScalarValue": "CNC-AERO-02"}, {"ScalarValue": "9.7"}]},
        ],
        "ColumnInfo": [{"Name": "machine_id"}, {"Name": "power_kwh"}],
    }
    rows = _query_energy_readings("PLANT-001", None, client)
    assert {"machine_id": "CNC-AERO-01", "power_kwh": 14.2} in rows
    assert len(rows) == 2

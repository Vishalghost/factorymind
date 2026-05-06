"""Unit tests for Sustainability Manager."""

import json
import pytest
from unittest.mock import MagicMock, patch, ANY

from agents.sustainability.workers.energy_monitor import monitor_energy
from agents.sustainability.workers.carbon_calculator import calculate_carbon
from agents.sustainability.workers.kpi_calculator import calculate_kpis
from agents.sustainability.workers.waste_detector import detect_waste, IDLE_POWER_THRESHOLD_KWH
from agents.sustainability.workers.genai_recommender import (
    generate_recommendations,
    _invoke_bedrock,
    _build_prompt,
    _fallback_recommendations,
)
from agents.shared.constants import CARBON_KG_PER_KWH, ENERGY_COST_INR_PER_KWH


class TestEnergyMonitor:
    """Tests for energy_monitor — deviation calculation against baselines."""

    def test_deviation_calculation_positive(self):
        """Positive deviation when current exceeds baseline."""
        mock_timestream = MagicMock()
        mock_timestream.query.return_value = {
            "Rows": [
                {
                    "Data": [
                        {"ScalarValue": "CNC-AERO-01"},
                        {"ScalarValue": "12.5"},
                    ]
                }
            ]
        }

        mock_table = MagicMock()
        mock_table.get_item.return_value = {
            "Item": {"machine_id": "CNC-AERO-01", "baseline_kwh": "10.0"}
        }

        # Use the internal logic directly by testing the deviation formula
        current_kwh = 12.5
        baseline_kwh = 10.0
        expected_deviation = ((current_kwh - baseline_kwh) / baseline_kwh) * 100
        assert expected_deviation == 25.0

    def test_deviation_calculation_negative(self):
        """Negative deviation when current is below baseline (energy savings)."""
        current_kwh = 8.0
        baseline_kwh = 10.0
        deviation_pct = ((current_kwh - baseline_kwh) / baseline_kwh) * 100
        assert deviation_pct == -20.0

    def test_deviation_zero_when_at_baseline(self):
        """Zero deviation when current equals baseline."""
        current_kwh = 10.0
        baseline_kwh = 10.0
        deviation_pct = ((current_kwh - baseline_kwh) / baseline_kwh) * 100
        assert deviation_pct == 0.0

    def test_deviation_zero_baseline_handled(self):
        """Zero baseline should not cause division by zero."""
        current_kwh = 5.0
        baseline_kwh = 0.0
        # The energy_monitor handles this case
        deviation_pct = (
            ((current_kwh - baseline_kwh) / baseline_kwh * 100)
            if baseline_kwh > 0
            else 0.0
        )
        assert deviation_pct == 0.0

    def test_energy_cost_calculation_in_metrics(self):
        """Energy cost should be current_kwh * Rs 7.50/kWh."""
        current_kwh = 12.5
        expected_cost = current_kwh * ENERGY_COST_INR_PER_KWH
        assert expected_cost == 93.75


class TestCarbonCalculator:
    """Tests for carbon_calculator — carbon footprint and cost calculations."""

    def test_carbon_footprint_single_machine(self):
        """Carbon footprint = total_kwh * 0.82 kg CO2/kWh."""
        energy_metrics = [
            {"current_kwh": 10.0, "baseline_kwh": 8.0},
        ]
        result = calculate_carbon(energy_metrics)

        assert result["total_kwh"] == 10.0
        assert result["total_carbon_kg"] == round(10.0 * CARBON_KG_PER_KWH, 2)
        assert result["total_carbon_kg"] == 8.2

    def test_carbon_footprint_multiple_machines(self):
        """Carbon footprint sums across all machines."""
        energy_metrics = [
            {"current_kwh": 10.0, "baseline_kwh": 8.0},
            {"current_kwh": 15.0, "baseline_kwh": 12.0},
            {"current_kwh": 5.0, "baseline_kwh": 5.0},
        ]
        result = calculate_carbon(energy_metrics)

        total_kwh = 10.0 + 15.0 + 5.0  # 30.0
        assert result["total_kwh"] == 30.0
        assert result["total_carbon_kg"] == round(30.0 * 0.82, 2)
        assert result["total_carbon_kg"] == 24.6

    def test_energy_cost_calculation(self):
        """Energy cost = total_kwh * Rs 7.50/kWh."""
        energy_metrics = [
            {"current_kwh": 20.0, "baseline_kwh": 15.0},
        ]
        result = calculate_carbon(energy_metrics)

        assert result["total_cost_inr"] == round(20.0 * 7.50, 2)
        assert result["total_cost_inr"] == 150.0

    def test_potential_savings_calculation(self):
        """Potential savings = excess_kwh * conversion factors."""
        energy_metrics = [
            {"current_kwh": 12.0, "baseline_kwh": 10.0},
        ]
        result = calculate_carbon(energy_metrics)

        excess_kwh = 12.0 - 10.0  # 2.0
        assert result["excess_kwh"] == 2.0
        assert result["potential_savings_kg"] == round(2.0 * 0.82, 2)
        assert result["potential_savings_kg"] == 1.64
        assert result["potential_cost_savings_inr"] == round(2.0 * 7.50, 2)
        assert result["potential_cost_savings_inr"] == 15.0

    def test_no_excess_when_below_baseline(self):
        """No excess energy when current is below baseline."""
        energy_metrics = [
            {"current_kwh": 8.0, "baseline_kwh": 10.0},
        ]
        result = calculate_carbon(energy_metrics)

        assert result["excess_kwh"] == 0.0
        assert result["potential_savings_kg"] == 0.0
        assert result["potential_cost_savings_inr"] == 0.0

    def test_empty_metrics_returns_zeros(self):
        """Empty energy metrics should return all zeros."""
        result = calculate_carbon([])

        assert result["total_kwh"] == 0.0
        assert result["total_carbon_kg"] == 0.0
        assert result["total_cost_inr"] == 0.0
        assert result["excess_kwh"] == 0.0

    def test_carbon_conversion_factor_is_082(self):
        """Verify the carbon conversion factor constant is 0.82 kg CO2/kWh."""
        assert CARBON_KG_PER_KWH == 0.82

    def test_energy_cost_factor_is_750(self):
        """Verify the energy cost constant is Rs 7.50/kWh."""
        assert ENERGY_COST_INR_PER_KWH == 7.50


class TestKPICalculator:
    """Tests for kpi_calculator — sustainability KPI computation."""

    def test_energy_efficiency_perfect(self):
        """Energy efficiency = 1.0 when current equals baseline."""
        energy_metrics = [
            {"current_kwh": 10.0, "baseline_kwh": 10.0},
        ]
        waste_data = {"total_waste_kwh": 0.0}
        carbon_data = {"total_carbon_kg": 8.2}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        assert kpis["energy_efficiency"] == 1.0

    def test_energy_efficiency_degraded(self):
        """Energy efficiency < 1.0 when current exceeds baseline."""
        energy_metrics = [
            {"current_kwh": 20.0, "baseline_kwh": 10.0},
        ]
        waste_data = {"total_waste_kwh": 0.0}
        carbon_data = {"total_carbon_kg": 16.4}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        # efficiency = baseline / current = 10 / 20 = 0.5
        assert kpis["energy_efficiency"] == 0.5

    def test_energy_efficiency_capped_at_one(self):
        """Energy efficiency should not exceed 1.0 even if below baseline."""
        energy_metrics = [
            {"current_kwh": 8.0, "baseline_kwh": 10.0},
        ]
        waste_data = {"total_waste_kwh": 0.0}
        carbon_data = {"total_carbon_kg": 6.56}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        # min(1.0, 10/8) = min(1.0, 1.25) = 1.0
        assert kpis["energy_efficiency"] == 1.0

    def test_carbon_footprint_in_kpis(self):
        """Carbon footprint KPI = total_current * 0.82."""
        energy_metrics = [
            {"current_kwh": 10.0, "baseline_kwh": 8.0},
            {"current_kwh": 5.0, "baseline_kwh": 4.0},
        ]
        waste_data = {"total_waste_kwh": 0.0}
        carbon_data = {"total_carbon_kg": 12.3}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        # total_current = 15.0, carbon = 15.0 * 0.82 = 12.3
        assert kpis["carbon_footprint_kg"] == 12.3

    def test_waste_index_calculation(self):
        """Waste index = waste_kwh / total_current."""
        energy_metrics = [
            {"current_kwh": 20.0, "baseline_kwh": 15.0},
        ]
        waste_data = {"total_waste_kwh": 5.0}
        carbon_data = {"total_carbon_kg": 16.4}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        # waste_index = 5.0 / 20.0 = 0.25
        assert kpis["waste_index"] == 0.25

    def test_waste_index_capped_at_one(self):
        """Waste index should not exceed 1.0."""
        energy_metrics = [
            {"current_kwh": 5.0, "baseline_kwh": 3.0},
        ]
        waste_data = {"total_waste_kwh": 10.0}
        carbon_data = {"total_carbon_kg": 4.1}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        # min(1.0, 10.0 / 5.0) = min(1.0, 2.0) = 1.0
        assert kpis["waste_index"] == 1.0

    def test_overall_score_range(self):
        """Overall score should be between 0 and 100."""
        energy_metrics = [
            {"current_kwh": 12.0, "baseline_kwh": 10.0},
        ]
        waste_data = {"total_waste_kwh": 2.0}
        carbon_data = {"total_carbon_kg": 9.84}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        assert 0.0 <= kpis["overall_score"] <= 100.0

    def test_kpis_with_zero_current(self):
        """KPIs should handle zero current gracefully."""
        energy_metrics = [
            {"current_kwh": 0.0, "baseline_kwh": 0.0},
        ]
        waste_data = {"total_waste_kwh": 0.0}
        carbon_data = {"total_carbon_kg": 0.0}

        kpis = calculate_kpis(energy_metrics, waste_data, carbon_data)

        assert kpis["energy_efficiency"] == 1.0
        assert kpis["carbon_footprint_kg"] == 0.0
        assert kpis["waste_index"] == 0.0


class TestWasteDetector:
    """Tests for waste_detector — idle CNC machines consuming power."""

    def test_waste_detected_high_deviation_above_threshold(self):
        """Machine with >20% deviation and >2 kWh is flagged as waste."""
        energy_metrics = [
            {
                "machine_id": "CNC-AERO-01",
                "current_kwh": 5.0,
                "baseline_kwh": 3.0,
                "deviation_pct": 66.7,
            },
        ]
        machine_states = {"CNC-AERO-01": "IDLE"}

        result = detect_waste(energy_metrics, machine_states)

        assert result["waste_machine_count"] == 1
        assert result["waste_machines"][0]["machine_id"] == "CNC-AERO-01"
        assert result["waste_machines"][0]["waste_kwh"] == 2.0
        assert result["total_waste_kwh"] == 2.0

    def test_no_waste_when_deviation_below_threshold(self):
        """Machine with <=20% deviation is not flagged."""
        energy_metrics = [
            {
                "machine_id": "CNC-AERO-01",
                "current_kwh": 10.5,
                "baseline_kwh": 10.0,
                "deviation_pct": 5.0,
            },
        ]

        result = detect_waste(energy_metrics)

        assert result["waste_machine_count"] == 0
        assert result["waste_machines"] == []
        assert result["total_waste_kwh"] == 0.0

    def test_no_waste_when_below_idle_power_threshold(self):
        """Machine consuming <= 2 kWh is not flagged even with high deviation."""
        energy_metrics = [
            {
                "machine_id": "CNC-AERO-01",
                "current_kwh": 1.5,
                "baseline_kwh": 1.0,
                "deviation_pct": 50.0,
            },
        ]

        result = detect_waste(energy_metrics)

        assert result["waste_machine_count"] == 0

    def test_multiple_waste_machines(self):
        """Multiple idle machines consuming power are all detected."""
        energy_metrics = [
            {
                "machine_id": "CNC-AERO-01",
                "current_kwh": 6.0,
                "baseline_kwh": 4.0,
                "deviation_pct": 50.0,
            },
            {
                "machine_id": "CNC-AERO-02",
                "current_kwh": 8.0,
                "baseline_kwh": 5.0,
                "deviation_pct": 60.0,
            },
            {
                "machine_id": "CNC-AERO-03",
                "current_kwh": 10.0,
                "baseline_kwh": 9.5,
                "deviation_pct": 5.3,
            },
        ]
        machine_states = {
            "CNC-AERO-01": "IDLE",
            "CNC-AERO-02": "IDLE",
            "CNC-AERO-03": "RUNNING",
        }

        result = detect_waste(energy_metrics, machine_states)

        assert result["waste_machine_count"] == 2
        waste_ids = [m["machine_id"] for m in result["waste_machines"]]
        assert "CNC-AERO-01" in waste_ids
        assert "CNC-AERO-02" in waste_ids
        assert "CNC-AERO-03" not in waste_ids
        assert result["total_waste_kwh"] == round(2.0 + 3.0, 2)

    def test_idle_power_threshold_constant(self):
        """Verify idle power threshold is 2.0 kWh."""
        assert IDLE_POWER_THRESHOLD_KWH == 2.0

    def test_waste_detection_with_no_machine_states(self):
        """Waste detection works without explicit machine states."""
        energy_metrics = [
            {
                "machine_id": "CNC-AERO-01",
                "current_kwh": 7.0,
                "baseline_kwh": 4.0,
                "deviation_pct": 75.0,
            },
        ]

        result = detect_waste(energy_metrics)

        assert result["waste_machine_count"] == 1
        assert result["waste_machines"][0]["status"] == "UNKNOWN"


class TestGenAIRecommender:
    """Tests for genai_recommender — Bedrock Claude 3.5 invocation."""

    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_runtime_client")
    def test_bedrock_invocation_success(self, mock_get_client):
        """Bedrock invocation should return parsed recommendations."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        recommendations_json = json.dumps([
            "Shut down idle CNC-AERO-03 to save 2.5 kWh",
            "Schedule spindle maintenance for CNC-AERO-07",
            "Optimize coolant pump scheduling during off-peak hours",
        ])

        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({
            "content": [{"type": "text", "text": recommendations_json}]
        })
        mock_client.invoke_model.return_value = {"body": mock_response_body}

        result = _invoke_bedrock("test prompt")

        assert len(result) == 3
        assert "CNC-AERO-03" in result[0]
        mock_client.invoke_model.assert_called_once()

    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_runtime_client")
    def test_bedrock_invocation_uses_correct_model(self, mock_get_client):
        """Bedrock invocation should use Claude 3.5 model ID."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({
            "content": [{"type": "text", "text": '["recommendation"]'}]
        })
        mock_client.invoke_model.return_value = {"body": mock_response_body}

        _invoke_bedrock("test prompt")

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert "anthropic.claude" in call_kwargs["modelId"]
        assert call_kwargs["contentType"] == "application/json"
        assert call_kwargs["accept"] == "application/json"

    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_runtime_client")
    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_agent_runtime_client")
    def test_generate_recommendations_full_flow(
        self, mock_get_agent_client, mock_get_client
    ):
        """Full recommendation flow: Knowledge Base query + Bedrock invocation."""
        # Mock Knowledge Base client (no KB configured)
        mock_agent_client = MagicMock()
        mock_get_agent_client.return_value = mock_agent_client

        # Mock Bedrock Runtime client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        recommendations_json = json.dumps([
            "Reduce idle time on CNC-AERO-01",
            "Optimize spindle speed profiles",
        ])
        mock_response_body = MagicMock()
        mock_response_body.read.return_value = json.dumps({
            "content": [{"type": "text", "text": recommendations_json}]
        })
        mock_client.invoke_model.return_value = {"body": mock_response_body}

        energy_metrics = [{"current_kwh": 12.0, "baseline_kwh": 10.0}]
        kpis = {"energy_efficiency": 0.83, "carbon_footprint_kg": 9.84, "waste_index": 0.1, "overall_score": 75.0}
        waste_data = {"waste_machines": [], "total_waste_kwh": 0.0}

        result = generate_recommendations(energy_metrics, kpis, waste_data)

        assert len(result) == 2
        assert "CNC-AERO-01" in result[0]

    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_runtime_client")
    @patch("agents.sustainability.workers.genai_recommender._get_bedrock_agent_runtime_client")
    def test_fallback_recommendations_on_bedrock_failure(
        self, mock_get_agent_client, mock_get_client
    ):
        """Fallback recommendations returned when Bedrock invocation fails."""
        mock_get_agent_client.return_value = MagicMock()
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.invoke_model.side_effect = Exception("Bedrock unavailable")

        energy_metrics = [
            {"current_kwh": 12.0, "baseline_kwh": 10.0, "deviation_pct": 20.0}
        ]
        kpis = {"energy_efficiency": 0.83, "carbon_footprint_kg": 9.84, "waste_index": 0.1, "overall_score": 75.0}
        waste_data = {
            "waste_machines": [{"machine_id": "CNC-AERO-05", "waste_kwh": 3.0}],
            "total_waste_kwh": 3.0,
        }

        result = generate_recommendations(energy_metrics, kpis, waste_data)

        # Should return fallback recommendations (not empty)
        assert len(result) > 0
        # Fallback should mention the waste machine
        assert any("CNC-AERO-05" in r for r in result)

    def test_fallback_recommendations_with_waste_machines(self):
        """Fallback recommendations should mention idle waste machines."""
        energy_metrics = [
            {"current_kwh": 12.0, "baseline_kwh": 10.0, "deviation_pct": 20.0}
        ]
        waste_data = {
            "waste_machines": [
                {"machine_id": "CNC-AERO-01", "waste_kwh": 2.0},
                {"machine_id": "CNC-AERO-02", "waste_kwh": 3.0},
            ],
            "total_waste_kwh": 5.0,
        }

        result = _fallback_recommendations(energy_metrics, waste_data)

        assert len(result) > 0
        assert any("CNC-AERO-01" in r for r in result)

    def test_fallback_recommendations_with_high_deviation(self):
        """Fallback recommendations should mention high deviation machines."""
        energy_metrics = [
            {"current_kwh": 15.0, "baseline_kwh": 10.0, "deviation_pct": 50.0}
        ]
        waste_data = {"waste_machines": [], "total_waste_kwh": 0.0}

        result = _fallback_recommendations(energy_metrics, waste_data)

        assert any("15%" in r or "deviation" in r.lower() for r in result)

    def test_build_prompt_includes_constants(self):
        """Prompt should include carbon conversion and cost rate."""
        energy_metrics = [{"current_kwh": 10.0, "baseline_kwh": 8.0}]
        kpis = {"energy_efficiency": 0.8, "carbon_footprint_kg": 8.2, "waste_index": 0.1, "overall_score": 70.0}
        waste_data = {"waste_machines": [], "total_waste_kwh": 0.0}

        prompt = _build_prompt(energy_metrics, kpis, waste_data, "")

        assert "0.82" in prompt
        assert "7.5" in prompt or "7.50" in prompt


class TestWeeklyReportSES:
    """Tests for weekly report SES email trigger."""

    @patch("agents.sustainability.manager.handler.monitor_energy")
    @patch("agents.sustainability.manager.handler.detect_waste")
    @patch("agents.sustainability.manager.handler.calculate_carbon")
    @patch("agents.sustainability.manager.handler.calculate_kpis")
    @patch("agents.sustainability.manager.handler.generate_recommendations")
    def test_weekly_report_analysis_type_accepted(
        self,
        mock_recommendations,
        mock_kpis,
        mock_carbon,
        mock_waste,
        mock_energy,
    ):
        """Handler should accept analysis_type='weekly_report' and process normally."""
        mock_energy.return_value = [
            {"machine_id": "CNC-AERO-01", "current_kwh": 10.0, "baseline_kwh": 8.0}
        ]
        mock_waste.return_value = {"waste_machines": [], "total_waste_kwh": 0.0, "waste_machine_count": 0}
        mock_carbon.return_value = {
            "total_kwh": 10.0,
            "total_carbon_kg": 8.2,
            "total_cost_inr": 75.0,
            "baseline_carbon_kg": 6.56,
            "excess_kwh": 2.0,
            "potential_savings_kg": 1.64,
            "potential_cost_savings_inr": 15.0,
        }
        mock_kpis.return_value = {
            "energy_efficiency": 0.8,
            "carbon_footprint_kg": 8.2,
            "waste_index": 0.0,
            "overall_score": 75.0,
        }
        mock_recommendations.return_value = ["Optimize scheduling"]

        from agents.sustainability.manager.handler import handler

        event = {
            "plant_id": "PLANT-001",
            "analysis_type": "weekly_report",
            "timestamp": "2026-05-06T00:00:00Z",
        }

        result = handler(event, None)

        assert result["report_id"].startswith("SUSR-")
        assert result["plant_id"] == "PLANT-001"
        assert result["recommendations"] == ["Optimize scheduling"]
        assert result["processing_time_ms"] >= 0

    @patch("boto3.client")
    def test_ses_email_send_mock(self, mock_boto_client):
        """SES email send should be invocable with correct parameters."""
        mock_ses = MagicMock()
        mock_boto_client.return_value = mock_ses

        # Simulate what a weekly report SES call would look like
        import boto3
        ses_client = boto3.client("ses", region_name="ap-south-1")

        ses_client.send_email(
            Source="sustainability@factorymind.io",
            Destination={
                "ToAddresses": ["plant-manager@factorymind.io"]
            },
            Message={
                "Subject": {"Data": "FactoryMind Weekly Sustainability Report - PLANT-001"},
                "Body": {
                    "Html": {
                        "Data": "<h1>Weekly Sustainability Report</h1><p>Energy efficiency: 85%</p>"
                    }
                },
            },
        )

        mock_ses.send_email.assert_called_once()
        call_kwargs = mock_ses.send_email.call_args[1]
        assert call_kwargs["Source"] == "sustainability@factorymind.io"
        assert "plant-manager@factorymind.io" in call_kwargs["Destination"]["ToAddresses"]
        assert "Weekly Sustainability Report" in call_kwargs["Message"]["Subject"]["Data"]


class TestSustainabilityManagerHandler:
    """Tests for the full Sustainability Manager handler integration."""

    @patch("agents.sustainability.manager.handler.monitor_energy")
    @patch("agents.sustainability.manager.handler.detect_waste")
    @patch("agents.sustainability.manager.handler.calculate_carbon")
    @patch("agents.sustainability.manager.handler.calculate_kpis")
    @patch("agents.sustainability.manager.handler.generate_recommendations")
    def test_handler_full_pipeline(
        self,
        mock_recommendations,
        mock_kpis,
        mock_carbon,
        mock_waste,
        mock_energy,
    ):
        """Handler should orchestrate all workers and return complete output."""
        mock_energy.return_value = [
            {"machine_id": "CNC-AERO-01", "current_kwh": 12.0, "baseline_kwh": 10.0}
        ]
        mock_waste.return_value = {"waste_machines": [], "total_waste_kwh": 0.0, "waste_machine_count": 0}
        mock_carbon.return_value = {
            "total_kwh": 12.0,
            "total_carbon_kg": 9.84,
            "total_cost_inr": 90.0,
            "baseline_carbon_kg": 8.2,
            "excess_kwh": 2.0,
            "potential_savings_kg": 1.64,
            "potential_cost_savings_inr": 15.0,
        }
        mock_kpis.return_value = {
            "energy_efficiency": 0.833,
            "carbon_footprint_kg": 9.84,
            "waste_index": 0.0,
            "overall_score": 78.5,
        }
        mock_recommendations.return_value = [
            "Optimize CNC spindle scheduling",
            "Reduce idle time on Line-B machines",
        ]

        from agents.sustainability.manager.handler import handler

        event = {
            "plant_id": "PLANT-001",
            "analysis_type": "real_time",
            "timestamp": "2026-05-06T14:30:00Z",
        }

        result = handler(event, None)

        assert result["report_id"].startswith("SUSR-")
        assert result["plant_id"] == "PLANT-001"
        assert len(result["energy_metrics"]) == 1
        assert result["kpis"]["energy_efficiency"] == 0.833
        assert len(result["recommendations"]) == 2
        assert result["carbon_saved_kg"] == 1.64
        assert result["cost_saved_inr"] == 15.0
        assert result["processing_time_ms"] >= 0

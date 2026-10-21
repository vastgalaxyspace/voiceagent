import pytest
from google.genai import types
from app.services.usage import Measurements
from tests.helpers.fakes import usage


def test_unknown_usage_preserves_samples_without_claiming_cost():
    report = Measurements('gemini-3.8-live', 'unknown')
    report.record_usage(usage(100, 50))
    summary = report.summary('user_stopped')
    assert summary['usage_event_count'] == 1
    assert summary['aggregated_tokens'] is None
    assert summary['estimated_model_cost_usd'] is None


def test_cumulative_usage_uses_deltas():
    report = Measurements('gemini-3.8-live', 'cumulative')
    report.record_usage(usage(100, 50))
    report.record_usage(usage(150, 75))
    summary = report.summary('user_stopped')
    assert summary['aggregated_tokens'] == {'input_AUDIO': 150, 'output_AUDIO': 75}
    assert summary['estimated_model_cost_usd'] == .00135


@pytest.mark.parametrize('metadata', [
    types.UsageMetadata(prompt_token_count=100),
    usage(100, 50, thoughts_token_count=10),
    usage(100, 50, tool_use_prompt_token_count=10),
])
def test_incomplete_or_extra_usage_does_not_claim_full_cost(metadata):
    report = Measurements('gemini-3.8-live', 'per_response')
    report.record_usage(metadata)
    assert report.summary('user_stopped')['estimated_model_cost_usd'] is None


def test_unknown_model_never_uses_another_models_prices():
    report = Measurements('some-other-model', 'per_response')
    report.record_usage(usage(10, 5))
    assert report.summary('user_stopped')['estimated_model_cost_usd'] is None


@pytest.mark.parametrize('metadata', [
    types.UsageMetadata(),
    usage(100, 50, total_token_count=999),
])
def test_missing_or_inconsistent_totals_prevent_cost_estimate(metadata):
    report = Measurements('gemini-3.8-live', 'per_response')
    report.record_usage(metadata)
    assert report.summary('user_stopped')['estimated_model_cost_usd'] is None


def test_falling_cumulative_counter_invalidates_estimate():
    report = Measurements('gemini-3.8-live', 'cumulative')
    report.record_usage(usage(100, 50))
    report.record_usage(usage(10, 5))
    assert report.summary('user_stopped')['estimated_model_cost_usd'] is None


def test_activity_after_final_usage_invalidates_settlement_but_preserves_observed_cost():
    report = Measurements('gemini-3.8-live', 'per_response')
    report.record_usage(usage(10, 5))
    report.mark_provider_activity()
    summary = report.summary('user_stopped')
    assert summary['estimated_model_cost_usd'] is None
    assert summary['observed_model_cost_usd'] == .00009
    assert summary['usage_complete'] is False
    assert summary['unreported_provider_activity'] is True


def test_mid_turn_metadata_does_not_clear_pending_activity():
    report = Measurements('gemini-3.8-live', 'per_response')
    report.mark_provider_activity()
    report.record_usage(usage(10, 5), final_for_turn=False)
    assert report.estimated_cost() == pytest.approx(.00009)
    assert report.summary('duration_limit')['usage_complete'] is False


def test_delayed_final_metadata_can_cover_completed_turn():
    report = Measurements('gemini-3.8-live', 'per_response')
    report.mark_provider_activity()
    report.mark_turn_complete()
    report.record_usage(usage(10, 5), final_for_turn=report.turn_finished)
    assert report.summary('user_stopped')['usage_complete'] is True


def test_completed_response_does_not_acknowledge_overlapping_input():
    report = Measurements('gemini-3.8-live', 'per_response')
    report.mark_input_activity()
    report.mark_output_activity()
    report.mark_input_activity()  # User starts talking during assistant output.
    report.mark_turn_complete()
    report.record_usage(usage(10, 5), final_for_turn=report.turn_finished)
    assert report.summary('user_stopped')['usage_complete'] is False

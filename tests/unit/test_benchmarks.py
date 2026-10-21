import json
import subprocess
import sys


def test_benchmark_comparison_does_not_treat_unknown_cost_as_zero(tmp_path):
    for number, cost in enumerate([None, .1]):
        (tmp_path / f'{number}.json').write_text(json.dumps({
            'session_id': str(number), 'estimated_model_cost_usd': cost,
        }), encoding='utf-8')
    result = subprocess.run(
        [sys.executable, 'scripts/summarize_benchmarks.py', str(tmp_path)],
        capture_output=True, text=True, check=True,
    )
    summary = json.loads(result.stdout.splitlines()[-1])
    assert summary['sessions'] == 2
    assert summary['sessions_with_cost_estimates'] == 1
    assert summary['mean_estimated_cost_usd'] == .1

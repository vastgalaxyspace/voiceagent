"""Compare downloaded metadata reports without reading audio or transcripts."""
import argparse
import json
from pathlib import Path
from statistics import mean


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Directory containing session JSON reports')
    args = parser.parse_args()
    reports = []
    for path in sorted(args.directory.glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8-sig'))
        if 'session_id' in data:
            reports.append(data)
    if not reports:
        parser.error('No session reports found')
    for report in reports:
        print(json.dumps({key: report.get(key) for key in (
            'session_id', 'model', 'duration_seconds', 'turn_count',
            'interruption_count', 'ready_ms', 'relay_p95_ms',
            'estimated_model_cost_usd', 'cost_status', 'end_reason',
        )}))
    costs = [report['estimated_model_cost_usd'] for report in reports
             if report.get('estimated_model_cost_usd') is not None]
    print(json.dumps({
        'sessions': len(reports), 'sessions_with_cost_estimates': len(costs),
        'mean_estimated_cost_usd': mean(costs) if costs else None,
        'note': 'No missing costs are treated as zero. Group by model/configuration and scenario before comparing.',
    }))


if __name__ == '__main__':
    main()

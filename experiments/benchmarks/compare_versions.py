"""Run the same offline part benchmark against symbolic repository versions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile


def _numeric_metrics(result):
    values = {}
    for part, data in result.get('results', {}).items():
        median = data.get('median', {})
        for key, value in median.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[f'{part}.{key}'] = value
        for scenario, scenario_data in data.get('scenarios', {}).items():
            for key, value in scenario_data.get('median', {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    values[f'{part}.{scenario}.{key}'] = value
    return values


def _run_one(script, repo, ref, output, samples):
    command = [sys.executable, str(script), '--repo', str(repo), '--commit', ref,
               '--output', str(output), '--samples', str(samples)]
    subprocess.run(command, check=True)
    return json.loads(output.read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--samples', type=int, default=10)
    parser.add_argument('--refs', nargs='+', default=['5677870', 'b7cb4c6', '1a4f7e6', 'b64d82b', 'HEAD'])
    args = parser.parse_args()
    repo, script = args.repo.resolve(), Path(__file__).resolve().parent / 'benchmark_parts.py'
    versions = []
    with tempfile.TemporaryDirectory(prefix='turtleneck-benchmark-versions-') as folder:
        root = Path(folder)
        for index, ref in enumerate(args.refs):
            if ref in ('HEAD', 'working-tree'):
                output = root / f'{index}.json'
                subprocess.run([sys.executable, str(script), '--repo', str(repo), '--output', str(output),
                                '--samples', str(args.samples)], check=True)
                data = json.loads(output.read_text(encoding='utf-8'))
            else:
                archive = root / f'{index}.tar'
                checkout = root / f'{index}-checkout'
                checkout.mkdir()
                subprocess.run(['git', 'archive', '--format=tar', f'--output={archive}', ref], cwd=repo, check=True)
                with tarfile.open(archive) as bundle:
                    bundle.extractall(checkout)
                data = _run_one(script, checkout, ref, root / f'{index}.json', args.samples)
            versions.append({'ref': ref, 'environment': data['environment'],
                             'run': data['run'], 'parts': data['parts'], 'results': data['results'],
                             'numericMetrics': _numeric_metrics(data)})
    output = {'comparisonVersion': 1, 'samples': args.samples, 'versions': versions}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'versions': [item['environment']['commitShort'] for item in versions],
                      'output': str(args.output)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

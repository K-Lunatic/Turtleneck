"""Opt-in launcher for approved partial kernels; default entry points stay Python."""
import argparse
import json
from pathlib import Path
import runpy
import sys
from backend import activate
from python_adapter import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('script', choices=('sync_tls', 'run_agent'))
    args, forwarded = parser.parse_known_args()
    decision = json.loads((Path(__file__).parent / 'results/partial-decision.json').read_text(encoding='utf-8'))
    modules = tuple(name for name in ('activity', 'overview', 'concept') if decision['modules'][name]['adopt'])
    target = ROOT / 'skills/university-agent/scripts' / (args.script + '.py')
    sys.path.insert(0, str(target.parent))
    sys.argv = [str(target), *forwarded]
    with activate(modules=modules) as enabled:
        print('Experimental HTML backend: ' + (', '.join(enabled) if enabled else 'Python fallback'), file=sys.stderr)
        runpy.run_path(str(target), run_name='__main__')


if __name__ == '__main__':
    main()

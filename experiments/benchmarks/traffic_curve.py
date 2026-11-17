"""Render a cumulative user-browser vs Turtleneck traffic curve from sanitized comparisons."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path


WIDTH, HEIGHT = 760, 420
PLOT = (72, 36, 704, 344)


def _value(item: dict, metric: str) -> float:
    value = item.get("comparison", {}).get(metric, {}).get("skill")
    if not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"comparison에 skill {metric} 값이 없어요.")
    user = item["comparison"][metric].get("user")
    if not isinstance(user, (int, float)) or user < 0:
        raise ValueError(f"comparison에 user {metric} 값이 없어요.")
    return float(value), float(user)


def render_svg(comparisons: list[dict], metric: str = "bodyBytesLowerBound") -> str:
    if not comparisons:
        raise ValueError("비교 결과가 하나 이상 필요해요.")
    scenarios = {item.get("scenario") for item in comparisons}
    if len(scenarios) != 1:
        raise ValueError("같은 시나리오의 비교 결과만 한 곡선에 넣을 수 있어요.")
    points = [_value(item, metric) for item in comparisons]
    skill, user = [], []
    skill_total = user_total = 0.0
    for skill_value, user_value in points:
        skill_total += skill_value
        user_total += user_value
        skill.append(skill_total)
        user.append(user_total)
    maximum = max(skill[-1], user[-1], 1.0)
    left, top, right, bottom = PLOT
    chart_width, chart_height = right - left, bottom - top

    def coords(values):
        return " ".join(
            f"{left + chart_width * index / max(1, len(values) - 1):.1f},"
            f"{bottom - chart_height * value / maximum:.1f}"
            for index, value in enumerate(values)
        )

    title = html.escape(str(next(iter(scenarios))))
    metric_label = "누적 요청·응답 본문 하한 (B)" if metric == "bodyBytesLowerBound" else "누적 요청 수"
    labels = []
    for index in range(len(points)):
        x = left + chart_width * index / max(1, len(points) - 1)
        labels.append(f'<text x="{x:.1f}" y="{bottom + 24}" text-anchor="middle">{index + 1}</text>')
    grid = []
    for index in range(5):
        value = maximum * index / 4
        y = bottom - chart_height * index / 4
        grid.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" class="grid"/>'
                    f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end">{value:,.0f}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">
<title id="title">건국대 TLS {html.escape(metric_label)} 비교</title>
<desc id="desc">동일한 {title} 시나리오를 반복했을 때의 사용자 브라우저와 터틀넥 누적 트래픽 하한 비교</desc>
<style>text{{font:13px system-ui,sans-serif;fill:#24332a}}.grid{{stroke:#d9e5dc;stroke-width:1}}.axis{{stroke:#789080;stroke-width:1}}.skill{{fill:none;stroke:#226b35;stroke-width:3}}.user{{fill:none;stroke:#c27724;stroke-width:3;stroke-dasharray:8 6}}.legend{{font-weight:650}}</style>
<rect width="100%" height="100%" fill="#fbfdfb"/><text x="{left}" y="22" class="legend">건국대 TLS · {title}</text>
{''.join(grid)}<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" class="axis"/><line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" class="axis"/>
<polyline points="{coords(skill)}" class="skill"/><polyline points="{coords(user)}" class="user"/>
{''.join(labels)}<text x="{(left + right) / 2}" y="{bottom + 48}" text-anchor="middle">동일 시나리오 실행 횟수</text>
<text x="18" y="{(top + bottom) / 2}" transform="rotate(-90 18 {(top + bottom) / 2})" text-anchor="middle">{html.escape(metric_label)}</text>
<line x1="{right - 220}" y1="24" x2="{right - 190}" y2="24" class="skill"/><text x="{right - 182}" y="28">터틀넥</text>
<line x1="{right - 105}" y1="24" x2="{right - 75}" y2="24" class="user"/><text x="{right - 67}" y="28">사용자 브라우저</text>
</svg>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, nargs="+", required=True,
                        help="traffic_profile.py 비교 결과 JSON(같은 시나리오, 실행 순서대로)")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metric", choices=("bodyBytesLowerBound", "requests"),
                        default="bodyBytesLowerBound")
    args = parser.parse_args()
    comparisons = [json.loads(path.read_text(encoding="utf-8")) for path in args.input]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_svg(comparisons, args.metric), encoding="utf-8")
    print(f"트래픽 곡선 저장 완료 · {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

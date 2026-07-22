"""런타임별 result_*.json을 모아 비교표를 만든다.

benchmark.sh는 한 번에 한 런타임만 측정해 result_<runtime>.json을 남긴다.
이 스크립트는 한 디렉터리 안의 result_*.json을 모두 읽어 7.17 저널 매트릭 표 형태로
나란히 놓는다. 실험군이 하나뿐이어도(예: pytorch만 돌린 경우) 그 하나를 표로 낸다.

Usage:
    python bench_report.py --result-dir runs/onnx_bench/exp
"""

import argparse
import json
import unicodedata
from pathlib import Path

ORDER = ["pytorch", "onnx"]  # 표에서 왼쪽부터의 순서 (기준 = 첫 번째)


def _w(s) -> int:
    """표시 폭. 한글·전각 문자는 두 칸이므로 len()으로는 정렬이 깨진다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, width: int) -> str:
    return str(s) + " " * max(0, width - _w(s))


def load_results(result_dir: Path) -> dict:
    arms = {}
    for f in sorted(result_dir.glob("result_*.json")):
        d = json.loads(f.read_text())
        arms[d.get("runtime", f.stem)] = d
    # pytorch, onnx 순으로 정렬 (없는 건 건너뜀)
    ordered = {k: arms[k] for k in ORDER if k in arms}
    for k in arms:  # ORDER에 없는 런타임도 뒤에 붙임
        ordered.setdefault(k, arms[k])
    return ordered


def g(d: dict, *keys, default="-"):
    """중첩 dict 안전 조회. 값이 None이면 default."""
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return default if d is None else d


def render(arms: dict) -> str:
    names = list(arms)
    sections = [
        ("── 속도 ──", [
            ("추론 평균(ms)", lambda a: g(a, "speed", "mean_ms")),
            ("추론 p50(ms)", lambda a: g(a, "speed", "p50_ms")),
            ("추론 p95(ms)", lambda a: g(a, "speed", "p95_ms")),
            ("추론 p99(ms)", lambda a: g(a, "speed", "p99_ms")),
            ("추론 표준편차", lambda a: g(a, "speed", "std_ms")),
            ("전처리(ms)", lambda a: g(a, "speed", "preprocess_ms")),
            ("NMS(ms)", lambda a: g(a, "speed", "nms_ms")),
            ("전체 합(ms)", lambda a: g(a, "speed", "total_ms")),
            ("추론 FPS", lambda a: g(a, "speed", "fps")),
        ]),
        ("── 정확도 ──", [
            ("mAP@0.5", lambda a: g(a, "accuracy", "map50")),
            ("mAP@0.5:0.95", lambda a: g(a, "accuracy", "map50_95")),
            ("APs(소형)", lambda a: g(a, "accuracy", "ap_small")),
            ("car AP", lambda a: g(a, "accuracy", "car_ap")),
            ("정확도 출처", lambda a: g(a, "accuracy", "source", default=g(a, "accuracy", "status"))),
        ]),
        ("── 자원 ──", [
            ("CPU 평균(%)", lambda a: g(a, "resource", "cpu_percent_mean")),
            ("RAM peak(MB)", lambda a: g(a, "resource", "ram_rss_peak_mb")),
            ("GPU util 평균(%)", lambda a: g(a, "resource", "gpu_util_mean_percent")),
            ("VRAM peak(MB)", lambda a: g(a, "resource", "vram_peak_mb")),
            ("자원 샘플 수", lambda a: g(a, "resource", "samples")),
        ]),
        ("── 부가 ──", [
            ("모델 크기(MB)", lambda a: g(a, "extra", "model_size_mb")),
            ("빌드 시간(s)", lambda a: g(a, "extra", "build_time_s")),
            ("측정 이미지", lambda a: g(a, "config", "num_images")),
        ]),
    ]

    w0 = 22
    w = max(max(_w(n) for n in names), 14) + 2
    bar = "─" * (w0 + w * len(names))
    out = ["", bar, _pad("항목", w0) + "".join(_pad(arms[n].get("engine", n), w) for n in names), bar]
    for title, rows in sections:
        out.append(_pad(title, w0))
        for label, fn in rows:
            out.append(_pad("  " + label, w0) + "".join(_pad(fn(arms[n]), w) for n in names))
    out.append(bar)

    # 기준(첫 런타임) 대비 배속
    base = names[0]
    bm = g(arms[base], "speed", "mean_ms", default=None)
    if bm not in (None, "-") and len(names) > 1:
        out.append("")
        for n in names[1:]:
            cm = g(arms[n], "speed", "mean_ms", default=None)
            if cm not in (None, "-"):
                out.append(f"  {arms[n].get('engine', n)} vs {arms[base].get('engine', base)}: "
                           f"추론 {bm / cm:.2f}배")

    out.append("")
    out.append(check_detections(arms))
    return "\n".join(out)


def check_detections(arms: dict) -> str:
    """런타임 간 검출 결과 동등성. 라벨 없이 하는 최소 정확도 검증.

    같은 이미지를 같은 순서로 detect.py에 넣었을 때 엔진만 바꿨는데 검출이 달라지면
    변환이 어긋난 것이다. 이미지 수·순서가 같아야 성립하므로 같은 --data-dir로 돌린
    결과끼리만 의미가 있다.
    """
    names = list(arms)
    if len(names) < 2:
        return "검출 대조: 실험군이 하나뿐이라 생략"
    base = names[0]
    base_d = arms[base].get("detections", [])
    lines = []
    for n in names[1:]:
        other = arms[n].get("detections", [])
        if not base_d or not other:
            lines.append(f"검출 대조 {n} vs {base}: 검출 기록 없음")
            continue
        if len(base_d) != len(other):
            lines.append(f"검출 대조 {n} vs {base}: 이미지 수 불일치 ({len(other)} vs {len(base_d)}) ⚠ "
                         f"(같은 --data-dir 인지 확인)")
            continue
        diff = [i for i, (x, y) in enumerate(zip(base_d, other)) if x != y]
        if not diff:
            lines.append(f"검출 대조 {n} vs {base}: 전체 {len(other)}장 동일 ✓")
        else:
            lines.append(f"검출 대조 {n} vs {base}: {len(diff)}/{len(other)}장 상이 ⚠")
            for i in diff[:3]:
                lines.append(f"    [{i}] {base}={base_d[i]!r}  {n}={other[i]!r}")
            if len(diff) > 3:
                lines.append(f"    ... 외 {len(diff) - 3}건")
    return "\n".join(lines)


def main(a):
    result_dir = Path(a.result_dir)
    arms = load_results(result_dir)
    if not arms:
        raise SystemExit(f"result_*.json 이 없습니다: {result_dir}\n"
                         f"  먼저 ./benchmark.sh --runtime pytorch|onnx 를 실행하세요.")
    print(render(arms))
    summary = {"result_dir": str(result_dir), "runtimes": list(arms)}
    (result_dir / "report.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[info] 실험군: {', '.join(arms)}")


def parse_args():
    p = argparse.ArgumentParser(description="result_*.json 취합 비교 리포트")
    p.add_argument("--result-dir", required=True, help="result_<runtime>.json 이 있는 디렉터리")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

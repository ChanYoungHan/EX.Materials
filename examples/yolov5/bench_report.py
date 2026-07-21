"""detect.py 로그를 파싱해 A/B 비교표를 만든다.

계측기를 새로 만들지 않고 detect.py가 이미 출력하는 값을 읽는다. 비교 대상과
계측 코드가 동일해야 두 실험군의 숫자가 같은 의미를 갖기 때문이다.

detect.py가 내보내는 두 종류의 줄:

  1) 이미지별 (detect.py:316)
       image 3/20 /path/bus.jpg: 640x480 4 persons, 1 bus, 112.4ms
     -> 끝의 숫자가 그 이미지의 추론 시간(dt[1], 전처리·NMS 제외)

  2) 요약 (detect.py:320)
       Speed: 1.2ms pre-process, 110.5ms inference, 2.3ms NMS per image at shape (1, 3, 640, 640)
     -> 세 구간의 이미지당 평균

이미지별 값이 있으므로 평균뿐 아니라 p50/p95/p99와 표준편차까지 낼 수 있다.
첫 N장은 워밍업으로 버린다 — detect.py의 warmup()은 CPU에서 동작하지 않아
첫 추론에 커널 초기화 비용이 섞인다.

Usage:
    python bench_report.py --log-dir runs/onnx_bench/exp --warmup 3
"""

import argparse
import json
import re
import statistics
import unicodedata
from pathlib import Path

# "image 1/20 /path/0000.jpg: 640x640 4 persons, 1 bus, 112.4ms"
# "image 5/20 /path/0004.jpg: 640x640 (no detections), 98.1ms"
RE_PER_IMAGE = re.compile(
    r"^(?:image|video)\s+\d+/\d+\s+(?P<path>.*?):\s+"
    r"(?P<shape>\d+x\d+)\s+(?P<dets>.*?)(?P<ms>[0-9]+\.[0-9]+)ms\s*$"
)
# "Speed: 1.2ms pre-process, 110.5ms inference, 2.3ms NMS per image at shape (1, 3, 640, 640)"
RE_SPEED = re.compile(
    r"Speed:\s*([0-9.]+)ms pre-process,\s*([0-9.]+)ms inference,\s*([0-9.]+)ms NMS"
)


def parse_log(text: str, warmup: int) -> dict:
    per_image, detections, speed = [], [], None
    for line in text.splitlines():
        line = line.strip()
        m = RE_PER_IMAGE.match(line)
        if m:
            per_image.append(float(m.group("ms")))
            # "4 persons, 1 bus, " -> "4 persons, 1 bus" (A/B 검출 동등성 대조용)
            detections.append(m.group("dets").strip().rstrip(","))
            continue
        m = RE_SPEED.search(line)
        if m:
            speed = {
                "preprocess_ms": float(m.group(1)),
                "inference_ms": float(m.group(2)),
                "nms_ms": float(m.group(3)),
            }

    result = {
        "images_parsed": len(per_image),
        "warmup_dropped": 0,
        "detect_py_speed": speed,   # detect.py가 직접 계산한 평균 (교차 검증용)
        "detections": detections,
        "inference": None,
    }

    kept = per_image[warmup:] if len(per_image) > warmup else per_image
    result["warmup_dropped"] = len(per_image) - len(kept)
    if not kept:
        return result

    s = sorted(kept)

    def pct(q):
        return round(s[min(int(len(s) * q), len(s) - 1)], 2)

    result["inference"] = {
        "n": len(kept),
        "mean_ms": round(statistics.fmean(s), 2),
        "p50_ms": pct(0.50),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "min_ms": round(s[0], 2),
        "max_ms": round(s[-1], 2),
        "std_ms": round(statistics.pstdev(s), 2) if len(s) > 1 else 0.0,
        "fps": round(1000.0 / statistics.fmean(s), 2),
    }
    return result


def total_ms(arm: dict):
    """전처리 + 추론 + NMS. 실제 처리량은 이 합으로 결정된다."""
    sp = arm.get("detect_py_speed")
    if not sp:
        return None
    return round(sp["preprocess_ms"] + sp["inference_ms"] + sp["nms_ms"], 2)


def _w(s: str) -> int:
    """표시 폭. 한글·전각 문자는 두 칸을 차지하므로 len()으로는 정렬이 깨진다."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in str(s))


def _pad(s, width: int) -> str:
    return str(s) + " " * max(0, width - _w(s))


def render_table(arms: dict) -> str:
    names = list(arms)
    rows = [
        ("엔진", lambda a: a["meta"]["engine"]),
        ("모델 크기(MB)", lambda a: a["meta"].get("model_size_mb", "-")),
        ("측정 이미지", lambda a: a["inference"]["n"] if a["inference"] else "-"),
        ("추론 평균(ms)", lambda a: a["inference"]["mean_ms"] if a["inference"] else "-"),
        ("추론 p50(ms)", lambda a: a["inference"]["p50_ms"] if a["inference"] else "-"),
        ("추론 p95(ms)", lambda a: a["inference"]["p95_ms"] if a["inference"] else "-"),
        ("추론 p99(ms)", lambda a: a["inference"]["p99_ms"] if a["inference"] else "-"),
        ("추론 표준편차", lambda a: a["inference"]["std_ms"] if a["inference"] else "-"),
        ("전처리(ms)", lambda a: (a["detect_py_speed"] or {}).get("preprocess_ms", "-")),
        ("NMS(ms)", lambda a: (a["detect_py_speed"] or {}).get("nms_ms", "-")),
        ("합계(ms)", lambda a: total_ms(a) or "-"),
        ("추론 FPS", lambda a: a["inference"]["fps"] if a["inference"] else "-"),
        ("총 실행시간(s)", lambda a: a["meta"].get("wall_time_s", "-")),
    ]

    w0 = max(_w(r[0]) for r in rows) + 2
    w = max(max(_w(n) for n in names), 14) + 2
    bar = "─" * ((w0 + w * len(names)) // 2)
    out = ["", bar]
    out.append(_pad("항목", w0) + "".join(_pad(n, w) for n in names))
    out.append(bar)
    for label, fn in rows:
        out.append(_pad(label, w0) + "".join(_pad(fn(arms[n]), w) for n in names))
    out.append(bar)

    # A 대비 배속. 엔진 교체의 효과를 한 줄로 보여준다.
    base = names[0]
    b = arms[base]["inference"]
    if b:
        out.append("")
        for n in names[1:]:
            c = arms[n]["inference"]
            if not c:
                continue
            sp_i = b["mean_ms"] / c["mean_ms"]
            line = f"{n} vs {base}: 추론 {sp_i:.2f}배"
            ta, tb = total_ms(arms[base]), total_ms(arms[n])
            if ta and tb:
                line += f" / 전체(전처리+추론+NMS) {ta / tb:.2f}배"
            out.append("  " + line)

    # 검출 동등성. 속도만 보면 변환이 모델을 망가뜨린 경우를 놓친다.
    out.append("")
    out.append(check_detections(arms))
    return "\n".join(out)


def check_detections(arms: dict) -> str:
    """실험군 간 검출 결과가 같은지 확인한다.

    라벨 없이도 할 수 있는 최소한의 정확도 검증이다. 엔진만 바꿨는데 검출 내용이
    달라졌다면 변환 과정에서 뭔가 어긋난 것이고, 속도 비교는 의미를 잃는다.
    다만 이것은 동등성 확인일 뿐 정확도(mAP) 측정은 아니다 — 라벨이 필요하다.
    """
    names = list(arms)
    if len(names) < 2:
        return "검출 대조: 실험군이 하나뿐이라 생략"

    base = names[0]
    base_dets = arms[base]["detections"]
    lines = []
    for n in names[1:]:
        other = arms[n]["detections"]
        if len(base_dets) != len(other):
            lines.append(f"검출 대조 {n} vs {base}: 이미지 수 불일치 ({len(other)} vs {len(base_dets)}) ⚠")
            continue
        diff = [i for i, (x, y) in enumerate(zip(base_dets, other)) if x != y]
        if not diff:
            lines.append(f"검출 대조 {n} vs {base}: 전체 {len(other)}장 동일 ✓")
        else:
            lines.append(f"검출 대조 {n} vs {base}: {len(diff)}/{len(other)}장 상이 ⚠")
            for i in diff[:3]:
                lines.append(f"    [{i}] {base}={base_dets[i]!r}  {n}={other[i]!r}")
            if len(diff) > 3:
                lines.append(f"    ... 외 {len(diff) - 3}건")
    return "\n".join(lines)


def main(a):
    log_dir = Path(a.log_dir)
    manifest_path = log_dir / "arms.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"arms.json이 없습니다: {manifest_path}")
    arms_meta = json.loads(manifest_path.read_text())

    arms = {}
    for name, meta in arms_meta.items():
        log_file = log_dir / f"{name}.log"
        if not log_file.exists():
            print(f"[warn] 로그 없음, 건너뜀: {log_file}")
            continue
        parsed = parse_log(log_file.read_text(errors="replace"), a.warmup)
        parsed["meta"] = meta
        arms[name] = parsed

    if not arms:
        raise RuntimeError("파싱된 실험군이 없습니다.")

    report = {"log_dir": str(log_dir), "warmup_dropped": a.warmup, "arms": arms}
    (log_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print(render_table(arms))
    print(f"\n[info] 상세: {log_dir / 'report.json'}")


def parse_args():
    p = argparse.ArgumentParser(description="detect.py 로그 기반 A/B 비교 리포트")
    p.add_argument("--log-dir", required=True)
    p.add_argument("--warmup", type=int, default=3, help="앞에서 버릴 이미지 수")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

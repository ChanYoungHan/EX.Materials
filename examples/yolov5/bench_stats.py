"""원본 latency CSV → 추론시간 통계 → result_<runtime>.json의 speed에 병합.

detect.py가 이미지별로 남긴 추론시간(원본 5000행)을 읽어 통계를 낸다. 추론과 분리돼
있으므로, 워밍업 개수를 바꾸거나 통계를 다시 뽑을 때 재추론 없이 이 스크립트만 재실행하면 된다.

CSV는 bench_run.py가 만든 <runtime>_latency.csv (columns: index,image,inference_ms,detections).

Usage (보통 benchmark.sh가 호출):
    python bench_stats.py --csv runs/.../onnx_latency.csv \
        --result runs/.../result_onnx.json --warmup 3

    # 워밍업만 바꿔 재집계 (재추론 불필요):
    python bench_stats.py --csv runs/.../onnx_latency.csv --result ... --warmup 50
"""

import argparse
import csv
import json
import statistics
from pathlib import Path


def compute(latencies: list, warmup: int) -> dict:
    """이미지별 추론시간 리스트 → 통계.

    앞 warmup개는 버린다 — 첫 추론들은 커널 초기화/메모리 할당 때문에 느려 분포를 왜곡한다.
    """
    kept = latencies[warmup:] if len(latencies) > warmup else latencies
    if not kept:
        return {"n": 0, "warmup_dropped": len(latencies), "error": "표본 없음"}

    s = sorted(kept)
    pct = lambda q: round(s[min(int(len(s) * q), len(s) - 1)], 3)
    mean = statistics.fmean(s)
    return {
        "n": len(kept),
        "warmup_dropped": len(latencies) - len(kept),
        "mean_ms": round(mean, 3),
        "std_ms": round(statistics.pstdev(s), 3) if len(s) > 1 else 0.0,
        "min_ms": round(s[0], 3),
        "max_ms": round(s[-1], 3),
        "p50_ms": pct(0.50),
        "p90_ms": pct(0.90),
        "p95_ms": pct(0.95),
        "p99_ms": pct(0.99),
        "fps": round(1000.0 / mean, 2),
    }


def load_latencies(csv_path: Path) -> list:
    with csv_path.open(newline="") as f:
        return [float(row["inference_ms"]) for row in csv.DictReader(f)]


def main(a):
    csv_path = Path(a.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV 없음: {csv_path}")
    lat = load_latencies(csv_path)
    stats = compute(lat, a.warmup)

    # result JSON의 speed에 병합. bench_run.py가 넣어둔 전처리·NMS 스칼라와 합쳐 완성한다.
    if a.result:
        rp = Path(a.result)
        result = json.loads(rp.read_text()) if rp.exists() else {}
        speed = result.get("speed") or {}
        speed.update(stats)
        pre, nms = speed.get("preprocess_ms"), speed.get("nms_ms")
        if pre is not None and nms is not None and stats.get("mean_ms") is not None:
            speed["total_ms"] = round(pre + stats["mean_ms"] + nms, 3)
        result["speed"] = speed
        rp.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"[stats] result 갱신: {rp}")

    print(json.dumps(stats, indent=2, ensure_ascii=False))


def parse_args():
    p = argparse.ArgumentParser(description="latency CSV → 추론시간 통계 (→ result JSON 병합)")
    p.add_argument("--csv", required=True, help="bench_run.py가 만든 <runtime>_latency.csv")
    p.add_argument("--result", default=None, help="병합 대상 result_<runtime>.json (생략 시 출력만)")
    p.add_argument("--warmup", type=int, default=3, help="앞에서 버릴 이미지 수")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

"""detect.py/val.py 로그 → 원본 per-image CSV + result_<runtime>.json (통계 제외).

benchmark.sh가 detect.py/val.py를 실행해 남긴 로그를 파싱한다. 하는 일:
  - 속도 원본: detect.py의 이미지별 추론시간을 가공 없이 <runtime>_latency.csv에 저장.
    (5000장이면 5000행.) 통계는 bench_stats.py가 이 CSV를 읽어 따로 계산한다 —
    추론과 분리돼 있어 워밍업 개수를 바꾸거나 다시 집계할 때 재추론이 필요 없다.
  - 정확도: val.py native mAP를 파싱.
  - 부가: 모델 크기, 빌드 시간(export manifest).

서브프로세스를 띄우지 않는다 — 순수 텍스트 파싱. 속도 "통계"는 여기서 내지 않는다.
"""

import argparse
import csv
import json
import re
from pathlib import Path

# --- detect.py 출력 (detect.py:316·320) ---
RE_PER_IMAGE = re.compile(
    r"^(?:image|video)\s+\d+/\d+\s+(?P<path>.*?):\s+"
    r"\d+x\d+\s+(?P<dets>.*?)(?P<ms>[0-9]+\.[0-9]+)ms\s*$"
)
RE_SPEED = re.compile(
    r"Speed:\s*([0-9.]+)ms pre-process,\s*([0-9.]+)ms inference,\s*([0-9.]+)ms NMS"
)
# --- val.py 출력 ---
# "                   all        128        929      0.717      0.635      0.712      0.475"
RE_VAL_ROW = re.compile(
    r"^\s*(?P<name>\S+)\s+(?P<images>\d+)\s+(?P<inst>\d+)\s+"
    r"(?P<p>[-0-9.]+)\s+(?P<r>[-0-9.]+)\s+(?P<map50>[-0-9.]+)\s+(?P<map>[-0-9.]+)\s*$"
)
# ── 추후개발(케이스 A): pycocotools 소형객체 APs 파싱 ──────────────────────────
# RE_COCO_APS = re.compile(r"Average Precision.*IoU=0\.50:0\.95.*area=\s*small.*=\s*([-0-9.]+)")


def parse_detect(text: str):
    """이미지별 (index, image, inference_ms, detections) 원본 행 + Speed 평균줄."""
    rows, speed = [], None
    for line in text.splitlines():
        line = line.strip()
        m = RE_PER_IMAGE.match(line)
        if m:
            rows.append((len(rows), Path(m.group("path")).name,
                         float(m.group("ms")), m.group("dets").strip().rstrip(",")))
            continue
        m = RE_SPEED.search(line)
        if m:
            # 전처리·NMS는 이미 이미지당 평균값(스칼라)이라 통계 대상이 아니다.
            speed = {"preprocess_ms": float(m.group(1)), "nms_ms": float(m.group(3))}
    return rows, speed


def parse_accuracy(text: str, target_class: str = "car") -> dict:
    """val.py 출력에서 native mAP를 뽑는다 (케이스 B).

    ap_small(소형객체 APs)은 pycocotools 전용이라 지금은 None (추후개발: 케이스 A).
    """
    all_row, class_ap = None, None
    for line in text.splitlines():
        m = RE_VAL_ROW.match(line)
        if m:
            if m.group("name") == "all":
                all_row = {"map50": float(m.group("map50")), "map50_95": float(m.group("map"))}
            elif m.group("name") == target_class:
                class_ap = float(m.group("map"))  # 마지막 열 = AP@0.5:0.95
    if all_row:
        return {"status": "ok", "source": "val.py",
                "map50_95": all_row["map50_95"], "map50": all_row["map50"],
                "ap_small": None, f"{target_class}_ap": class_ap}
    return {"status": "no_metrics", "reason": "val.py 출력에서 mAP를 찾지 못함 (라벨 없음?)"}


def read_build_time(weights: Path):
    """export manifest가 있으면 빌드 시간을 읽는다 (onnx 전용). 없으면 None."""
    mani = Path(f"{weights}.manifest.json")
    if mani.exists():
        try:
            return json.loads(mani.read_text())["export"].get("elapsed_s")
        except Exception:
            return None
    return None


def main(a):
    weights = Path(a.weights).resolve()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)

    rows, speed_avg = parse_detect(Path(a.detect_log).read_text(errors="replace"))

    # 원본 저장 — 통계는 bench_stats.py가 이 파일에서 낸다.
    csv_path = outdir / f"{a.runtime}_latency.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["index", "image", "inference_ms", "detections"])
        w.writerows(rows)

    if a.val_log and Path(a.val_log).exists():
        accuracy = parse_accuracy(Path(a.val_log).read_text(errors="replace"), a.target_class)
    else:
        accuracy = {"status": "skipped", "reason": "YOLO 라벨 미제공 (정확도 측정 불가)"}

    engine_name = {"pytorch": "PyTorch", "onnx": "ONNX Runtime", "trt": "TensorRT"}
    result = {
        "runtime": a.runtime,
        "engine": engine_name.get(a.runtime, a.runtime),
        "weights": str(weights),
        "repo_commit": a.commit,
        "config": {
            "imgsz": a.imgsz, "device": a.device, "conf": a.conf, "iou": a.iou,
            "num_images": len(rows),
        },
        # speed 통계는 bench_stats.py가 채운다. 여기선 스칼라 평균만 미리 담아둔다.
        "speed": speed_avg or {"preprocess_ms": None, "nms_ms": None},
        "accuracy": accuracy,
        "extra": {
            "model_size_mb": round(weights.stat().st_size / 1e6, 2) if weights.exists() else None,
            "build_time_s": read_build_time(weights),
        },
        "latency_csv": csv_path.name,
    }
    (outdir / f"result_{a.runtime}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[bench] 원본: {csv_path}  ({len(rows)}행)")
    print(f"[bench] 메타: {outdir / f'result_{a.runtime}.json'}  (통계는 bench_stats.py가 채움)")


def parse_args():
    p = argparse.ArgumentParser(description="detect.py/val.py 로그 → 원본 CSV + result JSON")
    p.add_argument("--runtime", choices=["pytorch", "onnx", "trt"], required=True)
    p.add_argument("--weights", required=True)
    p.add_argument("--detect-log", required=True, help="detect.py 출력 로그 (속도 원본)")
    p.add_argument("--val-log", default=None, help="val.py 출력 로그 (정확도, 없으면 생략)")
    p.add_argument("--commit", default=None, help="레포 커밋 SHA (기록용)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="cpu")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--target-class", default="car", help="단독 AP를 뽑을 관심 클래스")
    p.add_argument("--out", required=True, help="결과 디렉터리")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

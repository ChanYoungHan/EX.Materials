"""단일 런타임 벤치마크 러너.

benchmark.sh가 환경(pyenv·레포·의존성)을 준비한 뒤 이 스크립트를 호출한다.
하나의 런타임(.pt 또는 .onnx)에 대해 7.17 저널 매트릭 표를 채운다:

  속도   : detect.py를 이미지 폴더에 실행 → 이미지별 추론시간 파싱 → 평균/p50/p95/p99/FPS
  자원   : 그 detect.py 프로세스를 폴링 → CPU%/RSS peak, GPU util 평균, VRAM peak
  정확도 : (라벨 데이터셋이 있으면) val.py --save-json → pycocotools mAP@0.5:0.95, APs, car AP
  부가   : 모델 크기(파일), 빌드 시간(export manifest), 로드 시간

추론·정확도 계산은 전부 레퍼런스(detect.py/val.py)가 한다. 이 스크립트가 새로 하는 것은
서브프로세스를 감싼 자원 샘플링과 로그 파싱뿐이다 — 레퍼런스에 없는 부분만 채운다.

결과는 result_<runtime>.json 한 개. bench_report.py가 여러 런타임의 result를 모아 비교한다.

Usage (보통 benchmark.sh가 호출):
    python bench_run.py --runtime pytorch --weights yolov5s.pt --repo /tmp/yolov5-export/yolov5 \
        --data-dir ./images --out runs/onnx_bench/exp
"""

import argparse
import json
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path

# --- detect.py 출력 (models/common.py, detect.py:316·320 참조) ---
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
# pycocotools 12줄 요약 중 필요한 것
RE_COCO_MAP = re.compile(r"Average Precision.*IoU=0\.50:0\.95.*area=\s*all.*=\s*([-0-9.]+)")
RE_COCO_MAP50 = re.compile(r"Average Precision.*IoU=0\.50\s.*area=\s*all.*=\s*([-0-9.]+)")
RE_COCO_APS = re.compile(r"Average Precision.*IoU=0\.50:0\.95.*area=\s*small.*=\s*([-0-9.]+)")


# ----------------------------------------------------------------- 자원 샘플러
class ResourceMonitor:
    """서브프로세스(+자식)를 주기 폴링. psutil/pynvml 없으면 조용히 비활성.

    추론 코드를 건드리지 않고 자원을 재는 유일한 방법이다. detect.py가 도는 동안
    별도 스레드에서 프로세스 트리의 CPU/RSS와 GPU 전체의 util/VRAM을 샘플링한다.
    (GPU 지표는 프로세스 단위가 아니라 장치 전체 값 — 단독 벤치 환경 가정.)
    """

    def __init__(self, pid: int, interval: float = 0.1):
        self.pid = pid
        self.interval = interval
        self.cpu, self.rss, self.gpu, self.vram = [], [], [], []
        self._stop = threading.Event()
        self._thread = None

        try:
            import psutil
            self.psutil = psutil
            self.proc = psutil.Process(pid)
            self.proc.cpu_percent(None)  # 첫 호출은 0 — 프라이밍
        except Exception:
            self.psutil = None

        try:
            import pynvml
            pynvml.nvmlInit()
            self.nvml = pynvml
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            self.nvml = None

    def _procs(self):
        try:
            return [self.proc] + self.proc.children(recursive=True)
        except Exception:
            return []

    def _loop(self):
        while not self._stop.wait(self.interval):
            if self.psutil:
                c = r = 0.0
                for p in self._procs():
                    try:
                        c += p.cpu_percent(None)
                        r += p.memory_info().rss
                    except Exception:
                        pass
                self.cpu.append(c)
                self.rss.append(r / 1e6)
            if self.nvml:
                try:
                    self.gpu.append(self.nvml.nvmlDeviceGetUtilizationRates(self.handle).gpu)
                    self.vram.append(self.nvml.nvmlDeviceGetMemoryInfo(self.handle).used / 1e6)
                except Exception:
                    pass

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def report(self) -> dict:
        return {
            "cpu_percent_mean": round(statistics.fmean(self.cpu), 1) if self.cpu else None,
            "ram_rss_peak_mb": round(max(self.rss), 1) if self.rss else None,
            "gpu_util_mean_percent": round(statistics.fmean(self.gpu), 1) if self.gpu else None,
            "vram_peak_mb": round(max(self.vram), 1) if self.vram else None,
            "gpu_available": self.nvml is not None,
            "samples": len(self.cpu) or len(self.gpu),
        }


def run_and_sample(cmd: list, cwd: str, sample_interval: float):
    """서브프로세스를 실행하며 자원을 샘플링. (stdout, 자원리포트, wall초)를 반환."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, errors="replace")
    with ResourceMonitor(proc.pid, sample_interval) as mon:
        out, _ = proc.communicate()
    wall = time.perf_counter() - t0
    return out, proc.returncode, mon.report(), round(wall, 2)


# ------------------------------------------------------------------ 파서
def parse_speed(text: str, warmup: int) -> dict:
    per_image, detections, speed = [], [], None
    for line in text.splitlines():
        line = line.strip()
        m = RE_PER_IMAGE.match(line)
        if m:
            per_image.append(float(m.group("ms")))
            detections.append(m.group("dets").strip().rstrip(","))
            continue
        m = RE_SPEED.search(line)
        if m:
            speed = {"preprocess_ms": float(m.group(1)),
                     "inference_ms": float(m.group(2)), "nms_ms": float(m.group(3))}

    kept = per_image[warmup:] if len(per_image) > warmup else per_image
    result = {"images_parsed": len(per_image), "warmup_dropped": len(per_image) - len(kept),
              "detect_py_speed": speed, "detections": detections[warmup:] if kept else [],
              "latency": None}
    if not kept:
        return result

    s = sorted(kept)
    pct = lambda q: round(s[min(int(len(s) * q), len(s) - 1)], 2)
    mean = statistics.fmean(s)
    total = None
    if speed:
        total = round(speed["preprocess_ms"] + speed["inference_ms"] + speed["nms_ms"], 2)
    result["latency"] = {
        "n": len(kept), "mean_ms": round(mean, 2),
        "p50_ms": pct(0.50), "p95_ms": pct(0.95), "p99_ms": pct(0.99),
        "std_ms": round(statistics.pstdev(s), 2) if len(s) > 1 else 0.0,
        "fps": round(1000.0 / mean, 2),
        "preprocess_ms": speed["preprocess_ms"] if speed else None,
        "nms_ms": speed["nms_ms"] if speed else None,
        "total_ms": total,
    }
    return result


def parse_accuracy(text: str, target_class: str = "car") -> dict:
    """val.py 출력에서 mAP를 뽑는다. pycocotools 결과가 있으면 우선(저널 표준)."""
    all_row, class_ap = None, None
    for line in text.splitlines():
        m = RE_VAL_ROW.match(line)
        if m:
            if m.group("name") == "all":
                all_row = {"map50": float(m.group("map50")), "map50_95": float(m.group("map"))}
            elif m.group("name") == target_class:
                class_ap = float(m.group("map"))  # 마지막 열 = AP@0.5:0.95

    coco = {}
    for pat, key in ((RE_COCO_MAP, "map50_95"), (RE_COCO_MAP50, "map50"), (RE_COCO_APS, "ap_small")):
        mm = pat.search(text)
        if mm:
            coco[key] = float(mm.group(1))

    if coco:
        return {"status": "ok", "source": "pycocotools",
                "map50_95": coco.get("map50_95"), "map50": coco.get("map50"),
                "ap_small": coco.get("ap_small"), f"{target_class}_ap": class_ap}
    if all_row:
        return {"status": "ok", "source": "val.py",
                "map50_95": all_row["map50_95"], "map50": all_row["map50"],
                "ap_small": None, f"{target_class}_ap": class_ap}
    return {"status": "no_metrics", "reason": "val.py 출력에서 mAP를 찾지 못함 (라벨 없음?)"}


# ------------------------------------------------------------------ 부가
def read_build_time(weights: Path):
    """export manifest가 있으면 빌드 시간을 읽는다 (onnx 전용). 없으면 None."""
    mani = Path(f"{weights}.manifest.json")
    if mani.exists():
        try:
            return json.loads(mani.read_text())["export"].get("elapsed_s")
        except Exception:
            return None
    return None


# ------------------------------------------------------------------ 실행
def main(a):
    weights = Path(a.weights).resolve()
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    py = a.python

    # --- 속도 + 자원: detect.py ---
    detect_cmd = [
        py, "detect.py", "--weights", str(weights), "--source", a.data_dir,
        "--imgsz", str(a.imgsz), str(a.imgsz), "--device", a.device,
        "--conf-thres", str(a.conf), "--iou-thres", str(a.iou),
        "--project", str(outdir), "--name", f"{a.runtime}_detect", "--exist-ok", "--nosave",
    ]
    print(f"[bench] 속도·자원 측정: detect.py ({a.runtime})")
    out, rc, resource, wall = run_and_sample(detect_cmd, a.repo, a.sample_interval)
    (outdir / f"{a.runtime}_detect.log").write_text(out)
    if rc != 0:
        print(out[-2000:])
        raise SystemExit(f"detect.py 실패 (rc={rc}) — 로그 확인")
    speed = parse_speed(out, a.warmup)

    # --- 정확도: val.py (라벨 데이터셋이 있을 때만) ---
    if a.data_yaml:
        val_cmd = [
            py, "val.py", "--weights", str(weights), "--data", a.data_yaml,
            "--imgsz", str(a.imgsz), "--device", a.device,
            "--project", str(outdir), "--name", f"{a.runtime}_val", "--exist-ok",
            "--verbose", "--save-json",
        ]
        print(f"[bench] 정확도 측정: val.py ({a.runtime})")
        vout, vrc, _, _ = run_and_sample(val_cmd, a.repo, a.sample_interval)
        (outdir / f"{a.runtime}_val.log").write_text(vout)
        accuracy = parse_accuracy(vout, a.target_class) if vrc == 0 else \
            {"status": "failed", "reason": f"val.py rc={vrc}"}
    else:
        accuracy = {"status": "skipped", "reason": "--data-yaml 미지정 (라벨 데이터셋 미제공)"}

    result = {
        "runtime": a.runtime,
        "engine": "PyTorch" if a.runtime == "pytorch" else "ONNX Runtime",
        "weights": str(weights),
        "repo_commit": a.commit,
        "config": {
            "imgsz": a.imgsz, "device": a.device, "conf": a.conf, "iou": a.iou,
            "data_dir": a.data_dir, "data_yaml": a.data_yaml,
            "num_images": speed["images_parsed"], "warmup_dropped": speed["warmup_dropped"],
        },
        "speed": speed["latency"],
        "resource": resource,
        "accuracy": accuracy,
        "extra": {
            "model_size_mb": round(weights.stat().st_size / 1e6, 2),
            "build_time_s": read_build_time(weights),
            "detect_wall_s": wall,
        },
        "detections": speed["detections"],
    }
    out_json = outdir / f"result_{a.runtime}.json"
    out_json.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(f"[bench] 결과: {out_json}")

    # 요약 한 줄
    lat = speed["latency"]
    if lat:
        print(f"[bench] {a.runtime}: 추론 {lat['mean_ms']}ms (p95 {lat['p95_ms']}), {lat['fps']} FPS"
              f" | mAP {accuracy.get('map50_95', '-')}")


def parse_args():
    p = argparse.ArgumentParser(description="단일 런타임 벤치마크 러너")
    p.add_argument("--runtime", choices=["pytorch", "onnx"], required=True)
    p.add_argument("--weights", required=True)
    p.add_argument("--repo", required=True, help="yolov5 레포 경로 (detect.py/val.py 위치)")
    p.add_argument("--python", default="python", help="사용할 python 인터프리터")
    p.add_argument("--data-dir", required=True, help="속도 측정용 이미지 폴더")
    p.add_argument("--data-yaml", default=None, help="정확도용 라벨 데이터셋 yaml (없으면 정확도 생략)")
    p.add_argument("--commit", default=None, help="레포 커밋 SHA (기록용)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--device", default="cpu")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--warmup", type=int, default=3)
    p.add_argument("--target-class", default="car", help="단독 AP를 뽑을 관심 클래스")
    p.add_argument("--sample-interval", type=float, default=0.1)
    p.add_argument("--out", required=True, help="결과 디렉터리")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

# YOLOv5 ONNX 벤치마크

PyTorch(`.pt`)와 ONNX Runtime(`.onnx`)의 추론 속도·정확도를 COCO val2017에서 비교한다.
추론·평가·변환은 모두 레퍼런스(ultralytics/yolov5의 `detect.py`·`val.py`·`export.py`)가 하고,
이 저장소의 스크립트는 그 실행을 감싸고 로그를 정리할 뿐이다.

전체 흐름: **사전학습 모델 확보 → ONNX 변환 → 벤치마크**

---

## 사전 준비

- **pyenv 가상환경** (기본 이름 `yolov5`). 다른 이름이면 각 스크립트에 `--env <이름>`.
- **git**, 인터넷 (레포를 임시 디렉터리에 클론).
- 스크립트가 yolov5 레포를 `$TMPDIR/yolov5-export`에 캐시하고 필요한 패키지를 설치한다.

---

## 1단계 — 사전학습 모델 확보 + 동작 확인

`yolov5s.pt`는 Ultralytics가 COCO로 학습해 배포한 가중치다. 없으면 받는다.

```bash
# torch.hub로 yolov5s 다운로드 + 샘플 이미지 추론 (동작 확인)
python basic_example.py
```

이미 `yolov5s.pt`가 있으면 이 단계는 건너뛰어도 된다.
(수치가 궁금하면: yolov5s의 COCO mAP@0.5:0.95는 ~0.37, mAP@0.5는 ~0.57 — 정상값이다.)

---

## 2단계 — 모델 변환 (ONNX / TensorRT)

`export.py`를 감싸 `.onnx` 또는 TensorRT `.engine`을 만든다. 산출물은 `.pt`와 같은 위치.

```bash
./export.sh                                  # onnx (cpu) — yolov5s.pt → yolov5s.onnx
./export.sh --format engine --device 0       # TensorRT 엔진 (GPU/Jetson)
./export.sh --format engine --device 0 --half  # FP16 엔진 (Jetson 권장)
./export.sh --format both --device 0         # onnx + engine
./export.sh --no-infer                       # 변환까지만
```

만들어지는 것:
- `yolov5s.onnx` / `yolov5s.engine` — 변환 산출물
- `yolov5s.onnx.manifest.json` — repo 커밋·패키지 버전·실제 opset 등 재현 정보 (onnx일 때)
- 끝에 `infer.py`로 bus.jpg를 한 번 추론해 **변환이 실제로 도는지** 검증 (`--no-infer`로 생략)

> **TensorRT 엔진은 빌드한 그 기기·TRT 버전에서만 동작한다.** Jetson용 엔진은 반드시
> Jetson에서 `./export.sh --format engine`으로 빌드해야 한다(x86에서 만든 `.engine`은 안 됨).
> Jetson은 tensorrt가 시스템 패키지라 pyenv 환경을 `--system-site-packages`로 만들어야 할 수 있다.

> ONNX/TensorRT 그래프에는 letterbox·NMS 전후처리가 없어 `infer.py`가 직접 구현해 검증용으로 쓴다.
> `infer.py`는 확장자로 백엔드를 자동 선택한다: `.pt`(PyTorch) / `.onnx`(ORT) / `.engine`(TensorRT).
> 벤치마크 본체는 이걸 쓰지 않고 레퍼런스 `detect.py`/`val.py`를 쓴다.

---

## 3단계 — COCO 데이터셋 준비 (YOLO 포맷)

벤치마크는 **YOLO 형식 라벨이 필수**다. yolov5 규약대로 배치한다:

```
datasets/coco/
├── images/val2017/*.jpg              # 이미지
├── labels/val2017/*.txt              # [필수] YOLO 라벨 — mAP 계산
├── val2017.txt                        # 이미지 목록 (없으면 자동 생성)
└── annotations/instances_val2017.json # [선택] pycocotools APs (추후개발)
```

받는 방법 (YOLO 라벨 + 이미지를 한 번에):

```bash
# 레포의 data/coco.yaml 다운로드 스크립트가 coco2017labels.zip + val2017.zip을 받는다
python -c "from utils.general import download; \
  download(['https://github.com/ultralytics/assets/releases/download/v0.0.0/coco2017labels.zip'], dir='datasets')"
# 이미지: http://images.cocodataset.org/zips/val2017.zip → datasets/coco/images/val2017/
```

> COCO 공식 다운로드(`val2017.zip` + `annotations_trainval2017.zip`)만 받으면 JSON은 있으나
> **YOLO `.txt` 라벨이 없어** mAP를 못 낸다. 위 yolov5 방식을 써야 라벨까지 갖춰진다.

---

## 4단계 — 벤치마크

한 번에 **한 런타임**만 측정한다. 런타임들을 **같은 `--name`**으로 돌려 결과를 한 폴더에 모은다.
`--runtime`은 `pytorch`(.pt) / `onnx`(.onnx) / `trt`(.engine) 중 하나.

```bash
./benchmark.sh --runtime pytorch --dataset-dir ./datasets/coco --name run1
./benchmark.sh --runtime onnx    --dataset-dir ./datasets/coco --name run1   # --device 0 로 GPU
./benchmark.sh --runtime trt     --dataset-dir ./datasets/coco --name run1   # Jetson (GPU 자동)
```

> **Jetson에서 trt 실행 시**: yolov5 `requirements.txt`에 torch가 있어 의존성 자동 설치가
> 시스템 torch/tensorrt와 충돌할 수 있다. 시스템 패키지를 쓰는 환경(`--system-site-packages`)을
> 미리 만들고 **`--skip-deps`** 로 실행할 것. `.engine`은 그 Jetson에서 `export.sh`로 빌드한 것이어야 한다.

각 실행이 `runs/bench_coco/run1/` 아래에 남기는 것:

| 파일 | 내용 |
|---|---|
| `result_<runtime>.json` | **요약** — 속도 통계·mAP·모델 크기 |
| `<runtime>_latency.csv` | **원본** — 이미지별 추론시간 (5000행) |
| `<runtime>_detect.log`, `<runtime>_val.log` | detect.py / val.py 원본 로그 |

### 파이프라인 (내부)

```
detect.py (이미지별 추론시간) ┐
                              ├→ bench_run.py (로그 → CSV + result JSON)
val.py (native mAP)          ┘        └→ bench_stats.py (CSV → 통계 → result JSON에 병합)
```

---

## 결과 읽기

`result_<runtime>.json`의 핵심:

```json
{
  "speed":    { "mean_ms": 77.8, "p50_ms": 77.7, "p95_ms": 81.6, "p99_ms": 82.0, "fps": 12.85 },
  "accuracy": { "map50": 0.565, "map50_95": 0.371, "car_ap": 0.40, "ap_small": null },
  "extra":    { "model_size_mb": 28.3, "build_time_s": 17 }
}
```

- **속도**: `mean_ms`(평균), `p95/p99_ms`(꼬리 지연), `fps`. batch=1 기준.
- **정확도**: `map50`(IoU≥0.5 기준), `map50_95`(IoU 0.5~0.95 평균, COCO 표준). `ap_small`은 추후개발.
- **비교**: `result_pytorch.json`과 `result_onnx.json`을 나란히 보거나 LLM에 넘겨 "onnx vs pytorch 트레이드오프"를 정리한다. (별도 리포트 스크립트는 두지 않음.)

### 통계 재집계 (재추론 없이)

워밍업 개수만 바꿔 통계를 다시 낼 때는 CSV만 다시 읽으면 된다.

```bash
python bench_stats.py --csv runs/bench_coco/run1/onnx_latency.csv \
                      --result runs/bench_coco/run1/result_onnx.json --warmup 50
```

---

## 파일 구성

| 파일 | 역할 |
|---|---|
| `export.sh` | `.pt` → `.onnx` / TensorRT `.engine` 변환 (export.py 래핑) |
| `infer.py` | 단독 추론 검증 — `.pt`/`.onnx`/`.engine` 자동 선택 (변환 검증용) |
| `benchmark.sh` | 한 런타임 측정 오케스트레이션 |
| `bench_run.py` | detect.py/val.py 로그 → CSV + result JSON |
| `bench_stats.py` | 원본 CSV → 추론시간 통계 |
| `_common.sh` | pyenv·레포 클론 공통 유틸 |

---

## 참고 / 추후개발

- **자원 모니터링**(CPU/GPU/RAM)은 스크립트에서 제외. 지금은 외부 도구로 관찰:
  `htop`, `nvidia-smi -l 1`, `pidstat -u -r -C python 1 > usage.log`.
- **정확도 APs**(소형객체, pycocotools): COCO json 경로(케이스 A)는 코드에 주석으로 남겨둠.
- **INT8 양자화**: `.onnx`를 정적 양자화(캘리브레이션)해 만든 뒤 `--onnx <int8>.onnx`로 측정하면 됨(양자화 스크립트는 미구현).
- **dynamic/half**: 이 벤치마크는 batch=1·640 고정이라 쓰지 않는다. `--half`는 GPU 전용이며 `--dynamic`과 배타.

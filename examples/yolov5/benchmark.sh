#!/usr/bin/env bash
#
# 단일 런타임 벤치마크 — 7.17 저널 매트릭(속도·자원·정확도·부가)
#
# 한 번에 하나의 런타임만 측정한다. 결과는 result_<runtime>.json 한 개로 떨어지고,
# bench_report.py가 여러 런타임의 result를 모아 비교표를 만든다. 이 구조라면
# "GPU 서버에서 onnx, 노트북에서 pytorch"처럼 따로 돌린 결과도 나중에 합칠 수 있다.
#
# 측정 자체는 레퍼런스가 한다:
#   속도·자원 : detect.py (이미지 폴더) + 프로세스 자원 폴링
#   정확도    : val.py --save-json (라벨 데이터셋 있을 때, pycocotools mAP)
#
# 사용법:
#   ./benchmark.sh --runtime pytorch --data-dir ./images
#   ./benchmark.sh --runtime onnx    --data-dir ./images --data-yaml ./datasets/coco.yaml
#   ./benchmark.sh --runtime onnx    --data-dir ./val2017 --device 0
#   # 두 런타임을 같은 폴더에 모으면 리포트가 자동 비교:
#   ./benchmark.sh --runtime pytorch --data-dir ./img --name run1
#   ./benchmark.sh --runtime onnx    --data-dir ./img --name run1   # 같은 --name
#   python bench_report.py --result-dir runs/onnx_bench/run1
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_TAG="bench"
# shellcheck source=_common.sh
source "${HERE}/_common.sh"

# ------------------------------------------------------------------ 기본값
PYENV_ENV="yolov5"
REPO_URL="https://github.com/ultralytics/yolov5.git"
REPO_REF="master"
CACHE_DIR="${TMPDIR:-/tmp}/yolov5-export"
RUNTIME=""
PT_WEIGHTS="${HERE}/yolov5s.pt"
ONNX_WEIGHTS="${HERE}/yolov5s.onnx"
DATA_DIR=""
DATA_YAML=""
IMGSZ=640
DEVICE="cpu"
CONF=0.25
IOU=0.45
WARMUP=3
TARGET_CLASS="car"
PROJECT="${HERE}/runs/onnx_bench"
NAME="exp"
FRESH=0
SKIP_DEPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)   RUNTIME="$2"; shift 2 ;;
    --env)       PYENV_ENV="$2"; shift 2 ;;
    --ref)       REPO_REF="$2"; shift 2 ;;
    --pt)        PT_WEIGHTS="$2"; shift 2 ;;
    --onnx)      ONNX_WEIGHTS="$2"; shift 2 ;;
    --data-dir)  DATA_DIR="$2"; shift 2 ;;
    --data-yaml) DATA_YAML="$2"; shift 2 ;;
    --imgsz)     IMGSZ="$2"; shift 2 ;;
    --device)    DEVICE="$2"; shift 2 ;;
    --conf)      CONF="$2"; shift 2 ;;
    --iou)       IOU="$2"; shift 2 ;;
    --warmup)    WARMUP="$2"; shift 2 ;;
    --target-class) TARGET_CLASS="$2"; shift 2 ;;
    --project)   PROJECT="$2"; shift 2 ;;
    --name)      NAME="$2"; shift 2 ;;
    --cache-dir) CACHE_DIR="$2"; shift 2 ;;
    --fresh)     FRESH=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    -h|--help)   sed -n '2,30p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)           die "알 수 없는 인자: $1" ;;
  esac
done

# ------------------------------------------------------------------ 인자 검증
case "$RUNTIME" in
  pytorch) WEIGHTS="$PT_WEIGHTS" ;;
  onnx)    WEIGHTS="$ONNX_WEIGHTS" ;;
  "")      die "--runtime 가 필요합니다. pytorch 또는 onnx 를 지정하세요." ;;
  *)       die "알 수 없는 런타임: $RUNTIME (pytorch|onnx)" ;;
esac
[[ -f "$WEIGHTS" ]] || die "가중치 없음: $WEIGHTS  ${RUNTIME}=onnx 라면 먼저 ./export_onnx.sh 실행"

# 데이터셋 필수 — 준비 전 실행으로 의미 없는 숫자를 얻는 상황을 막는다.
[[ -n "$DATA_DIR" ]] || die "--data-dir 가 필요합니다. 속도 측정용 이미지 디렉터리를 지정하세요."
[[ -d "$DATA_DIR" ]] || die "데이터 디렉터리 없음: $DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
N_IMAGES="$(find "$DATA_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \
             -o -iname '*.bmp' -o -iname '*.webp' \) | wc -l | tr -d ' ')"
[[ "$N_IMAGES" -gt "$WARMUP" ]] || die "이미지가 ${N_IMAGES}장뿐입니다. 워밍업 ${WARMUP}장을 버리면 표본이 없습니다."

if [[ -n "$DATA_YAML" ]]; then
  [[ -f "$DATA_YAML" ]] || die "데이터셋 yaml 없음: $DATA_YAML"
  DATA_YAML="$(cd "$(dirname "$DATA_YAML")" && pwd)/$(basename "$DATA_YAML")"
fi

WEIGHTS="$(cd "$(dirname "$WEIGHTS")" && pwd)/$(basename "$WEIGHTS")"

# ------------------------------------------------------------------ 환경 준비
PY="$(resolve_python "$PYENV_ENV")"
log "python : $PY"
log "runtime: $RUNTIME  ($WEIGHTS)"
ensure_repo "$CACHE_DIR" "$REPO_URL" "$REPO_REF" "$FRESH"   # -> REPO_DIR, REPO_SHA
log "commit : $REPO_SHA"
# psutil/pynvml: 자원 샘플러용. pynvml은 GPU 없으면 조용히 비활성되므로 CPU 환경에서도 무해.
ensure_deps "$PY" "$REPO_DIR" "$PYENV_ENV" "$SKIP_DEPS" onnx onnxruntime psutil pynvml pycocotools

# ------------------------------------------------------------------ 실행
OUTDIR="${PROJECT}/${NAME}"
mkdir -p "$OUTDIR"
log "출력   : $OUTDIR"
[[ -n "$DATA_YAML" ]] && log "정확도 : $DATA_YAML" || warn "정확도 생략 (--data-yaml 미지정)"

"$PY" "${HERE}/bench_run.py" \
  --runtime "$RUNTIME" \
  --weights "$WEIGHTS" \
  --repo "$REPO_DIR" \
  --python "$PY" \
  --data-dir "$DATA_DIR" \
  ${DATA_YAML:+--data-yaml "$DATA_YAML"} \
  --commit "$REPO_SHA" \
  --imgsz "$IMGSZ" \
  --device "$DEVICE" \
  --conf "$CONF" \
  --iou "$IOU" \
  --warmup "$WARMUP" \
  --target-class "$TARGET_CLASS" \
  --out "$OUTDIR"

log "리포트 : python bench_report.py --result-dir $OUTDIR"

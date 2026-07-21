#!/usr/bin/env bash
#
# A/B 벤치마크 — PyTorch(.pt) vs ONNX Runtime(.onnx)
#
# 두 실험군 모두 레퍼런스 detect.py를 그대로 실행한다. 전처리와 NMS 구현이 완전히
# 동일하므로 두 결과의 차이는 곧 "엔진 교체 효과"다. 추론 코드를 새로 짜면 그 구현이
# 변수로 섞여 무엇 때문에 빨라졌는지 말할 수 없게 된다.
#
# 계측도 detect.py가 이미 출력하는 값을 파싱해 쓴다 (detect.py:316, 320).
#
#   A. torch : python detect.py --weights yolov5s.pt
#   B. onnx  : python detect.py --weights yolov5s.onnx
#
# --data-dir는 필수다. 합성 입력으로는 검출 동등성 대조가 의미를 잃고, 같은 이미지를
# 반복하면 캐시 효과로 실제보다 낙관적인 수치가 나온다.
#
# 사용법:
#   ./benchmark.sh --data-dir /path/to/images
#   ./benchmark.sh --data-dir ./datasets/coco/val2017 --device 0
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
PT_WEIGHTS="${HERE}/yolov5s.pt"
ONNX_WEIGHTS="${HERE}/yolov5s.onnx"
DATA_DIR=""
WARMUP=3
IMGSZ=640
DEVICE="cpu"
CONF=0.25
IOU=0.45
PROJECT="${HERE}/runs/onnx_bench"
NAME="exp"
FRESH=0
SKIP_DEPS=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)       PYENV_ENV="$2"; shift 2 ;;
    --ref)       REPO_REF="$2"; shift 2 ;;
    --pt)        PT_WEIGHTS="$2"; shift 2 ;;
    --onnx)      ONNX_WEIGHTS="$2"; shift 2 ;;
    --data-dir)  DATA_DIR="$2"; shift 2 ;;
    --warmup)    WARMUP="$2"; shift 2 ;;
    --imgsz)     IMGSZ="$2"; shift 2 ;;
    --device)    DEVICE="$2"; shift 2 ;;
    --conf)      CONF="$2"; shift 2 ;;
    --iou)       IOU="$2"; shift 2 ;;
    --project)   PROJECT="$2"; shift 2 ;;
    --name)      NAME="$2"; shift 2 ;;
    --cache-dir) CACHE_DIR="$2"; shift 2 ;;
    --fresh)     FRESH=1; shift ;;
    --skip-deps) SKIP_DEPS=1; shift ;;
    -h|--help)   sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)           die "알 수 없는 인자: $1" ;;
  esac
done

abspath() { printf '%s' "$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"; }
[[ -f "$PT_WEIGHTS"   ]] || die "가중치 없음: $PT_WEIGHTS"
[[ -f "$ONNX_WEIGHTS" ]] || die "ONNX 없음: $ONNX_WEIGHTS  (먼저 ./export_onnx.sh 실행)"
PT_WEIGHTS="$(abspath "$PT_WEIGHTS")"
ONNX_WEIGHTS="$(abspath "$ONNX_WEIGHTS")"

# 데이터셋 필수. 준비되기 전에 돌려서 의미 없는 숫자를 얻는 상황을 막는다.
[[ -n "$DATA_DIR" ]] || die "--data-dir 가 필요합니다. 추론할 이미지 디렉터리를 지정하세요."
[[ -d "$DATA_DIR" ]] || die "데이터 디렉터리 없음: $DATA_DIR"
DATA_DIR="$(cd "$DATA_DIR" && pwd)"
N_IMAGES="$(find "$DATA_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \
             -o -iname '*.bmp' -o -iname '*.webp' \) | wc -l | tr -d ' ')"
[[ "$N_IMAGES" -gt 0 ]] || die "이미지가 없습니다: $DATA_DIR"
[[ "$N_IMAGES" -gt "$WARMUP" ]] || die "이미지가 ${N_IMAGES}장뿐입니다. 워밍업 ${WARMUP}장을 버리면 남는 표본이 없습니다."

# ------------------------------------------------------------------ 환경 준비
PY="$(resolve_python "$PYENV_ENV")"
log "python : $PY"
ensure_repo "$CACHE_DIR" "$REPO_URL" "$REPO_REF" "$FRESH"   # -> REPO_DIR, REPO_SHA
log "repo   : $REPO_DIR"
log "commit : $REPO_SHA"
ensure_deps "$PY" "$REPO_DIR" "$PYENV_ENV" "$SKIP_DEPS" onnx onnxruntime

# ------------------------------------------------------------------ 출력 디렉터리
OUTDIR="${PROJECT}/${NAME}"
i=2; while [[ -d "$OUTDIR" ]]; do OUTDIR="${PROJECT}/${NAME}${i}"; i=$((i + 1)); done
mkdir -p "$OUTDIR"

SOURCE="$DATA_DIR"
log "데이터셋: $SOURCE (${N_IMAGES}장)"

# ------------------------------------------------------------------ 실행
run_arm() {
  local name="$1" weights="$2"
  local logf="${OUTDIR}/${name}.log"
  log "[$name] detect.py --weights $(basename "$weights")"

  local t0 t1
  t0=$(date +%s)
  ( cd "$REPO_DIR" && "$PY" detect.py \
      --weights "$weights" \
      --source "$SOURCE" \
      --imgsz "$IMGSZ" "$IMGSZ" \
      --device "$DEVICE" \
      --conf-thres "$CONF" \
      --iou-thres "$IOU" \
      --project "$OUTDIR" \
      --name "${name}_out" \
      --exist-ok \
      --nosave ) >"$logf" 2>&1 || { warn "[$name] 실패 — $logf 확인"; return 1; }
      # --nosave: 주석 이미지 저장은 계측 대상이 아니고 디스크만 먹는다.
      # 검출 내용은 detect.py가 이미지별 로그에 남기므로 A/B 대조는 로그로 가능하다.
  t1=$(date +%s)

  local size_mb
  size_mb=$("$PY" -c "import os;print(round(os.path.getsize('$weights')/1e6,2))")
  # arms.json: 리포터가 로그와 함께 읽는 실험군 메타데이터
  "$PY" - "$OUTDIR/arms.json" "$name" "$weights" "$size_mb" "$((t1 - t0))" <<'PYEOF'
import json, os, sys
path, name, weights, size_mb, wall = sys.argv[1:6]
d = json.load(open(path)) if os.path.exists(path) else {}
d[name] = {
    "engine": "PyTorch" if weights.endswith(".pt") else "ONNX Runtime",
    "weights": weights,
    "model_size_mb": float(size_mb),
    "wall_time_s": int(wall),
}
json.dump(d, open(path, "w"), indent=2, ensure_ascii=False)
PYEOF
}

rm -f "${OUTDIR}/arms.json"
run_arm "A_torch" "$PT_WEIGHTS"
run_arm "B_onnx"  "$ONNX_WEIGHTS"

# ------------------------------------------------------------------ 리포트
"$PY" "${HERE}/bench_report.py" --log-dir "$OUTDIR" --warmup "$WARMUP"

# 실행 조건을 함께 남긴다. 나중에 숫자만 보고 조건을 되짚을 수 없는 상황을 막는다.
"$PY" - "${OUTDIR}/config.json" <<PYEOF
import json, sys
json.dump({
    "repo": {"url": "${REPO_URL}", "ref": "${REPO_REF}", "commit": "${REPO_SHA}"},
    "python": "${PY}", "pyenv_env": "${PYENV_ENV}",
    "source": "${SOURCE}", "num_images": ${N_IMAGES},
    "imgsz": ${IMGSZ}, "device": "${DEVICE}",
    "conf_thres": ${CONF}, "iou_thres": ${IOU},
    "warmup_dropped": ${WARMUP},
}, open(sys.argv[1], "w"), indent=2)
PYEOF

log "결과: $OUTDIR"

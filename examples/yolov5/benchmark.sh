#!/usr/bin/env bash
#
# 단일 런타임 벤치마크 — 7.17 저널 매트릭(속도·자원·정확도·부가)
#
# 한 번에 하나의 런타임만 측정한다. 결과는 result_<runtime>.json 한 개로 떨어진다.
# 런타임끼리 비교(onnx vs pytorch)는 이 JSON들을 그대로 놓고 보거나 LLM에 넘겨 정리한다
# — 별도 리포트 코드를 두지 않는다. 이 구조라면 "GPU 서버에서 onnx, 노트북에서 pytorch"
# 처럼 따로 돌린 결과도 result JSON만 모으면 된다.
#
# 측정 자체는 레퍼런스가 한다:
#   속도    : detect.py (val2017 이미지) — 이미지별 추론시간
#   정확도  : val.py — YOLO 라벨로 native mAP
#
# 파이프라인:
#   detect.py/val.py → 로그
#     → bench_run.py  : 로그 → <runtime>_latency.csv(원본) + result JSON(통계 제외)
#     → bench_stats.py: CSV → 추론시간 통계 → result JSON의 speed에 병합
# 원본(5000행 CSV)과 통계를 분리해, 워밍업만 바꿔 재집계할 때 재추론이 필요 없다.
# (자원 모니터링은 추후 순차 도입.)
#
# 기준 포맷은 YOLO다. 이미지 + YOLO .txt 라벨이 필수이며, 없으면 실패한다.
# 소형객체 APs(pycocotools)는 COCO json이 필요해 지금은 미구현이다 — 데이터셋을 직접
# 생산·관리하는 시점에 케이스 A(COCO json 경로)로 확장한다. 아래 "추후개발" 주석 참조.
#
# 데이터셋 레이아웃 (yolov5 규약):
#   <dataset-dir>/images/val2017/*.jpg   (또는 <dataset-dir>/val2017/*.jpg)
#   <dataset-dir>/labels/val2017/*.txt   [필수] YOLO 라벨 — native mAP
#   <dataset-dir>/val2017.txt            (없으면 자동 생성)
#
# 사용법:
#   ./benchmark.sh --runtime pytorch --dataset-dir ./datasets/coco --name run1
#   ./benchmark.sh --runtime onnx    --dataset-dir ./datasets/coco --name run1 --device 0
#   ./benchmark.sh ... --no-usage                                                # 자원 로그 끔
#   # 두 result_*.json 을 비교: runs/bench_coco/run1/ 의 JSON을 열어보거나 LLM에 전달
#
# 자원 로그: 각 phase(detect/val)의 python PID를 잡아 pidstat으로 추적 → usage_<runtime>.log
#            (sysstat 필요. 없으면 자동 생략.)
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
DATASET_DIR=""
IMGSZ=640
DEVICE="cpu"
CONF=0.25
IOU=0.45
WARMUP=3
TARGET_CLASS="car"
PROJECT="${HERE}/runs/bench_coco"
NAME="exp"
FRESH=0
SKIP_DEPS=0
USAGE=1         # 자원 로그(pidstat) on. --no-usage로 끔.

while [[ $# -gt 0 ]]; do
  case "$1" in
    --runtime)   RUNTIME="$2"; shift 2 ;;
    --env)       PYENV_ENV="$2"; shift 2 ;;
    --ref)       REPO_REF="$2"; shift 2 ;;
    --pt)        PT_WEIGHTS="$2"; shift 2 ;;
    --onnx)      ONNX_WEIGHTS="$2"; shift 2 ;;
    --dataset-dir|--coco-dir) DATASET_DIR="$2"; shift 2 ;;
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
    --no-usage)  USAGE=0; shift ;;
    -h|--help)   sed -n '2,37p' "${BASH_SOURCE[0]}"; exit 0 ;;
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

# --- 데이터셋 검증 (기준 포맷: YOLO) ---
# 이미지 + YOLO .txt 라벨이 필수. 둘 중 하나라도 없으면 실패한다.
[[ -n "$DATASET_DIR" ]] || die "--dataset-dir 가 필요합니다 (val2017 데이터셋 루트)."
[[ -d "$DATASET_DIR" ]] || die "디렉터리 없음: $DATASET_DIR"
DATASET_DIR="$(cd "$DATASET_DIR" && pwd)"

# 이미지 폴더: yolov5 다운로드는 images/val2017.
IMG_DIR=""
for cand in "${DATASET_DIR}/images/val2017"; do
  [[ -d "$cand" ]] && IMG_DIR="$cand" && break
done
[[ -n "$IMG_DIR" ]] || die "val2017 이미지를 찾지 못했습니다: ${DATASET_DIR}/images/val2017"
N_IMAGES="$(find "$IMG_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | wc -l | tr -d ' ')"
[[ "$N_IMAGES" -gt "$WARMUP" ]] || die "이미지가 ${N_IMAGES}장뿐입니다. 워밍업 ${WARMUP}장을 버리면 표본이 없습니다."

# YOLO 라벨: 정확도(native mAP)의 필수 입력. 없으면 실패한다(케이스 C 차단).
LABEL_DIR="${DATASET_DIR}/labels/val2017"
[[ -d "$LABEL_DIR" ]] && [[ -n "$(find "$LABEL_DIR" -name '*.txt' -print -quit)" ]] \
  || die "YOLO 라벨 없음: ${LABEL_DIR}
  정확도 측정에 YOLO .txt 라벨이 필요합니다. (구조는 --help 참조)"

# ── 추후개발: 케이스 A (COCO json → pycocotools 소형객체 APs) ──────────────
# COCO_JSON="${DATASET_DIR}/annotations/instances_val2017.json" 이 존재하면
# val.py에 --save-json을 붙여 pycocotools APs를 추가로 얻는다. is_coco 정확도를
# 위해 데이터셋 루트명이 'coco'여야 한다(val.py의 80→91 클래스 매핑 조건).
# 지금은 케이스 B(native mAP)만 지원한다.

WEIGHTS="$(cd "$(dirname "$WEIGHTS")" && pwd)/$(basename "$WEIGHTS")"

# ------------------------------------------------------------------ 환경 준비
PY="$(resolve_python "$PYENV_ENV")"
log "python : $PY"
log "runtime: $RUNTIME  ($WEIGHTS)"
ensure_repo "$CACHE_DIR" "$REPO_URL" "$REPO_REF" "$FRESH"   # -> REPO_DIR, REPO_SHA
log "commit : $REPO_SHA"
# onnx/onnxruntime: onnx 런타임 추론용. (native mAP는 pycocotools 불필요 —
# 케이스 A 도입 시 여기에 pycocotools 추가.)
ensure_deps "$PY" "$REPO_DIR" "$PYENV_ENV" "$SKIP_DEPS" onnx onnxruntime

# ------------------------------------------------------------------ 실행
OUTDIR="${PROJECT}/${NAME}"
mkdir -p "$OUTDIR"
log "출력   : $OUTDIR"
log "데이터 : $DATASET_DIR (val2017 ${N_IMAGES}장)"
log "정확도 : YOLO 라벨 native mAP (APs는 추후개발)"

# val.py용 yaml 자동 도출. 레포의 표준 data/coco.yaml에서 path만 이 데이터셋으로 바꿔
# 출력 디렉터리에 생성한다(클래스 이름 80개 하드코딩 대신 레퍼런스 재사용).
#
# 파일명을 coco.yaml로 두지 않는다: val.py는 --data가 'coco.yaml'로 끝나면 --save-json을
# 강제로 켜서 COCO json이 없어도 pycocotools를 시도한다. json 유무를 우리가 제어하려면
# 이 자동 트리거를 피해야 한다.
if [[ -f "${REPO_DIR}/data/coco.yaml" ]]; then
  DATA_YAML="${OUTDIR}/bench_data.yaml"
  "$PY" - "${REPO_DIR}/data/coco.yaml" "$DATASET_DIR" "$DATA_YAML" <<'PYEOF'
import re, sys, pathlib
src, root, dst = sys.argv[1:4]
lines, done = [], False
for ln in pathlib.Path(src).read_text().splitlines():
    if re.match(r"^\s*path\s*:", ln):
        lines.append(f"path: {root}  # benchmark.sh가 --dataset-dir로 덮어씀"); done = True
    else:
        lines.append(ln)
if not done:
    lines.insert(0, f"path: {root}")
pathlib.Path(dst).write_text("\n".join(lines) + "\n")
PYEOF
  log "yaml   : $DATA_YAML (레포 data/coco.yaml에서 생성)"
else
  die "레포에 data/coco.yaml 이 없습니다: ${REPO_DIR}/data/coco.yaml"
fi

# val2017.txt (val 이미지 목록) — val.py의 dataloader가 요구. 없으면 생성한다.
if [[ ! -f "${DATASET_DIR}/val2017.txt" ]]; then
  warn "val2017.txt 없음 — 이미지 목록을 ${OUTDIR}/val2017.txt 로 생성합니다."
  find "$IMG_DIR" -type f \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' \) | sort > "${OUTDIR}/val2017.txt"
  "$PY" - "$DATA_YAML" "${OUTDIR}/val2017.txt" <<'PYEOF'
import re, sys, pathlib
yaml_path, vallist = sys.argv[1:3]
p = pathlib.Path(yaml_path)
lines = [re.sub(r"^(\s*val\s*:).*", rf"\1 {vallist}", ln) for ln in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
PYEOF
fi

# run_phase <phase명> <출력로그> -- <python 인자...>
#
# 레퍼런스 스크립트(detect.py/val.py)를 백그라운드로 띄워 그 PID를 잡고, pidstat으로
# 그 PID만 추적해 자원 로그를 남긴다. 서브셸에서 exec로 python을 실행하므로 $!(서브셸 PID)이
# 곧 python PID가 된다 — 별도 조회 없이 정확한 PID를 얻는 방법이다.
# 자원 로그는 그 메인 프로세스(추론 스레드 포함)만 잡는다. dataloader 워커(별도 PID)는 제외.
run_phase() {
  local phase="$1" logf="$2"; shift 2   # 나머지 = python + 인자
  ( cd "$REPO_DIR" && exec "$@" ) > "$logf" 2>&1 &
  local pid=$! mon=""

  if [[ $USAGE -eq 1 ]] && command -v pidstat >/dev/null 2>&1; then
    { echo "### phase=$phase pid=$pid $(date '+%H:%M:%S')"
      pidstat -u -r -h -p "$pid" 1; } >> "$USAGE_LOG" 2>&1 &
    mon=$!
  fi

  wait "$pid"; local rc=$?
  [[ -n "$mon" ]] && { kill "$mon" 2>/dev/null; wait "$mon" 2>/dev/null; }
  return $rc
}

USAGE_LOG="${OUTDIR}/usage_${RUNTIME}.log"
: > "$USAGE_LOG"   # 실행마다 새로 시작
if [[ $USAGE -eq 1 ]] && ! command -v pidstat >/dev/null 2>&1; then
  warn "pidstat 없음(sysstat 미설치) — 자원 로그를 건너뜁니다. 설치: apt install sysstat"
fi

# --- 속도: detect.py 실행 (+ 자원 추적) ---
DETECT_LOG="${OUTDIR}/${RUNTIME}_detect.log"
log "속도   : detect.py 실행 ($RUNTIME)"
run_phase detect "$DETECT_LOG" "$PY" detect.py \
    --weights "$WEIGHTS" --source "$IMG_DIR" \
    --imgsz "$IMGSZ" "$IMGSZ" --device "$DEVICE" \
    --conf-thres "$CONF" --iou-thres "$IOU" \
    --project "$OUTDIR" --name "${RUNTIME}_detect" --exist-ok --nosave \
  || { tail -20 "$DETECT_LOG"; die "detect.py 실패 — $DETECT_LOG"; }

# --- 정확도: val.py 실행 (+ 자원 추적) ---
# 추후개발(케이스 A): COCO json이 있으면 val.py에 --save-json을 추가해 pycocotools APs를 얻는다.
VAL_LOG="${OUTDIR}/${RUNTIME}_val.log"
log "정확도 : val.py 실행 ($RUNTIME)"
run_phase val "$VAL_LOG" "$PY" val.py \
    --weights "$WEIGHTS" --data "$DATA_YAML" \
    --imgsz "$IMGSZ" --device "$DEVICE" \
    --project "$OUTDIR" --name "${RUNTIME}_val" --exist-ok --verbose \
  || warn "val.py 실패 — $VAL_LOG (정확도 없이 진행)"

[[ $USAGE -eq 1 ]] && command -v pidstat >/dev/null 2>&1 && log "자원   : $USAGE_LOG"

# --- 로그 파싱 → 원본 CSV + result JSON (통계 제외) ---
"$PY" "${HERE}/bench_run.py" \
  --runtime "$RUNTIME" \
  --weights "$WEIGHTS" \
  --detect-log "$DETECT_LOG" \
  --val-log "$VAL_LOG" \
  --commit "$REPO_SHA" \
  --imgsz "$IMGSZ" \
  --device "$DEVICE" \
  --conf "$CONF" \
  --iou "$IOU" \
  --target-class "$TARGET_CLASS" \
  --out "$OUTDIR"

# --- 원본 CSV → 추론시간 통계 → result JSON에 병합 ---
"$PY" "${HERE}/bench_stats.py" \
  --csv "${OUTDIR}/${RUNTIME}_latency.csv" \
  --result "${OUTDIR}/result_${RUNTIME}.json" \
  --warmup "$WARMUP"

log "완료   : ${OUTDIR}/result_${RUNTIME}.json  (원본: ${RUNTIME}_latency.csv)"
log "비교   : 같은 폴더의 result_*.json 을 열어보거나 LLM에 넘겨 정리"
log "재집계 : python bench_stats.py --csv ${OUTDIR}/${RUNTIME}_latency.csv --result ... --warmup N"

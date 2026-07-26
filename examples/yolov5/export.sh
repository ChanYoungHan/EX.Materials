#!/usr/bin/env bash
#
# YOLOv5 export 파이프라인 — ONNX / TensorRT engine (레퍼런스 export.py 그대로 사용)
#
#   1) yolov5 레포를 임시 디렉터리에 클론 (재실행 시 캐시 재사용)
#   2) pyenv 가상환경(--env, 기본 yolov5)의 python으로 실행
#   3) python export.py --include <format>
#   4) 산출물 회수 후 infer.py로 추론 검증
#
# 형식:
#   --format onnx     (기본)  → .onnx
#   --format engine           → .engine (+ 부산물 .onnx). GPU 필수.
#   --format both             → .onnx + .engine
#
# ⚠ TensorRT engine 주의:
#   .engine은 빌드한 그 기기·그 TensorRT 버전에서만 동작한다. Jetson에서 쓸 엔진은
#   반드시 Jetson에서 이 스크립트로 빌드해야 한다(x86에서 만든 엔진은 Jetson에서 안 됨).
#   Jetson은 tensorrt가 JetPack 시스템 패키지이므로 pyenv 환경에서 import되려면
#   가상환경 생성 시 --system-site-packages 가 필요할 수 있다.
#
# 사용법:
#   ./export.sh                                  # onnx (cpu)
#   ./export.sh --format engine --device 0       # TensorRT (GPU/Jetson)
#   ./export.sh --format engine --device 0 --half  # FP16 엔진 (Jetson 권장)
#   ./export.sh --format both --device 0
#   ./export.sh --no-infer                       # export까지만
#
set -euo pipefail

# ------------------------------------------------------------------ 기본값
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYENV_ENV="yolov5"
REPO_URL="https://github.com/ultralytics/yolov5.git"
REPO_REF="master"
CACHE_DIR="${TMPDIR:-/tmp}/yolov5-export"
WEIGHTS="${HERE}/yolov5s.pt"
FORMAT="onnx"
IMGSZ=640
BATCH=1
DEVICE="cpu"
OPSET=18          # 최신 torch exporter가 18로 캡쳐 → 처음부터 18 요청(왕복 회피)
WORKSPACE=4       # TensorRT 빌드 workspace(GB)
EXTRA_EXPORT_ARGS=()
FRESH=0
SKIP_DEPS=0
RUN_INFER=1

LOG_TAG="export"
# shellcheck source=_common.sh
source "${HERE}/_common.sh"

# ------------------------------------------------------------------ 인자 파싱
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)        PYENV_ENV="$2"; shift 2 ;;
    --ref)        REPO_REF="$2"; shift 2 ;;
    --weights)    WEIGHTS="$2"; shift 2 ;;
    --format)     FORMAT="$2"; shift 2 ;;
    --imgsz)      IMGSZ="$2"; shift 2 ;;
    --opset)      OPSET="$2"; shift 2 ;;
    --batch)      BATCH="$2"; shift 2 ;;
    --device)     DEVICE="$2"; shift 2 ;;
    --workspace)  WORKSPACE="$2"; shift 2 ;;
    --cache-dir)  CACHE_DIR="$2"; shift 2 ;;
    --fresh)      FRESH=1; shift ;;
    --skip-deps)  SKIP_DEPS=1; shift ;;
    --no-infer)   RUN_INFER=0; shift ;;
    --dynamic|--simplify|--half)
                  EXTRA_EXPORT_ARGS+=("$1"); shift ;;
    -h|--help)    sed -n '2,33p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)            die "알 수 없는 인자: $1" ;;
  esac
done

# --format → export.py --include 목록
case "$FORMAT" in
  onnx)    INCLUDE=(onnx) ;;
  engine)  INCLUDE=(engine) ;;      # engine은 내부에서 onnx를 먼저 만든다(부산물로 남음)
  both)    INCLUDE=(onnx engine) ;;
  *)       die "알 수 없는 --format: $FORMAT (onnx|engine|both)" ;;
esac
NEED_GPU=0
[[ "$FORMAT" == "engine" || "$FORMAT" == "both" ]] && NEED_GPU=1

# ------------------------------------------------------------------ 사전 검증
# TensorRT는 GPU 빌드. cpu로 요청하면 클론·설치 뒤에 실패하므로 먼저 막는다.
if [[ $NEED_GPU -eq 1 && "$DEVICE" == "cpu" ]]; then
  die "TensorRT(engine)는 GPU 빌드입니다. --device 0 을 지정하세요. (Jetson에서 실행)"
fi
# --half는 GPU 전용, --dynamic과 배타 (export.py의 assert와 동일 조건).
if [[ " ${EXTRA_EXPORT_ARGS[*]-} " == *" --half "* ]]; then
  [[ "$DEVICE" == "cpu" ]] && die "--half는 GPU 전용입니다. --device 0 을 지정하세요."
  [[ " ${EXTRA_EXPORT_ARGS[*]} " == *" --dynamic "* ]] && die "--half와 --dynamic은 함께 쓸 수 없습니다."
fi

# ------------------------------------------------------------------ 1~3. 환경 준비
[[ -f "$WEIGHTS" ]] || die "가중치 파일 없음: $WEIGHTS"
PY="$(resolve_python "$PYENV_ENV")"
log "python : $PY"
log "version: $("$PY" --version 2>&1)"
log "format : $FORMAT  (include: ${INCLUDE[*]})"

ensure_repo "$CACHE_DIR" "$REPO_URL" "$REPO_REF" "$FRESH"   # -> REPO_DIR, REPO_SHA
log "commit : $REPO_SHA"

# onnx 계열 의존성. engine의 tensorrt는 Jetson 시스템 패키지라 여기서 pip 설치하지 않는다
# (export.py의 check_requirements가 없으면 알려준다).
ensure_deps "$PY" "$REPO_DIR" "$PYENV_ENV" "$SKIP_DEPS" onnx onnxslim onnxruntime

# ------------------------------------------------------------------ 4. export 실행
WEIGHTS_ABS="$(cd "$(dirname "$WEIGHTS")" && pwd)/$(basename "$WEIGHTS")"
STEM="${WEIGHTS_ABS%.*}"
ONNX_OUT="${STEM}.onnx"
ENGINE_OUT="${STEM}.engine"

log "export 실행 (workspace ${WORKSPACE}GB)"
START_TS=$(date +%s)
( cd "$REPO_DIR" && "$PY" export.py \
    --weights "$WEIGHTS_ABS" \
    --imgsz "$IMGSZ" \
    --batch-size "$BATCH" \
    --device "$DEVICE" \
    --opset "$OPSET" \
    --workspace "$WORKSPACE" \
    --include "${INCLUDE[@]}" \
    ${EXTRA_EXPORT_ARGS[@]+"${EXTRA_EXPORT_ARGS[@]}"} )
ELAPSED=$(( $(date +%s) - START_TS ))

# ------------------------------------------------------------------ 5. 산출물 확인
PRIMARY=""   # infer.py로 검증할 대표 산출물
if [[ "$FORMAT" == "onnx" || "$FORMAT" == "both" ]]; then
  [[ -f "$ONNX_OUT" ]] || die "onnx 산출물 없음: $ONNX_OUT"
  log "산출물: $ONNX_OUT ($(du -h "$ONNX_OUT" | cut -f1))"
  PRIMARY="$ONNX_OUT"
fi
if [[ "$FORMAT" == "engine" || "$FORMAT" == "both" ]]; then
  [[ -f "$ENGINE_OUT" ]] || die "engine 산출물 없음: $ENGINE_OUT (TensorRT 빌드 실패 로그 확인)"
  log "산출물: $ENGINE_OUT ($(du -h "$ENGINE_OUT" | cut -f1))"
  PRIMARY="$ENGINE_OUT"   # engine이 있으면 그걸 대표로 검증
fi

# ------------------------------------------------------------------ 6. manifest (onnx가 있을 때만)
# opset·self-contained 검증은 onnx 전용. engine 전용이면 이 블록은 건너뛴다.
if [[ -f "$ONNX_OUT" ]]; then
  MANIFEST="${ONNX_OUT}.manifest.json"
  VERDICT="$("$PY" - "$MANIFEST" <<PYEOF
import json, sys, platform, subprocess
def ver(pkg):
    try:
        import importlib.metadata as md
        return md.version(pkg)
    except Exception:
        return None
requested_opset = ${OPSET}
actual_opset, checker_ok, checker_error = None, None, None
n_external, self_contained = None, None
try:
    import onnx
    m = onnx.load("${ONNX_OUT}", load_external_data=False)
    for imp in m.opset_import:
        if imp.domain in ("", "ai.onnx"):
            actual_opset = imp.version; break
    n_external = sum(1 for t in m.graph.initializer if t.data_location == onnx.TensorProto.EXTERNAL)
    self_contained = n_external == 0
    try:
        onnx.checker.check_model("${ONNX_OUT}"); checker_ok = True
    except Exception as e:
        checker_ok, checker_error = False, str(e)[:300]
except Exception as e:
    checker_error = ("onnx 로드 실패: %s" % e)[:300]
json.dump({
    "created_at": subprocess.check_output(["date","-u","+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
    "repo": {"url": "${REPO_URL}", "ref": "${REPO_REF}", "commit": "${REPO_SHA}"},
    "python": {"executable": sys.executable, "version": platform.python_version(), "pyenv_env": "${PYENV_ENV}"},
    "packages": {p: ver(p) for p in ("torch","onnx","onnxruntime","onnxslim","tensorrt","pycuda")},
    "export": {"weights": "${WEIGHTS_ABS}", "format": "${FORMAT}", "imgsz": ${IMGSZ}, "batch": ${BATCH},
               "device": "${DEVICE}", "opset_requested": requested_opset, "opset_actual": actual_opset,
               "extra_args": "${EXTRA_EXPORT_ARGS[*]-}".split(), "elapsed_s": ${ELAPSED}},
    "validation": {"onnx_checker_passed": checker_ok, "external_data_refs": n_external,
                   "self_contained": self_contained, "error": checker_error},
    "outputs": {"onnx": "${ONNX_OUT}", "engine": ("${ENGINE_OUT}" if __import__("os").path.exists("${ENGINE_OUT}") else None)},
}, open(sys.argv[1], "w"), indent=2)
print("opset=%s (요청 %s) checker=%s self_contained=%s" % (actual_opset, requested_opset, checker_ok, self_contained))
if actual_opset is not None and actual_opset != requested_opset: print("MISMATCH")
if self_contained: print("SELF_CONTAINED")
PYEOF
)" || VERDICT=""
  log "manifest: $MANIFEST"
  [[ -n "$VERDICT" ]] && log "검증: $(printf '%s' "$VERDICT" | sed -n 1p)" || warn "manifest 생성 실패 — 산출물은 유효"
  grep -q MISMATCH <<<"$VERDICT" && warn "요청 opset과 실제가 다릅니다."

  # 고아 외부 가중치 정리 (self-contained일 때만)
  EXT_DATA="${ONNX_OUT}.data"
  if [[ -f "$EXT_DATA" ]] && grep -q SELF_CONTAINED <<<"$VERDICT"; then
    log "고아 외부 가중치 제거: $(basename "$EXT_DATA")"
    rm -f "$EXT_DATA"
  fi
fi

# ------------------------------------------------------------------ 7. 추론 검증
if [[ $RUN_INFER -eq 1 && -n "$PRIMARY" ]]; then
  INFER_DEV="cpu"; [[ "$DEVICE" != "cpu" ]] && INFER_DEV="0"
  log "추론 검증: infer.py ($(basename "$PRIMARY"), device=$INFER_DEV)"
  "$PY" "${HERE}/infer.py" --weights "$PRIMARY" --imgsz "$IMGSZ" --device "$INFER_DEV"
fi

log "완료 (export ${ELAPSED}s)"

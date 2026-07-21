#!/usr/bin/env bash
#
# YOLOv5 ONNX export 파이프라인 (레퍼런스 export.py 그대로 사용)
#
#   1) yolov5 레포를 임시 디렉터리에 클론 (재실행 시 캐시 재사용)
#   2) pyenv 가상환경(--env, 기본 yolov5)의 python으로 실행
#   3) python export.py --include onnx
#   4) 산출물 .onnx 회수 후 onnx_infer.py로 추론 검증
#
# 사용법:
#   ./export_onnx.sh
#   ./export_onnx.sh --weights yolov5s.pt --imgsz 640
#   ./export_onnx.sh --opset 17                # 구버전 런타임 호환이 필요할 때
#   ./export_onnx.sh --ref v7.0 --fresh        # 특정 태그로 고정 + 클론 재생성
#   ./export_onnx.sh --no-infer                # export까지만
#
set -euo pipefail

# ------------------------------------------------------------------ 기본값
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYENV_ENV="yolov5"
REPO_URL="https://github.com/ultralytics/yolov5.git"
REPO_REF="master"                 # 재현성이 필요하면 --ref v7.0 처럼 고정할 것
CACHE_DIR="${TMPDIR:-/tmp}/yolov5-export"
WEIGHTS="${HERE}/yolov5s.pt"
IMGSZ=640
BATCH=1
DEVICE="cpu"
# export.py의 CLI 기본값은 17이지만, 최신 torch의 ONNX exporter는 18로 캡쳐한 뒤
# 17로 되돌리기를 시도하다 Resize 연산에서 실패한다(변환 어댑터 부재).
# 그 실패는 내부에서 삼켜져 export는 "성공"하지만 실제 산출물은 opset 18이 된다.
# 처음부터 18을 요청해 그 왕복을 없앤다. 구버전 런타임 호환이 필요하면 --opset으로 낮출 것.
OPSET=18
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
    --imgsz)      IMGSZ="$2"; shift 2 ;;
    --opset)      OPSET="$2"; shift 2 ;;
    --batch)      BATCH="$2"; shift 2 ;;
    --device)     DEVICE="$2"; shift 2 ;;
    --cache-dir)  CACHE_DIR="$2"; shift 2 ;;
    --fresh)      FRESH=1; shift ;;
    --skip-deps)  SKIP_DEPS=1; shift ;;
    --no-infer)   RUN_INFER=0; shift ;;
    --dynamic|--simplify|--half)
                  EXTRA_EXPORT_ARGS+=("$1"); shift ;;
    -h|--help)    sed -n '2,20p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *)            die "알 수 없는 인자: $1" ;;
  esac
done

# --half는 GPU 전용, --dynamic과 배타 (export.py run() 1380~1381행의 assert와 동일 조건).
# 스크립트 단계에서 미리 막아 5분짜리 클론·설치 뒤에 실패하는 상황을 방지한다.
if [[ " ${EXTRA_EXPORT_ARGS[*]-} " == *" --half "* ]]; then
  [[ "$DEVICE" == "cpu" ]] && die "--half는 GPU 전용입니다. --device 0 을 지정하세요."
  [[ " ${EXTRA_EXPORT_ARGS[*]} " == *" --dynamic "* ]] && die "--half와 --dynamic은 함께 쓸 수 없습니다."
fi

# ------------------------------------------------------------------ 1~3. 환경 준비
[[ -f "$WEIGHTS" ]] || die "가중치 파일 없음: $WEIGHTS"

PY="$(resolve_python "$PYENV_ENV")"
log "python : $PY"
log "version: $("$PY" --version 2>&1)"

REPO_DIR="$(ensure_repo "$CACHE_DIR" "$REPO_URL" "$REPO_REF" "$FRESH")"
log "repo   : $REPO_DIR"
log "commit : $REPO_SHA"   # 재현성 근거. 결과가 달라지면 가장 먼저 볼 값.

ensure_deps "$PY" "$REPO_DIR" "$PYENV_ENV" "$SKIP_DEPS" onnx onnxslim onnxruntime

# ------------------------------------------------------------------ 4. export 실행
# export.py는 .onnx를 --weights와 같은 디렉터리에 만든다. 레포를 더럽히지 않도록
# 가중치를 작업 디렉터리에 두고 그 경로를 그대로 넘긴다.
WEIGHTS_ABS="$(cd "$(dirname "$WEIGHTS")" && pwd)/$(basename "$WEIGHTS")"
ONNX_OUT="${WEIGHTS_ABS%.*}.onnx"

log "export 실행"
START_TS=$(date +%s)
( cd "$REPO_DIR" && "$PY" export.py \
    --weights "$WEIGHTS_ABS" \
    --imgsz "$IMGSZ" \
    --batch-size "$BATCH" \
    --device "$DEVICE" \
    --opset "$OPSET" \
    --include onnx \
    ${EXTRA_EXPORT_ARGS[@]+"${EXTRA_EXPORT_ARGS[@]}"} )
ELAPSED=$(( $(date +%s) - START_TS ))

[[ -f "$ONNX_OUT" ]] || die "export는 끝났으나 산출물이 없습니다: $ONNX_OUT"
log "산출물: $ONNX_OUT ($(du -h "$ONNX_OUT" | cut -f1))"

# ------------------------------------------------------------------ 5. 검증 + manifest
# 무엇으로 만든 .onnx인지 추적 가능하게 남긴다. 나중에 "이 파일 어떻게 만들었더라"를 없앤다.
#
# 특히 opset은 "요청값"이 아니라 "산출물에서 읽은 실제값"을 기록한다.
# torch exporter는 요청 opset을 만족 못하면 조용히 다른 버전으로 내보내고 export는 성공한다.
# 그 불일치를 여기서 잡지 못하면 다른 런타임으로 옮길 때가 되어서야 발견된다.
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
    # load_external_data=False: 가중치를 메모리에 올리지 않고 참조 형태만 본다.
    m = onnx.load("${ONNX_OUT}", load_external_data=False)
    # 표준 도메인("" 또는 ai.onnx)의 opset이 우리가 말하는 그 opset이다.
    for imp in m.opset_import:
        if imp.domain in ("", "ai.onnx"):
            actual_opset = imp.version
            break
    n_external = sum(1 for t in m.graph.initializer
                     if t.data_location == onnx.TensorProto.EXTERNAL)
    self_contained = n_external == 0
    try:
        onnx.checker.check_model("${ONNX_OUT}")  # 경로로 넘겨야 외부 데이터도 함께 검증된다
        checker_ok = True
    except Exception as e:
        checker_ok, checker_error = False, str(e)[:300]
except Exception as e:
    checker_error = f"onnx 로드 실패: {e}"[:300]

json.dump({
    "created_at": subprocess.check_output(["date", "-u", "+%Y-%m-%dT%H:%M:%SZ"]).decode().strip(),
    "repo": {"url": "${REPO_URL}", "ref": "${REPO_REF}", "commit": "${REPO_SHA}"},
    "python": {"executable": sys.executable, "version": platform.python_version(), "pyenv_env": "${PYENV_ENV}"},
    "packages": {p: ver(p) for p in ("torch", "onnx", "onnxruntime", "onnxslim")},
    "export": {
        "weights": "${WEIGHTS_ABS}",
        "imgsz": ${IMGSZ},
        "batch": ${BATCH},
        "device": "${DEVICE}",
        "opset_requested": requested_opset,
        "opset_actual": actual_opset,
        "extra_args": "${EXTRA_EXPORT_ARGS[*]-}".split(),
        "elapsed_s": ${ELAPSED},
    },
    "validation": {
        "onnx_checker_passed": checker_ok,
        "external_data_refs": n_external,
        "self_contained": self_contained,
        "error": checker_error,
    },
    "output": "${ONNX_OUT}",
}, open(sys.argv[1], "w"), indent=2)

print(f"opset={actual_opset} (요청 {requested_opset})  checker={checker_ok}  self_contained={self_contained}")
if actual_opset is not None and actual_opset != requested_opset:
    print("MISMATCH")
if checker_ok is False:
    print("CHECKFAIL")
if self_contained:
    print("SELF_CONTAINED")
PYEOF
)"

log "manifest: $MANIFEST"
log "검증: $(printf '%s' "$VERDICT" | sed -n 1p)"
if grep -q MISMATCH <<<"$VERDICT"; then
  warn "요청 opset과 실제 산출물 opset이 다릅니다. 다른 런타임(TensorRT 등)으로 옮길 때 문제가 될 수 있습니다."
fi
if grep -q CHECKFAIL <<<"$VERDICT"; then
  warn "onnx.checker 검증 실패. manifest의 validation.error를 확인하세요."
fi

# torch exporter는 가중치를 <name>.onnx.data로 따로 빼서 내보낸다. 이후 export.py가
# 메타데이터를 붙여 재저장하면서 가중치를 본체에 다시 흡수시키는데, 그 .data 파일은
# 지워지지 않고 남는다. 그래프가 외부 참조를 하나도 갖지 않을 때만(= 안전할 때만) 정리한다.
EXT_DATA="${ONNX_OUT}.data"
if [[ -f "$EXT_DATA" ]]; then
  if grep -q SELF_CONTAINED <<<"$VERDICT"; then
    log "고아 외부 가중치 제거: $(basename "$EXT_DATA") ($(du -h "$EXT_DATA" | cut -f1))"
    rm -f "$EXT_DATA"
  else
    warn "$(basename "$EXT_DATA") 는 그래프가 참조 중입니다. .onnx와 반드시 함께 배포하세요."
  fi
fi

# ------------------------------------------------------------------ 6. 추론 검증
if [[ $RUN_INFER -eq 1 ]]; then
  log "ONNX Runtime 추론 검증"
  "$PY" "${HERE}/onnx_infer.py" --onnx "$ONNX_OUT" --imgsz "$IMGSZ"
fi

log "완료 (export ${ELAPSED}s)"

#!/usr/bin/env bash
#
# export_onnx.sh / benchmark.sh 공통 유틸.
# 단독 실행하지 않고 source로 읽어들인다.
#
# pyenv 해석과 레포 클론 로직을 한 곳에 둔다. 두 스크립트가 같은 python·같은 커밋을
# 쓴다는 것이 비교의 전제이므로, 복사해두고 따로 손대는 상황을 구조적으로 막는다.

log()  { printf '\033[1;34m[%s]\033[0m %s\n' "${LOG_TAG:-run}" "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

# resolve_python <pyenv환경명>
#
# pyenv 환경을 셸 활성화(pyenv activate) 대신 인터프리터 절대경로로 직접 지정한다.
# 비대화형 셸에서 pyenv init이 안 걸려 엉뚱한 python이 잡히는 사고를 원천 차단.
resolve_python() {
  local env_name="$1" py root
  command -v pyenv >/dev/null || die "pyenv가 없습니다."
  root="${PYENV_ROOT:-$(pyenv root)}"
  py="${root}/versions/${env_name}/bin/python"
  if [[ ! -x "$py" ]]; then
    warn "경로에서 못 찾음: $py — pyenv 조회로 재시도"
    eval "$(pyenv init -)" 2>/dev/null || true
    py="$(PYENV_VERSION="$env_name" pyenv which python 2>/dev/null || true)"
    [[ -x "${py:-}" ]] || die "pyenv 환경 '${env_name}'을 찾을 수 없습니다. (pyenv versions 로 확인)"
  fi
  printf '%s' "$py"
}

# ensure_repo <캐시디렉터리> <url> <ref> <fresh 0|1>
# 성공 시 레포 경로를 stdout으로, 커밋 SHA를 전역 REPO_SHA로 반환한다.
ensure_repo() {
  local cache="$1" url="$2" ref="$3" fresh="$4"
  local dir="${cache}/yolov5"
  command -v git >/dev/null || die "git이 없습니다."

  if [[ "$fresh" -eq 1 ]]; then
    warn "기존 클론 삭제: $dir"
    rm -rf "$dir"
  fi

  if [[ -d "${dir}/.git" ]]; then
    git -C "$dir" fetch --quiet --depth 1 origin "$ref"
    git -C "$dir" checkout --quiet FETCH_HEAD
  else
    mkdir -p "$cache"
    git clone --quiet --depth 1 --branch "$ref" "$url" "$dir" 2>/dev/null \
      || git clone --quiet --depth 1 "$url" "$dir"
  fi

  REPO_SHA="$(git -C "$dir" rev-parse HEAD)"
  printf '%s' "$dir"
}

# ensure_deps <python> <레포디렉터리> <환경명> <skip 0|1> [추가패키지...]
#
# 레포별·환경별 마커 파일로 최초 1회만 설치한다. yolov5 requirements.txt는 무겁고,
# 벤치마크를 반복 실행할 때마다 pip을 도는 것은 시간 낭비이자 버전이 바뀔 위험이다.
ensure_deps() {
  local py="$1" dir="$2" env_name="$3" skip="$4"; shift 4
  local marker="${dir}/.deps-installed-${env_name}"
  if [[ "$skip" -eq 1 || -f "$marker" ]]; then
    log "의존성 설치 생략"
    return
  fi
  log "의존성 설치 (최초 1회, 수 분 소요)"
  "$py" -m pip install --quiet --upgrade pip
  "$py" -m pip install --quiet -r "${dir}/requirements.txt"
  # export.py / detect.py의 ONNX 경로가 요구하는 패키지. 두 스크립트 내부의
  # check_requirements가 런타임 자동 설치를 시도하지만, 운영에서는 예측 가능하도록
  # 미리 명시 설치한다.
  [[ $# -gt 0 ]] && "$py" -m pip install --quiet "$@"
  touch "$marker"
}

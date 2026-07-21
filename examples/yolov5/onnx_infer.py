"""ONNX Runtime 단독 추론 — yolov5 코드 의존 없음.

basic_example.py와 같은 이미지를 입력으로, export.py가 만든 .onnx를 ONNX Runtime으로
실행한다. 이 파일이 import하는 것은 onnxruntime / numpy / opencv뿐이며 ultralytics
패키지는 쓰지 않는다. 즉 .onnx만 있으면 yolov5 레포 없이 배포·운영이 가능하다.

ONNX 그래프에는 전처리(letterbox)도 후처리(NMS)도 들어있지 않으므로 여기서 직접 구현한다.
클래스 이름은 export.py가 .onnx의 metadata_props에 심어둔 값을 읽어 쓴다.

결과는 yolov5 관례를 따라 runs/onnx_detect/exp, exp2, ... 로 회차마다 분리 저장한다.
(주석 이미지 + result.json + 입력 이미지 사본)

Usage:
    python onnx_infer.py --onnx yolov5s.onnx
    python onnx_infer.py --onnx yolov5s.onnx --source bus.jpg --provider cpu
    python onnx_infer.py --onnx yolov5s.onnx --name run-a --exist-ok
"""

import argparse
import ast
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort

HERE = Path(__file__).resolve().parent

# basic_example.py가 쓰던 것과 동일한 이미지
DEFAULT_URL = "https://ultralytics.com/images/bus.jpg"
# 다운로드한 입력 이미지를 두는 곳. 작업 디렉터리를 더럽히지 않도록 분리한다.
CACHE_DIR = HERE / "runs" / ".cache"


def increment_path(base: Path, name: str, exist_ok: bool = False) -> Path:
    """runs/onnx_detect/exp -> exp2 -> exp3 ... (yolov5 관례와 동일)

    회차마다 디렉터리를 분리해 이전 결과를 덮어쓰지 않는다. 실행 이력이 곧 비교 근거가
    되므로 운영에서는 덮어쓰기보다 누적이 안전하다. --exist-ok로 덮어쓰기 가능.
    """
    p = base / name
    if not p.exists() or exist_ok:
        p.mkdir(parents=True, exist_ok=True)
        return p
    for i in range(2, 10000):
        q = base / f"{name}{i}"
        if not q.exists():
            q.mkdir(parents=True)
            return q
    raise RuntimeError(f"경로를 만들 수 없습니다: {base}/{name}*")


# ------------------------------------------------------------------ 메타데이터
def load_class_names(sess: "ort.InferenceSession") -> dict:
    """세션 메타데이터에서 클래스 이름을 읽는다.

    export.py 357~361행이 {"stride", "names"}를 .onnx의 metadata_props에 심는다.
    그래프 자체에는 클래스 이름이 없으므로(이름은 연산이 아니다) 이 주머니가 유일한 출처다.

    ORT 세션의 get_modelmeta()로 꺼내면 onnx 패키지 없이 읽을 수 있다. 배포 환경에
    onnxruntime만 있으면 되도록 하는 것이 목적이며, ultralytics의 DetectMultiBackend도
    같은 방식을 쓴다 (models/common.py, ONNX Runtime 분기).
    """
    try:
        meta = sess.get_modelmeta().custom_metadata_map
        return {int(k): v for k, v in ast.literal_eval(meta["names"]).items()}
    except Exception as e:
        print(f"[warn] 클래스 이름 로드 실패 ({e}) — 인덱스로 표시합니다")
        return {}


# -------------------------------------------------------------------- 전처리
def letterbox(im: np.ndarray, new_shape: int = 640, color=(114, 114, 114)):
    """종횡비를 유지한 채 리사이즈하고 남는 영역을 회색으로 채운다.

    단순 resize를 쓰면 이미지가 찌그러져 정확도가 떨어진다. yolov5 학습 시 전처리와
    동일해야 하므로 여기서도 letterbox를 쓴다.
    되돌리기용으로 배율 r과 패딩 (dw, dh)를 함께 반환한다.
    """
    h, w = im.shape[:2]
    r = min(new_shape / h, new_shape / w)
    new_w, new_h = round(w * r), round(h * r)
    dw, dh = (new_shape - new_w) / 2, (new_shape - new_h) / 2

    if (w, h) != (new_w, new_h):
        im = cv2.resize(im, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    im = cv2.copyMakeBorder(im, top, bottom, left, right, cv2.BORDER_CONSTANT, value=color)
    return im, r, (dw, dh)


def preprocess(im: np.ndarray, imgsz: int):
    """BGR HWC uint8 -> RGB BCHW float32 [0,1]"""
    padded, r, pad = letterbox(im, imgsz)
    x = padded[:, :, ::-1].transpose(2, 0, 1)          # BGR->RGB, HWC->CHW
    x = np.ascontiguousarray(x, dtype=np.float32) / 255.0
    return x[None], r, pad                              # (1,3,H,W)


# -------------------------------------------------------------------- 후처리
def nms(boxes: np.ndarray, scores: np.ndarray, iou_thres: float) -> list:
    """Non-Maximum Suppression (numpy 구현).

    점수가 높은 박스부터 채택하고, 그와 IoU가 임계값을 넘는 박스는 같은 객체를 가리키는
    중복으로 보고 버린다. boxes는 xyxy.
    """
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]

    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        # 교집합 영역
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thres]
    return keep


def postprocess(pred: np.ndarray, r: float, pad, orig_shape, conf_thres=0.25, iou_thres=0.45):
    """(1, 25200, 85) -> 검출 리스트.

    85 = cx, cy, w, h, objectness, cls0..cls79  (좌표는 입력 640 픽셀 기준)
    """
    p = pred[0]

    # 1단계: objectness로 거른다. 25200개 중 대부분이 여기서 탈락해 이후 연산이 가벼워진다.
    p = p[p[:, 4] > conf_thres]
    if not len(p):
        return []

    # 2단계: 최종 점수 = objectness x 클래스 확률
    scores_all = p[:, 5:] * p[:, 4:5]
    cls_ids = scores_all.argmax(1)
    scores = scores_all[np.arange(len(p)), cls_ids]
    m = scores > conf_thres
    p, cls_ids, scores = p[m], cls_ids[m], scores[m]
    if not len(p):
        return []

    # 3단계: 중심좌표 xywh -> 모서리 xyxy
    cx, cy, w, h = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)

    # 4단계: 클래스별로 NMS를 분리한다. 클래스마다 큰 오프셋을 더해 좌표 공간을 갈라놓으면
    # 서로 다른 클래스의 박스는 절대 겹치지 않아 한 번의 NMS로 클래스별 처리가 된다.
    keep = nms(boxes + (cls_ids[:, None] * 7680), scores, iou_thres)

    # 5단계: letterbox 되돌리기 — 패딩을 빼고 배율로 나눈다
    dw, dh = pad
    oh, ow = orig_shape[:2]
    out = []
    for i in keep:
        x1, y1, x2, y2 = boxes[i]
        x1, x2 = (x1 - dw) / r, (x2 - dw) / r
        y1, y2 = (y1 - dh) / r, (y2 - dh) / r
        out.append({
            "cls": int(cls_ids[i]),
            "conf": float(scores[i]),
            "xyxy": [
                float(np.clip(x1, 0, ow)), float(np.clip(y1, 0, oh)),
                float(np.clip(x2, 0, ow)), float(np.clip(y2, 0, oh)),
            ],
        })
    return out


# ---------------------------------------------------------------------- 입출력
def load_image(source: str) -> tuple:
    """이미지를 읽어 (배열, 실제 파일 경로)를 반환. URL이면 캐시에 받아둔다."""
    if source.startswith(("http://", "https://")):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / source.split("/")[-1]
        if not cache.exists():
            print(f"[info] 다운로드: {source} -> {cache}")
            urllib.request.urlretrieve(source, cache)
        source = str(cache)
    im = cv2.imread(source)
    if im is None:
        raise FileNotFoundError(f"이미지를 읽을 수 없습니다: {source}")
    return im, Path(source)


def draw(im: np.ndarray, dets: list, names: dict) -> np.ndarray:
    out = im.copy()
    for d in dets:
        x1, y1, x2, y2 = map(int, d["xyxy"])
        label = f"{names.get(d['cls'], d['cls'])} {d['conf']:.2f}"
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 2, y1), (0, 200, 0), -1)
        cv2.putText(out, label, (x1 + 1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return out


def main(a):
    providers = {
        "cpu": ["CPUExecutionProvider"],
        "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    }[a.provider]
    providers = [p for p in providers if p in ort.get_available_providers()] or ["CPUExecutionProvider"]

    t0 = time.perf_counter()
    sess = ort.InferenceSession(a.onnx, providers=providers)
    load_s = time.perf_counter() - t0

    iname = sess.get_inputs()[0].name
    onames = [o.name for o in sess.get_outputs()]
    names = load_class_names(sess)

    im, src_path = load_image(a.source)
    x, r, pad = preprocess(im, a.imgsz)

    for _ in range(a.warmup):
        sess.run(onames, {iname: x})

    t = time.perf_counter()
    pred = sess.run(onames, {iname: x})[0]
    infer_ms = (time.perf_counter() - t) * 1000

    dets = postprocess(pred, r, pad, im.shape, a.conf, a.iou)

    outdir = increment_path(Path(a.project), a.name, a.exist_ok)
    out_img = outdir / f"{src_path.stem}.jpg"
    cv2.imwrite(str(out_img), draw(im, dets, names))

    summary = {
        "onnx": str(Path(a.onnx).resolve()),
        "providers": sess.get_providers(),
        "source": a.source,
        "imgsz": a.imgsz,
        "conf_thres": a.conf,
        "iou_thres": a.iou,
        "input_shape": list(x.shape),
        "output_shape": list(np.shape(pred)),
        "load_time_s": round(load_s, 3),
        "inference_ms": round(infer_ms, 2),
        "num_detections": len(dets),
        "detections": [
            {"class": names.get(d["cls"], d["cls"]), "conf": round(d["conf"], 3),
             "xyxy": [round(v, 1) for v in d["xyxy"]]}
            for d in dets
        ],
        "outdir": str(outdir),
        "saved": str(out_img),
    }
    (outdir / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n[info] 결과 저장: {outdir}")


def parse_args():
    p = argparse.ArgumentParser(description="ONNX Runtime inference (no yolov5 dependency)")
    p.add_argument("--onnx", default="yolov5s.onnx")
    p.add_argument("--source", default=DEFAULT_URL, help="이미지 경로 또는 URL")
    p.add_argument("--imgsz", type=int, default=640, help="export 시 지정한 값과 같아야 함")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--provider", choices=["cpu", "cuda"], default="cpu")
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--project", default=str(HERE / "runs" / "onnx_detect"), help="결과 상위 디렉터리")
    p.add_argument("--name", default="exp", help="결과 디렉터리 이름 (중복 시 exp2, exp3...)")
    p.add_argument("--exist-ok", action="store_true", help="기존 디렉터리에 덮어쓰기")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

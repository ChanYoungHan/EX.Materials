"""단독 추론 검증 — PyTorch / ONNX Runtime / TensorRT 3-way.

가중치 확장자로 백엔드를 자동 선택한다:
    .pt     → PyTorch      (torch + yolov5 필요)
    .onnx   → ONNX Runtime (onnxruntime 만 필요 — yolov5 의존 없음)
    .engine → TensorRT     (tensorrt + pycuda 필요 — Jetson 등 NVIDIA 기기)

세 백엔드 모두 raw 출력 (1, 25200, 85)를 내고, letterbox 전처리와 NMS 후처리는
공유한다(아래 함수들). 즉 백엔드만 갈아끼우고 전후처리는 동일하게 검증한다.

TensorRT 주의 (Jetson):
  - .engine은 빌드한 그 기기·그 TensorRT 버전에서만 동작한다. 반드시 타깃(Jetson)에서
    export.sh로 빌드하고, 이 스크립트도 같은 기기에서 돌려야 한다.
  - 아래 TRT 코드는 TensorRT 8.x(bindings API, JetPack 4.6 = Nano)를 기준으로 한다.
  - 이 파일은 Python 3.6에서도 동작하도록 3.7+ 전용 문법을 피한다(원본 Nano 대응).

Usage:
    python infer.py --weights yolov5s.onnx
    python infer.py --weights yolov5s.engine --device 0
    python infer.py --weights yolov5s.pt --device 0 --source bus.jpg
"""

import argparse
import ast
import json
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
DEFAULT_URL = "https://ultralytics.com/images/bus.jpg"
CACHE_DIR = HERE / "runs" / ".cache"

# .engine/.pt에 클래스 이름이 없을 때의 폴백 (COCO 80). export한 모델이 COCO 학습 기준.
COCO_NAMES = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 4: "airplane", 5: "bus",
    6: "train", 7: "truck", 8: "boat", 9: "traffic light", 10: "fire hydrant",
    11: "stop sign", 12: "parking meter", 13: "bench", 14: "bird", 15: "cat", 16: "dog",
    17: "horse", 18: "sheep", 19: "cow", 20: "elephant", 21: "bear", 22: "zebra",
    23: "giraffe", 24: "backpack", 25: "umbrella", 26: "handbag", 27: "tie", 28: "suitcase",
    29: "frisbee", 30: "skis", 31: "snowboard", 32: "sports ball", 33: "kite",
    34: "baseball bat", 35: "baseball glove", 36: "skateboard", 37: "surfboard",
    38: "tennis racket", 39: "bottle", 40: "wine glass", 41: "cup", 42: "fork", 43: "knife",
    44: "spoon", 45: "bowl", 46: "banana", 47: "apple", 48: "sandwich", 49: "orange",
    50: "broccoli", 51: "carrot", 52: "hot dog", 53: "pizza", 54: "donut", 55: "cake",
    56: "chair", 57: "couch", 58: "potted plant", 59: "bed", 60: "dining table",
    61: "toilet", 62: "tv", 63: "laptop", 64: "mouse", 65: "remote", 66: "keyboard",
    67: "cell phone", 68: "microwave", 69: "oven", 70: "toaster", 71: "sink",
    72: "refrigerator", 73: "book", 74: "clock", 75: "vase", 76: "scissors",
    77: "teddy bear", 78: "hair drier", 79: "toothbrush",
}


# ================================================================= 백엔드
class OnnxBackend:
    """ONNX Runtime. onnxruntime 외 의존 없음. 클래스명은 .onnx 메타데이터에서."""

    kind = "onnx"

    def __init__(self, weights, device):
        import onnxruntime as ort
        prov = {
            "cpu": ["CPUExecutionProvider"],
            "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
            "trt": ["TensorrtExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"],
        }[device]
        avail = ort.get_available_providers()
        prov = [p for p in prov if p in avail] or ["CPUExecutionProvider"]
        self.sess = ort.InferenceSession(weights, providers=prov)
        self.providers = self.sess.get_providers()
        self.iname = self.sess.get_inputs()[0].name
        self.onames = [o.name for o in self.sess.get_outputs()]
        self.names = self._load_names()

    def _load_names(self):
        # export.py가 .onnx metadata_props에 심어둔 names (그래프엔 없음).
        try:
            meta = self.sess.get_modelmeta().custom_metadata_map
            return {int(k): v for k, v in ast.literal_eval(meta["names"]).items()}
        except Exception:
            return dict(COCO_NAMES)

    def infer(self, x):
        return np.asarray(self.sess.run(self.onames, {self.iname: x})[0], dtype=np.float32)

    def desc(self):
        return "ONNX Runtime (%s)" % ",".join(self.providers)


class TorchBackend:
    """PyTorch. torch + yolov5(model 정의) 필요 — .pt는 코드가 있어야 로드된다."""

    kind = "pytorch"

    def __init__(self, weights, device):
        import torch
        self.torch = torch
        self.device = torch.device("cuda:0" if device in ("cuda", "trt", "0") else "cpu")
        m = torch.hub.load("ultralytics/yolov5", "custom", path=weights, verbose=False)
        core = getattr(m, "model", m).to(self.device).float().eval()
        for p in core.parameters():
            p.requires_grad = False
        self.model = core
        nm = getattr(core, "names", None)
        self.names = (dict(enumerate(nm)) if isinstance(nm, (list, tuple))
                      else dict(nm) if isinstance(nm, dict) else dict(COCO_NAMES))

    def infer(self, x):
        with self.torch.inference_mode():
            t = self.torch.from_numpy(x).to(self.device)
            y = self.model(t)
            y = y[0] if isinstance(y, (list, tuple)) else y
            return y.float().cpu().numpy()

    def desc(self):
        return "PyTorch (%s)" % self.device


class TrtBackend:
    """TensorRT 8.x (bindings API). tensorrt + pycuda 필요. Jetson에서만 검증할 것.

    엔진은 빌드한 기기·TRT 버전에 종속된다. 다른 곳에서 만든 .engine을 넣으면
    deserialize 단계에서 실패한다 — 그때는 그 기기에서 export.sh로 다시 빌드해야 한다.
    (클래스명은 엔진에 없으므로 COCO 폴백. --names로 덮어쓸 수 있음.)
    """

    kind = "trt"

    def __init__(self, weights, device, names=None):
        import tensorrt as trt
        import pycuda.driver as cuda
        import pycuda.autoinit  # noqa: F401  (CUDA 컨텍스트 초기화)
        self.trt, self.cuda = trt, cuda

        logger = trt.Logger(trt.Logger.WARNING)
        with open(weights, "rb") as f, trt.Runtime(logger) as rt:
            self.engine = rt.deserialize_cuda_engine(f.read())
        if self.engine is None:
            raise RuntimeError(
                "TensorRT 엔진 deserialize 실패. 이 엔진은 다른 기기/TRT 버전에서 만든 것일 수 있습니다. "
                "이 기기에서 export.sh --format engine 으로 다시 빌드하세요."
            )
        self.ctx = self.engine.create_execution_context()
        self.stream = cuda.Stream()

        self.inputs, self.outputs, self.bindings = [], [], []
        for i in range(self.engine.num_bindings):
            shape = tuple(self.engine.get_binding_shape(i))
            dtype = trt.nptype(self.engine.get_binding_dtype(i))
            host = cuda.pagelocked_empty(int(np.prod(shape)), dtype)
            dev = cuda.mem_alloc(host.nbytes)
            self.bindings.append(int(dev))
            slot = {"host": host, "dev": dev, "shape": shape, "dtype": dtype}
            (self.inputs if self.engine.binding_is_input(i) else self.outputs).append(slot)
        self.names = names or dict(COCO_NAMES)

    def infer(self, x):
        inp = self.inputs[0]
        np.copyto(inp["host"], x.astype(inp["dtype"], copy=False).ravel())
        self.cuda.memcpy_htod_async(inp["dev"], inp["host"], self.stream)
        self.ctx.execute_async_v2(bindings=self.bindings, stream_handle=self.stream.handle)
        out = self.outputs[0]
        self.cuda.memcpy_dtoh_async(out["host"], out["dev"], self.stream)
        self.stream.synchronize()
        return out["host"].reshape(out["shape"]).astype(np.float32)

    def desc(self):
        return "TensorRT %s" % self.trt.__version__


def make_backend(weights, device, names=None):
    ext = Path(weights).suffix.lower()
    if ext == ".pt":
        return TorchBackend(weights, device)
    if ext == ".onnx":
        return OnnxBackend(weights, device)
    if ext == ".engine":
        return TrtBackend(weights, device, names)
    raise ValueError("지원하지 않는 확장자: %s (.pt/.onnx/.engine)" % ext)


# ================================================================= 공유 전후처리
def letterbox(im, new_shape=640, color=(114, 114, 114)):
    """종횡비 유지 리사이즈 + 회색 패딩. 배율 r, 패딩 (dw,dh) 반환."""
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


def preprocess(im, imgsz):
    """BGR HWC uint8 -> RGB BCHW float32 [0,1]"""
    padded, r, pad = letterbox(im, imgsz)
    x = padded[:, :, ::-1].transpose(2, 0, 1)
    x = np.ascontiguousarray(x, dtype=np.float32) / 255.0
    return x[None], r, pad


def nms(boxes, scores, iou_thres):
    """Non-Maximum Suppression (numpy). boxes는 xyxy."""
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
        xx1 = np.maximum(x1[i], x1[rest]); yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest]); yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thres]
    return keep


def postprocess(pred, r, pad, orig_shape, conf_thres=0.25, iou_thres=0.45):
    """(1, 25200, 85) -> 검출 리스트. 85 = cx,cy,w,h,obj,cls0..cls79 (640px 기준)."""
    p = pred[0]
    p = p[p[:, 4] > conf_thres]
    if not len(p):
        return []
    scores_all = p[:, 5:] * p[:, 4:5]
    cls_ids = scores_all.argmax(1)
    scores = scores_all[np.arange(len(p)), cls_ids]
    m = scores > conf_thres
    p, cls_ids, scores = p[m], cls_ids[m], scores[m]
    if not len(p):
        return []
    cx, cy, w, h = p[:, 0], p[:, 1], p[:, 2], p[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    keep = nms(boxes + (cls_ids[:, None] * 7680), scores, iou_thres)  # 클래스별 분리 NMS
    dw, dh = pad
    oh, ow = orig_shape[:2]
    out = []
    for i in keep:
        x1, y1, x2, y2 = boxes[i]
        x1, x2 = (x1 - dw) / r, (x2 - dw) / r
        y1, y2 = (y1 - dh) / r, (y2 - dh) / r
        out.append({
            "cls": int(cls_ids[i]), "conf": float(scores[i]),
            "xyxy": [float(np.clip(x1, 0, ow)), float(np.clip(y1, 0, oh)),
                     float(np.clip(x2, 0, ow)), float(np.clip(y2, 0, oh))],
        })
    return out


# ==================================================================== 입출력
def load_image(source):
    if source.startswith(("http://", "https://")):
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache = CACHE_DIR / source.split("/")[-1]
        if not cache.exists():
            print("[info] 다운로드: %s -> %s" % (source, cache))
            urllib.request.urlretrieve(source, str(cache))
        source = str(cache)
    im = cv2.imread(source)
    if im is None:
        raise FileNotFoundError("이미지를 읽을 수 없습니다: %s" % source)
    return im, Path(source)


def draw(im, dets, names):
    out = im.copy()
    for d in dets:
        x1, y1, x2, y2 = map(int, d["xyxy"])
        label = "%s %.2f" % (names.get(d["cls"], d["cls"]), d["conf"])
        cv2.rectangle(out, (x1, y1), (x2, y2), (0, 200, 0), 2)
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, y1 - th - 6), (x1 + tw + 2, y1), (0, 200, 0), -1)
        cv2.putText(out, label, (x1 + 1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
    return out


def increment_path(base, name, exist_ok=False):
    p = base / name
    if not p.exists() or exist_ok:
        p.mkdir(parents=True, exist_ok=True)
        return p
    for i in range(2, 10000):
        q = base / ("%s%d" % (name, i))
        if not q.exists():
            q.mkdir(parents=True)
            return q
    raise RuntimeError("경로를 만들 수 없습니다: %s/%s*" % (base, name))


def main(a):
    names_override = None
    if a.names:
        import yaml  # 선택: --names coco.yaml
        names_override = {int(k): v for k, v in yaml.safe_load(open(a.names))["names"].items()}

    t0 = time.perf_counter()
    be = make_backend(a.weights, a.device, names_override)
    load_s = time.perf_counter() - t0
    names = names_override or be.names

    im, src_path = load_image(a.source)
    x, r, pad = preprocess(im, a.imgsz)

    for _ in range(a.warmup):
        be.infer(x)
    t = time.perf_counter()
    pred = be.infer(x)
    infer_ms = (time.perf_counter() - t) * 1000

    dets = postprocess(pred, r, pad, im.shape, a.conf, a.iou)

    outdir = increment_path(Path(a.project), a.name, a.exist_ok)
    out_img = outdir / ("%s.jpg" % src_path.stem)
    cv2.imwrite(str(out_img), draw(im, dets, names))

    summary = {
        "backend": be.kind,
        "backend_desc": be.desc(),
        "weights": str(Path(a.weights).resolve()),
        "source": a.source,
        "imgsz": a.imgsz,
        "conf_thres": a.conf, "iou_thres": a.iou,
        "input_shape": list(x.shape),
        "output_shape": list(np.shape(pred)),
        "load_time_s": round(load_s, 3),
        "inference_ms": round(infer_ms, 2),
        "num_detections": len(dets),
        "detections": [
            {"class": names.get(d["cls"], d["cls"]), "conf": round(d["conf"], 3),
             "xyxy": [round(v, 1) for v in d["xyxy"]]} for d in dets
        ],
        "saved": str(out_img),
    }
    (outdir / "result.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\n[info] 결과 저장: %s" % outdir)


def parse_args():
    p = argparse.ArgumentParser(description="단독 추론 검증 (pytorch/onnx/tensorrt)")
    p.add_argument("--weights", default="yolov5s.onnx", help=".pt / .onnx / .engine (확장자로 백엔드 자동 선택)")
    p.add_argument("--source", default=DEFAULT_URL, help="이미지 경로 또는 URL")
    p.add_argument("--imgsz", type=int, default=640, help="export 시 값과 같아야 함")
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--iou", type=float, default=0.45)
    p.add_argument("--device", choices=["cpu", "cuda", "trt", "0"], default="cpu",
                   help="onnx: provider / pytorch: 디바이스 / tensorrt: 항상 GPU")
    p.add_argument("--names", default=None, help="클래스명 yaml (선택, 주로 .engine용)")
    p.add_argument("--warmup", type=int, default=2)
    p.add_argument("--project", default=str(HERE / "runs" / "infer"), help="결과 상위 디렉터리")
    p.add_argument("--name", default="exp", help="결과 디렉터리 이름")
    p.add_argument("--exist-ok", action="store_true", help="기존 디렉터리 덮어쓰기")
    return p.parse_args()


if __name__ == "__main__":
    main(parse_args())

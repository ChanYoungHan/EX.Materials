"""박스 중심점 오차 기반 모델 벤치마크.

논의된 기준:
  - 1차 지표: GT 중심 vs 예측 중심의 유클리드 거리 (px, 그리고 sqrt(GT면적) 정규화)
  - 통계: mean / median / std / p95  (편향·분산 상세 분석은 별도 섹션 — 여기선 bias 벡터만 출력)
  - 참고 지표: 매칭 쌍의 IoU, 검출률(matched/GT), FP 수
  - 3x3 영역별 분해 (호모그래피 증폭 불균일 대비)

호환 모델:
  - ultralytics: YOLO11, YOLO26, RT-DETR      -> --adapter ultralytics --model yolo11n.pt
  - HuggingFace: D-FINE, RF-DETR(HF 포팅판 등) -> --adapter hf --model ustc-community/dfine-medium-coco
  - CenterNet 등 커스텀: CustomAdapter 상속 후 predict()만 구현

사용법:
    pip install ultralytics scipy pillow            # +transformers torch (HF 어댑터 시)
    python benchmark.py --ann ./data/filtered_val2017.json --img-dir ./data/val2017 \
        --adapter ultralytics --model yolo11n.pt --conf 0.25
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

TARGET_CLASSES = {"car", "boat", "skateboard", "remote"}


# ---------------------------------------------------------------- adapters
class BaseAdapter:
    """predict()는 [{'name', 'conf', 'x1','y1','x2','y2'}, ...] 를 반환해야 한다."""

    def predict(self, image_path: str) -> list[dict]:
        raise NotImplementedError


class UltralyticsAdapter(BaseAdapter):
    """YOLO11 / YOLO26 / RT-DETR (ultralytics 패키지)."""

    def __init__(self, model: str, conf: float):
        from ultralytics import YOLO
        self.m = YOLO(model)
        self.conf = conf

    def predict(self, image_path):
        r = self.m.predict(image_path, conf=self.conf, verbose=False)[0]
        names = r.names
        out = []
        for b in r.boxes:
            x1, y1, x2, y2 = b.xyxy[0].tolist()
            out.append(dict(name=names[int(b.cls)], conf=float(b.conf),
                            x1=x1, y1=y1, x2=x2, y2=y2))
        return out


class HFAdapter(BaseAdapter):
    """HuggingFace transformers 객체검출 모델 (D-FINE 등, COCO 사전학습)."""

    def __init__(self, model: str, conf: float):
        import torch
        from transformers import AutoImageProcessor, AutoModelForObjectDetection
        self.torch = torch
        self.proc = AutoImageProcessor.from_pretrained(model)
        self.model = AutoModelForObjectDetection.from_pretrained(model).eval()
        self.conf = conf

    def predict(self, image_path):
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        inputs = self.proc(images=img, return_tensors="pt")
        with self.torch.no_grad():
            outputs = self.model(**inputs)
        res = self.proc.post_process_object_detection(
            outputs, threshold=self.conf,
            target_sizes=[(img.height, img.width)])[0]
        id2label = self.model.config.id2label
        out = []
        for score, label, box in zip(res["scores"], res["labels"], res["boxes"]):
            x1, y1, x2, y2 = box.tolist()
            out.append(dict(name=id2label[int(label)], conf=float(score),
                            x1=x1, y1=y1, x2=x2, y2=y2))
        return out


class CustomAdapter(BaseAdapter):
    """CenterNet 등 자체 모델용 템플릿. predict()만 구현하면 된다.

    예: mmdetection CenterNet
        from mmdet.apis import init_detector, inference_detector
        구현 후 --adapter custom 으로 실행.
    """

    def __init__(self, model: str, conf: float):
        raise NotImplementedError("CustomAdapter.predict()를 구현하세요")


ADAPTERS = {"ultralytics": UltralyticsAdapter, "hf": HFAdapter, "custom": CustomAdapter}


# ---------------------------------------------------------------- metrics
def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def match_by_center(gts, preds):
    """클래스별 헝가리안 매칭. 게이트: 예측 중심이 GT 최장변 이내."""
    if not gts or not preds:
        return []
    gc = np.array([[(g[0] + g[2]) / 2, (g[1] + g[3]) / 2] for g in gts])
    pc = np.array([[(p[0] + p[2]) / 2, (p[1] + p[3]) / 2] for p in preds])
    dist = np.linalg.norm(gc[:, None, :] - pc[None, :, :], axis=2)
    gate = np.array([max(g[2] - g[0], g[3] - g[1]) for g in gts])
    cost = np.where(dist <= gate[:, None], dist, 1e6)
    ri, ci = linear_sum_assignment(cost)
    return [(int(r), int(c), dist[r, c]) for r, c in zip(ri, ci) if cost[r, c] < 1e6]


def region_of(cx, cy, w, h):
    return f"r{min(2, int(3 * cy / h))}{min(2, int(3 * cx / w))}"  # r00(좌상)~r22(우하)


def summarize(errs):
    e = np.array(errs)
    return dict(n=len(e), mean=float(e.mean()), median=float(np.median(e)),
                std=float(e.std()), p95=float(np.percentile(e, 95)))


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ann", default="./data/filtered_val2017.json")
    ap.add_argument("--img-dir", default="./data/val2017")
    ap.add_argument("--adapter", choices=ADAPTERS, default="ultralytics")
    ap.add_argument("--model", required=True)
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--out", default=None, help="결과 JSON 경로")
    args = ap.parse_args()

    coco = json.loads(Path(args.ann).read_text())
    cat_name = {c["id"]: c["name"] for c in coco["categories"]}
    gts_by_img = defaultdict(list)
    for a in coco["annotations"]:
        x, y, w, h = a["bbox"]
        gts_by_img[a["image_id"]].append((cat_name[a["category_id"]], (x, y, x + w, y + h)))

    adapter = ADAPTERS[args.adapter](args.model, args.conf)

    per_class = defaultdict(lambda: dict(err_px=[], err_norm=[], iou=[],
                                         dx=[], dy=[], n_gt=0, n_fp=0))
    per_region = defaultdict(list)

    images = [im for im in coco["images"] if im["id"] in gts_by_img]
    for i, im in enumerate(images, 1):
        path = Path(args.img_dir) / im["file_name"]
        if not path.exists():
            continue
        preds = [p for p in adapter.predict(str(path)) if p["name"] in TARGET_CLASSES]

        for cls in TARGET_CLASSES:
            g = [b for n, b in gts_by_img[im["id"]] if n == cls]
            p = [(q["x1"], q["y1"], q["x2"], q["y2"]) for q in preds if q["name"] == cls]
            s = per_class[cls]
            s["n_gt"] += len(g)
            matches = match_by_center(g, p)
            s["n_fp"] += len(p) - len(matches)
            for gi, pi, d in matches:
                gb, pb = g[gi], p[pi]
                gcx, gcy = (gb[0] + gb[2]) / 2, (gb[1] + gb[3]) / 2
                pcx, pcy = (pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2
                side = np.sqrt((gb[2] - gb[0]) * (gb[3] - gb[1]))
                s["err_px"].append(d)
                s["err_norm"].append(d / side)
                s["iou"].append(iou(gb, pb))
                s["dx"].append(pcx - gcx)
                s["dy"].append(pcy - gcy)
                per_region[region_of(gcx, gcy, im["width"], im["height"])].append(d)
        print(f"\r[{i}/{len(images)}] {im['file_name']}", end="")
    print()

    # ---- report
    report = dict(model=args.model, adapter=args.adapter, conf=args.conf,
                  classes={}, regions={}, overall={})
    all_px, all_norm = [], []
    print(f"\n=== 중심점 오차 벤치마크: {args.model} ===")
    hdr = f"{'class':12s} {'nGT':>5s} {'det%':>6s} {'FP':>5s} | {'mean':>6s} {'med':>6s} {'std':>6s} {'p95':>6s} px | {'norm':>6s} {'mIoU':>5s} | bias(dx,dy)"
    print(hdr)
    for cls, s in sorted(per_class.items()):
        if not s["err_px"]:
            print(f"{cls:12s} {s['n_gt']:5d}  매칭 없음")
            continue
        st = summarize(s["err_px"])
        det = 100 * st["n"] / max(s["n_gt"], 1)
        norm_mean = float(np.mean(s["err_norm"]))
        bias = (float(np.mean(s["dx"])), float(np.mean(s["dy"])))
        print(f"{cls:12s} {s['n_gt']:5d} {det:5.1f}% {s['n_fp']:5d} | "
              f"{st['mean']:6.2f} {st['median']:6.2f} {st['std']:6.2f} {st['p95']:6.2f} px | "
              f"{norm_mean:6.3f} {np.mean(s['iou']):5.3f} | ({bias[0]:+.2f},{bias[1]:+.2f})")
        report["classes"][cls] = dict(**st, det_rate=det / 100, n_fp=s["n_fp"],
                                      err_norm_mean=norm_mean,
                                      miou_matched=float(np.mean(s["iou"])), bias=bias)
        all_px += s["err_px"]
        all_norm += s["err_norm"]

    if all_px:
        report["overall"] = dict(**summarize(all_px),
                                 err_norm_mean=float(np.mean(all_norm)))
        o = report["overall"]
        print(f"\n{'OVERALL':12s} n={o['n']}  mean={o['mean']:.2f}px  "
              f"median={o['median']:.2f}px  p95={o['p95']:.2f}px  norm={o['err_norm_mean']:.3f}")

    print("\n영역별(3x3) 평균 중심 오차 px  [r00=좌상 ... r22=우하]")
    for rk in sorted(per_region):
        report["regions"][rk] = float(np.mean(per_region[rk]))
        print(f"  {rk}: {report['regions'][rk]:6.2f}  (n={len(per_region[rk])})")

    out = Path(args.out) if args.out else Path(f"result_{Path(args.model).stem}.json")
    out.write_text(json.dumps(report, indent=2))
    print(f"\n[saved] {out}")


if __name__ == "__main__":
    main()

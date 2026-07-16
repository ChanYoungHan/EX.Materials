"""COCO val2017에서 검증용 4개 클래스(car, boat, skateboard, remote)를
픽셀 면적 기준으로 필터해 새 COCO 포맷 JSON을 만든다.

선정 논리 (1/35 탱크 프라모델 대응):
  - car, boat        : 실루엣 유사 (낮고 길쭉한 차체/선체+상부구조)
  - remote, skateboard: 실물 크기·종횡비(~3:1) 및 탑뷰 촬영 조건 유사
  - 면적 필터        : 아레나 카메라에서 탱크가 차지할 예상 픽셀 크기와 정렬

사용법:
    python filter_coco.py --root ./data
    python filter_coco.py --root ./data --min-side 32 --max-side 96
    python filter_coco.py --root ./data --download-images   # 필터된 이미지만 다운로드
"""
import argparse
import json
import urllib.request
from collections import Counter
from pathlib import Path

# 클래스별 면적 범위 override (None이면 전역 --min-side/--max-side 사용)
# car는 대형 인스턴스가 많아 소형만 사용한다는 논의를 반영해 전역 범위 그대로 사용.
TARGET_CLASSES = {"car": None, "boat": None, "skateboard": None, "remote": None}

IMG_URL_FMT = "http://images.cocodataset.org/val2017/{file_name}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="./data")
    ap.add_argument("--min-side", type=float, default=32, help="sqrt(bbox 면적) 하한 (px)")
    ap.add_argument("--max-side", type=float, default=96, help="sqrt(bbox 면적) 상한 (px)")
    ap.add_argument("--out", default=None, help="출력 JSON 경로 (기본: root/filtered_val2017.json)")
    ap.add_argument("--download-images", action="store_true",
                    help="필터에 걸린 이미지만 root/val2017/ 에 개별 다운로드")
    args = ap.parse_args()

    root = Path(args.root)
    src = root / "annotations" / "instances_val2017.json"
    out = Path(args.out) if args.out else root / "filtered_val2017.json"

    coco = json.loads(src.read_text())
    name_by_catid = {c["id"]: c["name"] for c in coco["categories"]}
    target_catids = {c["id"] for c in coco["categories"] if c["name"] in TARGET_CLASSES}

    lo, hi = args.min_side**2, args.max_side**2
    kept_anns = []
    for a in coco["annotations"]:
        if a["category_id"] not in target_catids or a.get("iscrowd", 0):
            continue
        w, h = a["bbox"][2], a["bbox"][3]
        area = w * h  # segmentation area가 아닌 bbox 면적 기준 (검출 벤치마크 목적)
        rng = TARGET_CLASSES[name_by_catid[a["category_id"]]]
        _lo, _hi = (rng[0]**2, rng[1]**2) if rng else (lo, hi)
        if _lo <= area <= _hi:
            kept_anns.append(a)

    kept_img_ids = {a["image_id"] for a in kept_anns}
    kept_imgs = [im for im in coco["images"] if im["id"] in kept_img_ids]
    kept_cats = [c for c in coco["categories"] if c["id"] in target_catids]

    filtered = {
        "info": {"description": f"COCO val2017 filtered: {sorted(TARGET_CLASSES)}, "
                                f"side {args.min_side}-{args.max_side}px"},
        "images": kept_imgs,
        "annotations": kept_anns,
        "categories": kept_cats,
    }
    out.write_text(json.dumps(filtered))

    stats = Counter(name_by_catid[a["category_id"]] for a in kept_anns)
    print(f"[done] {out}")
    print(f"  이미지 {len(kept_imgs)}장, 인스턴스 {len(kept_anns)}개")
    for k, v in sorted(stats.items()):
        print(f"    {k:12s}: {v}")

    if args.download_images:
        img_dir = root / "val2017"
        img_dir.mkdir(parents=True, exist_ok=True)
        for i, im in enumerate(kept_imgs, 1):
            dst = img_dir / im["file_name"]
            if dst.exists():
                continue
            urllib.request.urlretrieve(IMG_URL_FMT.format(file_name=im["file_name"]), dst)
            print(f"\r  이미지 다운로드 {i}/{len(kept_imgs)}", end="")
        print(f"\n[done] images -> {img_dir}")


if __name__ == "__main__":
    main()

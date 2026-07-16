# COCO 중심점 오차 벤치마크

1/35 탱크 프라모델 대응 검증 셋(car, boat, skateboard, remote + 픽셀 면적 필터)으로
검출 모델의 **박스 중심점 오차**를 비교한다. mIoU는 참고 지표로만 병기.

## 빠른 시작

```bash
pip install ultralytics scipy numpy pillow
# D-FINE 등 HF 모델 쓸 경우: pip install transformers torch

# 1. annotations 다운로드 (241MB)
python download_coco.py --root ./data

# 2. 필터 (기본: sqrt(bbox면적) 32~96px) + 해당 이미지만 다운로드
python filter_coco.py --root ./data --download-images

# 3. 벤치마크
python benchmark.py --model yolo11n.pt                                    # YOLO11
python benchmark.py --model yolo26n.pt                                    # YOLO26
python benchmark.py --model rtdetr-l.pt                                   # RT-DETR
python benchmark.py --adapter hf --model ustc-community/dfine-medium-coco # D-FINE
```

CenterNet 등 자체 모델은 `benchmark.py`의 `CustomAdapter.predict()`만 구현하면 된다.

## 출력 지표

- 클래스별/전체: 중심 오차 mean · median · std · p95 (px), sqrt(GT면적) 정규화 오차
- bias 벡터 (dx, dy) — 편향·분산 상세 분석은 별도 섹션에서 수행
- 참고: 매칭 쌍 mIoU, 검출률, FP 수
- 3×3 영역별 평균 오차 (호모그래피 증폭 불균일 대비)
- 결과는 `result_<model>.json`으로 저장 → 모델 간 비교에 사용

## 매칭 규칙

클래스별 헝가리안 매칭, 비용 = 중심 거리, 게이트 = GT 박스 최장변 이내.
필터·비교 조건(면적 범위, conf 임계값)은 모든 모델에 동일하게 적용할 것.

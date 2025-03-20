#!/bin/bash

# 테스트 설정
ENDPOINT="http://localhost:8000/test/async-wait"  # async-wait 또는 sync-wait로 변경
REQUESTS=100  # 동시 요청 수

# 시간 측정 시작
start_time=$(date +%s)

# 동시 요청 발송
for ((i=1; i<=$REQUESTS; i++))
do
  curl -X 'GET' \
    "$ENDPOINT" \
    -H 'accept: application/json' \
    -s -o /dev/null \
    -w "Request $i: HTTP %{http_code} %{time_total}s\\n" &
done

# 모든 요청 완료 대기
wait

# 총 소요 시간 계산
end_time=$(date +%s)
total_time=$((end_time - start_time))

echo "===================================="
echo "총 처리 시간: ${total_time}초"
echo "동시 요청 수: ${REQUESTS}"
echo "테스트 엔드포인트: ${ENDPOINT}"

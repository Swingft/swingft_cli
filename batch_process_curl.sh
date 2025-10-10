#!/bin/bash
"""
JSON 파일들을 curl로 하나씩 순차적으로 처리하는 스크립트
"""

# 설정
SERVER_URL="http://localhost:8000"
INPUT_DIR="$1"
OUTPUT_DIR="batch_results"
CLEANUP_URL="${SERVER_URL}/cleanup"

# 입력 디렉토리 확인
if [ -z "$INPUT_DIR" ]; then
    echo "사용법: ./batch_process_curl.sh <JSON_파일_디렉토리>"
    echo "예시: ./batch_process_curl.sh exclude_inputs"
    exit 1
fi

if [ ! -d "$INPUT_DIR" ]; then
    echo "❌ 디렉토리를 찾을 수 없습니다: $INPUT_DIR"
    exit 1
fi

# 출력 디렉토리 생성
mkdir -p "$OUTPUT_DIR"

echo "JSON 파일 검색 중: $INPUT_DIR"

# JSON 파일들 찾기
json_files=($(find "$INPUT_DIR" -name "*.input.json" -type f))

if [ ${#json_files[@]} -eq 0 ]; then
    echo "❌ JSON 파일을 찾을 수 없습니다."
    exit 1
fi

echo "발견된 JSON 파일: ${#json_files[@]}개"

# 서버 연결 확인
echo "서버 연결 확인 중..."
if ! curl -s "$SERVER_URL/" > /dev/null; then
    echo "❌ 서버 연결 실패: $SERVER_URL"
    echo "서버가 실행 중인지 확인하세요: python3 model_test.py"
    exit 1
fi
echo "✅ 서버 연결 확인: $SERVER_URL"

# 파일들 순차 처리
processed=0
succeeded=0
failed=0

for i in "${!json_files[@]}"; do
    json_file="${json_files[$i]}"
    file_num=$((i + 1))
    total_files=${#json_files[@]}
    
    echo ""
    echo "[$file_num/$total_files] 처리 중: $json_file"
    
    # 결과 파일명 생성
    filename=$(basename "$json_file" .input.json)
    result_file="$OUTPUT_DIR/${filename}.result.json"
    
    # curl로 요청 전송
    if curl -X POST "$SERVER_URL/analyze_swift" \
            -H "Content-Type: application/json" \
            -H "Connection: close" \
            -d @"$json_file" \
            -o "$result_file" \
            --progress-bar \
            --max-time 300 \
            --connect-timeout 30 \
            --retry 2 \
            --retry-delay 5 \
            --silent --show-error; then
        
        # 응답 파일 확인
        if [ -s "$result_file" ] && grep -q "raw_output" "$result_file"; then
            echo "  ✅ 성공: $(wc -c < "$result_file")바 응답"
            succeeded=$((succeeded + 1))
        else
            echo "  ❌ 실패: 빈 응답 또는 잘못된 형식"
            failed=$((failed + 1))
        fi
    else
        echo "  ❌ 실패: curl 요청 오류"
        failed=$((failed + 1))
    fi
    
    processed=$((processed + 1))
    
    # 다음 요청 전 대기 (메모리 정리)
    if [ $file_num -lt $total_files ]; then
        echo "  ⏳ 10초 대기 중... (메모리 정리)"
        sleep 10
        
        # 서버 메모리 정리 요청 (cleanup 엔드포인트가 없으므로 제거)
        echo "  ⏳ 메모리 정리 대기 중..."
    fi
done

# 최종 결과
echo ""
echo "=== 처리 완료 ==="
echo "총 처리: $processed개"
echo "성공: $succeeded개"
echo "실패: $failed개"
echo "결과 저장 위치: $OUTPUT_DIR/"

# 실패한 파일이 있으면 목록 출력
if [ $failed -gt 0 ]; then
    echo ""
    echo "실패한 파일들:"
    for json_file in "${json_files[@]}"; do
        filename=$(basename "$json_file" .input.json)
        result_file="$OUTPUT_DIR/${filename}.result.json"
        if [ ! -s "$result_file" ] || ! grep -q "raw_output" "$result_file"; then
            echo "  - $json_file"
        fi
    done
fi

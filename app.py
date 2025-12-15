# [핵심] 키워드 최적화 분석 함수 (표준화 적용)
def analyze_text(text):
    try:
        model_name = get_available_model()
        if not model_name: return ["AI연동실패"], "기타"
        
        model = genai.GenerativeModel(model_name)
        
        # [수정] 표준 키워드 리스트를 프롬프트에 포함
        prompt = f"""
        너는 팀의 레슨런(Lesson Learned)을 분류하는 데이터 관리자야.
        입력된 텍스트를 분석해서 다음 규칙에 맞춰 JSON으로 응답해.

        [분류 기준표 (Standard Keywords)]
        아래 카테고리별 표준 키워드를 참고해서 가장 적절한 것을 선택해.
        - 기획: 기획의도, 정책수립, 일정관리, 데이터분석, 인사이트
        - 개발: 트러블슈팅, 리팩토링, 신기술도입, 코드리뷰, 성능개선, 유지보수
        - 디자인: UI/UX, 디자인시스템, 사용성개선, 디자인가이드
        - 협업: 커뮤니케이션, 문서화, 회의문화, 피드백
        - 프로세스: 업무효율화, 자동화, QA/테스트, 배포관리

        [작성 규칙]
        1. keywords: 총 2~3개의 키워드를 배열로 작성.
           - **첫 번째 키워드**는 반드시 위 [분류 기준표]에 있는 단어 중 하나를 선택해서 넣어. (데이터 그룹핑용)
           - 나머지 키워드는 본문 내용을 구체적으로 설명하는 단어를 자유롭게 넣어.
           - 예시: "디자인 시스템을 만들어서 통일성을 줬다" -> ["디자인시스템", "통일성", "작업효율"]
           - 예시: "API 응답속도가 느려서 캐시를 적용했다" -> ["성능개선", "API", "캐싱"]
        
        2. category: 기획, 개발, 디자인, 협업, 프로세스, 기타 중 택1

        [응답 형식 (JSON)]
        {{
            "keywords": ["표준키워드", "상세키워드1", "상세키워드2"],
            "category": "카테고리"
        }}
        
        텍스트: {text}
        """
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text_resp)
        cat = result.get("category", "기타")
        if cat not in CATEGORY_THEMES: cat = "기타"
        return result.get("keywords", ["분석불가"]), cat
    except Exception as e:
        return ["AI연동실패"], "기타"

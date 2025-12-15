import streamlit as st
import pandas as pd
import json
import datetime
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
import uuid
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# 1. 설정 및 데이터 관리
# -----------------------------------------------------------------------------
# [주의] Streamlit Cloud Secrets에 GOOGLE_API_KEY가 설정되어 있어야 합니다.
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"
CARD_BG_COLOR = "#0E1117"

# [사용자 제공 퍼플 팔레트]
PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83", 950: "#261A4C"
}

# [색상 테마] Gap 200
CATEGORY_THEMES = {
    "기타": (400, 600), "기획": (500, 700), "개발": (600, 800),
    "디자인": (700, 900), "협업": (500, 700), "프로세스": (600, 800)
}

def get_text_color(palette_index):
    return "#FFFFFF"

# 구글 시트 연결
def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

# 데이터 로드
def load_data():
    conn = get_connection()
    try:
        df = conn.read(ttl=0)
        if df.empty or 'id' not in df.columns:
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
        df = df.fillna("")
        return df
    except Exception:
        return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

# 데이터 저장
def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    save_df['date'] = save_df['date'].dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)

def save_entry(writer, text, keywords, category):
    df = load_data()
    new_data = pd.DataFrame({
        "id": [str(uuid.uuid4())],
        "date": [datetime.datetime.now()],
        "writer": [writer],
        "text": [text],
        "keywords": [json.dumps(keywords, ensure_ascii=False)],
        "category": [category]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    save_data_to_sheet(df)

def update_entry(entry_id, writer, text, keywords, category):
    df = load_data()
    idx = df[df['id'] == entry_id].index
    if not idx.empty:
        df.at[idx[0], 'writer'] = writer
        df.at[idx[0], 'text'] = text
        df.at[idx[0], 'keywords'] = json.dumps(keywords, ensure_ascii=False)
        df.at[idx[0], 'category'] = category
        save_data_to_sheet(df)

def delete_entry(entry_id):
    df = load_data()
    df = df[df['id'] != entry_id]
    save_data_to_sheet(df)

def get_available_model():
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                return m.name
        return None
    except:
        return None

# [핵심 변경] 표준 키워드 분류가 적용된 AI 분석 함수
def analyze_text(text):
    try:
        model_name = get_available_model()
        if not model_name: return ["AI연동실패"], "기타"
        
        model = genai.GenerativeModel(model_name)
        
        # [Taxonomy] 표준 키워드 리스트 적용
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

def get_month_week_str(date_obj):
    try:
        week_num = (date_obj.day - 1) // 7 + 1
        return f"{date_obj.strftime('%y')}년 {date_obj.month}월 {week_num}주차"
    except:
        return ""

# -----------------------------------------------------------------------------
# 2. Streamlit UI 디자인
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

if 'edit_mode' not in st.session_state:
    st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state:
    st.session_state['edit_data'] = {}

@st.dialog("⚠️ 삭제 확인")
def confirm_delete_dialog(entry_id):
    st.write("정말 이 기록을 삭제하시겠습니까?")
    st.caption("삭제된 데이터는 복구할 수 없습니다.")
    col_del, col_cancel = st.columns([1, 1])
    with col_del:
        if st.button("삭제", type="primary", use_container_width=True):
            delete_entry(entry_id)
            st.rerun()
    with col_cancel:
        if st.button("취소", use_container_width=True):
            st.rerun()

st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; }}
    .appview-container .main .block-container {{ max-width: 1080px; margin: 0 auto; }}
    
    .ai-status-ok {{ color: {PURPLE_PALETTE[500]}; font-weight: bold; font-size: 0.9rem; border: 1px solid {PURPLE_PALETTE[500]}; padding: 5px 10px; border-radius: 20px; }}
    .ai-status-fail {{ color: #F44336; font-weight: bold; font-size: 0.9rem; border: 1px solid #F44336; padding: 5px 10px; border-radius: 20px; }}

    div[data-testid="stMetric"] {{ background-color: {CARD_BG_COLOR}; border: 1px solid #30333F; padding: 15px; border-radius: 10px; color: white; margin-bottom: 10px; }}
    div[data-testid="stMetricLabel"] {{ color: #9CA3AF !important; }}
    div[data-testid="stMetricValue"] {{ color: white !important; font-weight: 700 !important; }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{ background-color: {CARD_BG_COLOR} !important; border: 1px solid #30333F !important; border-radius: 10px !important; padding: 20px !important; overflow: hidden !important; margin-bottom: 20px !important; }}
    
    button[data-testid="stTab"] {{ font-size: 1.2rem !important; font-weight: 700 !important; }}
    button[kind="secondary"] {{ border: 1px solid #30333F; color: #9CA3AF; padding: 4px 10px; font-size: 0.85rem; line-height: 1.2; margin-top: 0px !important; }}
    button[kind="secondary"]:hover {{ border-color: {PURPLE_PALETTE[500]}; color: {PURPLE_PALETTE[500]}; }}
    </style>
""", unsafe_allow_html=True)

col_head1, col_head2 = st.columns([5, 1])
with col_head1:
    st.title("Team Lesson Learned 🚀")
    st.caption("팀의 배움을 기록하고 공유하는 아카이브")
with col_head2:
    active_model = get_available_model()
    st.write("") 
    st.write("") 
    if active_model:
        st.markdown(f'<div style="text-align: right;"><span class="ai-status-ok">🟢 AI 연동됨</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align: right;"><span class="ai-status-fail">🔴 AI 미연동</span></div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

with tab1:
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        st.info("수정 중인 모드입니다.")
        if st.button("취소하고 새 글 쓰기"):
            st.session_state['edit_mode'] = False
            st.session_state['edit_data'] = {}
            st.rerun()
        form_writer = st.session_state['edit_data'].get('writer', '')
        form_text = st.session_state['edit_data'].get('text', '')
    else:
        st.subheader("이번주의 레슨런을 기록해주세요")
        form_writer = ""
        form_text = ""

    with st.form("record_form", clear_on_submit=True):
        writer = st.text_input("작성자", value=form_writer)
        text = st.text_area("내용 (Markdown 지원)", value=form_text, height=150)
        submitted = st.form_submit_button("수정 완료" if st.session_state['edit_mode'] else "기록 저장하기", use_container_width=True)
        
        if submitted:
            if not writer or not text:
                st.error("내용을 입력해주세요.")
            else:
                with st.spinner("✨ AI 분석 중..."):
                    keywords, category = analyze_text(text)
                    if st.session_state['edit_mode']:
                        update_entry(st.session_state['edit_data']['id'], writer, text, keywords, category)
                        st.success("✅ 수정 완료!")
                        st.session_state['edit_mode'] = False
                        st.session_state['edit_data'] = {}
                        st.rerun()
                    else:
                        save_entry(writer, text, keywords, category)
                        st.success(f"✅ 저장 완료! ({category})")

    st.markdown("---")
    
    df = load_data()
    c_title, c_filter1, c_filter2 = st.columns([2, 1, 1], gap="small")
    with c_title: st.subheader("📜 이전 기록 참고하기")
    
    if not df.empty:
        df['week_str'] = df['date'].apply(get_month_week_str)
        all_writers = sorted(list(set(df['writer'].dropna())))
        with c_filter1: selected_writer = st.selectbox("작성자", ["전체 보기"] + all_writers, label_visibility="collapsed")
        with c_filter2: selected_week = st.selectbox("주차 선택", ["전체 기간"] + sorted(list(set(df['week_str'].dropna())), reverse=True), label_visibility="collapsed")
        
        display_df = df.copy()
        if selected_writer != "전체 보기": display_df = display_df[display_df['writer'] == selected_writer]
        if selected_week != "전체 기간": display_df = display_df[display_df['week_str'] == selected_week]
        
        display_df = display_df.sort_values(by="date", ascending=False)
        
        for idx, row in display_df.iterrows():
            with st.container(border=True):
                # 수직 중앙 정렬 적용
                c_head, c_btn1, c_btn2 = st.columns([8.8, 0.6, 0.6], gap="small", vertical_alignment="center")
                with c_head:
                    date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                    st.markdown(f"""<div style="display: flex; align-items: center; height: 100%;"><span style="color: #9CA3AF; font-size: 0.9rem;">{date_str}</span><span style="margin: 0 10px; color: #555;">|</span><span style="font-weight: bold; font-size: 1.1rem;">{row['writer']}</span></div>""", unsafe_allow_html=True)
                with c_btn1:
                    if st.button("수정", key=f"edit_{row['id']}"):
                        st.session_state['edit_mode'] = True
                        st.session_state['edit_data'] = row.to_dict()
                        st.rerun()
                with c_btn2:
                    if st.button("삭제", key=f"del_{row['id']}"):
                        confirm_delete_dialog(row['id'])

                st.markdown(f'<hr style="border: 0; border-top: 1px solid #30333F; margin: 5px 0 15px 0;">', unsafe_allow_html=True)

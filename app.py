import streamlit as st
import pandas as pd
import json
import datetime
import google.generativeai as genai
import plotly.express as px
import plotly.graph_objects as go
import uuid
import time
from streamlit_gsheets import GSheetsConnection

# -----------------------------------------------------------------------------
# 1. 설정 및 기본 함수
# -----------------------------------------------------------------------------
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"
CARD_BG_COLOR = "#0E1117" # 메인 카드 배경색 (어두운색)

# 모델 우선순위 (쿼터 관리)
MODEL_PRIORITY_LIST = [
    "gemini-2.5-flash",       
    "gemini-2.5-flash-lite",  
    "gemini-1.5-flash"        
]

DEFAULT_CATEGORIES = [
    "기획", "디자인", "개발", "데이터", "QA", "비즈니스", "협업", "HR", "기타"
]

PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", # <-- 옅은 파란색/청자색 (키워드 텍스트)
    500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", # <-- 보라색 (카테고리 라벨 배경)
    900: "#3F2C83", 950: "#261A4C"
}

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    conn = get_connection()
    try:
        df = conn.read(ttl=0)
        if df.empty:
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])
        
        df.columns = [c.strip().lower() for c in df.columns]
        
        required_cols = ["id", "date", "writer", "text", "keywords", "category"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = ""

        if 'date' in df.columns:
            # 날짜를 datetime 객체로 변환 (time part 제거)
            df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
        
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
        return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    if 'date' in save_df.columns:
        save_df['date'] = pd.to_datetime(save_df['date']).dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)

def save_entry(writer, text, keywords, categories, date_val):
    df = load_data()
    if isinstance(categories, list):
        cat_str = json.dumps(categories, ensure_ascii=False)
    else:
        cat_str = json.dumps([str(categories)], ensure_ascii=False)

    new_data = pd.DataFrame({
        "id": [str(uuid.uuid4())],
        "date": [pd.to_datetime(date_val).normalize()],
        "writer": [writer],
        "text": [text],
        "keywords": [json.dumps(keywords, ensure_ascii=False)],
        "category": [cat_str] 
    })
    df = pd.concat([df, new_data], ignore_index=True)
    save_data_to_sheet(df)

def update_entry(entry_id, writer, text, keywords, categories, date_val):
    df = load_data()
    idx = df[df['id'] == entry_id].index
    if isinstance(categories, list):
        cat_str = json.dumps(categories, ensure_ascii=False)
    else:
        cat_str = json.dumps([str(categories)], ensure_ascii=False)

    if not idx.empty:
        df.at[idx[0], 'writer'] = writer
        df.at[idx[0], 'text'] = text
        df.at[idx[0], 'keywords'] = json.dumps(keywords, ensure_ascii=False)
        df.at[idx[0], 'category'] = cat_str
        df.at[idx[0], 'date'] = pd.to_datetime(date_val).normalize()
        save_data_to_sheet(df)

def delete_entry(entry_id):
    df = load_data()
    df = df[df['id'] != entry_id]
    save_data_to_sheet(df)

def parse_categories(cat_data):
    try:
        if isinstance(cat_data, list): return cat_data
        cat_data = str(cat_data).strip()
        if cat_data.startswith("["): return json.loads(cat_data)
        elif "," in cat_data: return [c.strip() for c in cat_data.split(",")]
        else: return [cat_data] if cat_data else ["기타"]
    except: return ["기타"]

# -----------------------------------------------------------------------------
# 2. AI 분석
# -----------------------------------------------------------------------------
def analyze_text(text):
    if GOOGLE_API_KEY == "YOUR_API_KEY":
        return ["#API_KEY_없음"], ["기타"], "None"
        
    genai.configure(api_key=GOOGLE_API_KEY)
    for model_name in MODEL_PRIORITY_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            prompt = f"""
            너는 팀의 레슨런(Lesson Learned)을 분석하는 데이터 전문가야.
            입력된 텍스트를 분석해서 JSON 형식으로 응답해.

            [규칙]
            1. keywords: 본문의 핵심 주제를 해시태그 형태의 명사로 2~3개 추출. (예: ["#코드리뷰", "#API설계"])
            2. categories: 본문의 성격을 나타내는 직무/분야 카테고리 1~2개 추출.
            - 참고: {', '.join(DEFAULT_CATEGORIES)} (필요하면 새로운 단어 생성 가능)
            
            [응답 예시]
            {{
                "keywords": ["#디자인시스템", "#일관성"],
                "categories": ["디자인", "협업"]
            }}
            
            텍스트: {text}
            """
            response = model.generate_content(prompt)
            text_resp = response.text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text_resp)
            
            kws = result.get("keywords", [])
            cats = result.get("categories", ["기타"])
            
            kws = [k for k in kws if k and str(k).strip() and k != "#분석불가"]
            if not kws: kws = ["#일반"]
            if isinstance(cats, str): cats = cats
            
            # print(f"✅ Success with {model_name}")
            return kws, cats, model_name

        except Exception as e:
            # print(f"⚠️ {model_name} failed: {e}")
            time.sleep(1) 
            continue
    return ["#AI오류"], ["기타"], "None"


def get_current_week_dates():
    """현재 주(월요일 ~ 일요일)의 시작일과 종료일을 반환합니다."""
    today = datetime.date.today()
    start_of_week = today - datetime.timedelta(days=today.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)
    return pd.Timestamp(start_of_week).normalize(), pd.Timestamp(end_of_week).normalize()

# -----------------------------------------------------------------------------
# 3. Streamlit UI
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

if 'edit_mode' not in st.session_state:
    st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state:
    st.session_state['edit_data'] = {}

@st.dialog("⚠️ 삭제 확인")
def confirm_delete_dialog(entry_id):
    st.write("정말 이 기록을 삭제하시겠습니까?")
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
    
    div[data-testid="stMetric"] {{ background-color: {CARD_BG_COLOR}; border: 1px solid #30333F; padding: 15px; border-radius: 10px; }}
    div[data-testid="stMetricLabel"] {{ color: #9CA3AF !important; }}
    div[data-testid="stMetricValue"] {{ color: white !important; font-weight: 700 !important; }}
    
    /* Plotly는 template="plotly_dark"를 사용 */
    
    /* [수정] 태그 아래 마진(여백) 및 키워드 폰트/색상 설정 */
    .tag-container {{
        margin-top: 10px;
        margin-bottom: 20px; /* 다음 기록과의 간격 확보 */
    }}
    
    /* 이름/버튼 아래 가로줄 마진 조정 */
    hr {{ 
        margin-top: 5px;   
        margin-bottom: 5px; 
        border-top: 1px solid #30333F;
    }}
    
    /* st.container 하단 마진을 줄여서 전체 카드 간격을 줄임 */
    div[data-testid="stVerticalBlock"] > div:nth-child(2) > div {{ 
        margin-bottom: 10px !important; 
    }}

    /* [수정] 버튼 크기 줄이기 */
    /* 버튼 텍스트와 패딩 조정 */
    div[data-testid="stButton"] > button {{
        padding-top: 4px;
        padding-bottom: 4px;
        font-size: 0.75rem; /* 텍스트 크기 축소 */
    }}
    
    /* [수정] 수직 가운데 정렬을 위한 flexbox 적용 */
    div[data-testid="stHorizontalBlock"] {{
        align-items: center; /* 수직 가운데 정렬 */
    }}
    
    /* 이름/날짜 정보 블록 */
    .info-block {{
        display: flex;
        flex-direction: column;
        justify-content: center;
        height: 100%; 
    }}
    
    /* [수정] 마크다운 깨짐 방지 및 스타일링 통일 */
    .writer-name {{
        font-weight: bold;
        font-size: 1.05rem; /* 이름 폰트 크기 */
        color: white;
    }}
    .date-info {{
        color: #9CA3AF; /* 회색 계열 */
        font-size: 0.9em;
        margin-left: 10px;
    }}

    /* [신규] 카테고리 라벨 스타일 (보라색) */
    .cat-badge {{
        background-color: {PURPLE_PALETTE[800]}; /* 보라색 배경 */
        color: white;
        padding: 3px 6px;
        border-radius: 10px;
        font-size: 0.8rem; /* 폰트 크기 통일 */
        font-weight: 500;
        margin-right: 5px;
    }}

    /* [신규] 키워드 텍스트 스타일 (옅은 파란색) */
    .keyword-text {{
        color: {PURPLE_PALETTE[400]}; /* 옅은 파란색/청자색 */
        font-size: 0.8rem; /* 폰트 크기 통일 */
        font-weight: 500;
    }}
    </style>
""", unsafe_allow_html=True)

col_head1, col_head2 = st.columns([5, 1])
with col_head1:
    st.title("Team Lesson Learned 🚀")
    st.caption("AI 자동 분류 및 모델 자동 전환 지원")
with col_head2:
    if GOOGLE_API_KEY != "YOUR_API_KEY":
        st.markdown(f'<div style="text-align: right;"><span style="color:{PURPLE_PALETTE[500]}; font-weight:bold; border:1px solid {PURPLE_PALETTE[500]}; padding:5px 10px; border-radius:20px;">🟢 AI Ready</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align: right;"><span style="color:#F44336; font-weight:bold; border:1px solid #F44336; padding:5px 10px; border-radius:20px;">🔴 API Key Missing</span></div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

# ==============================================================================
# TAB 1: 입력 및 필터링된 기록
# ==============================================================================
with tab1:
    df = load_data()
    
    # --------------------------------------------------
    # 1. 기록/수정 폼
    # --------------------------------------------------
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        
        form_writer = st.session_state['edit_data'].get('writer', '')
        form_text = st.session_state['edit_data'].get('text', '')
        saved_date = st.session_state['edit_data'].get('date')
        if isinstance(saved_date, (pd.Timestamp, datetime.datetime, datetime.date)):
            form_date = saved_date.date()
        else:
            form_date = datetime.date.today()
    else:
        st.subheader("이번주의 레슨런을 기록해주세요")
        form_writer = ""
        form_text = ""
        form_date = datetime.date.today()
        
    # [수정] 취소 버튼을 폼 바깥에 배치하여 오류 회피
    if st.session_state['edit_mode']:
        col_outside_cancel, col_outside_dummy = st.columns([1, 3])
        with col_outside_cancel:
            if st.button("취소하고 새 글 쓰기", key="cancel_edit_outside", use_container_width=True):
                st.session_state['edit_mode'] = False
                st.session_state['edit_data'] = {}
                st.rerun()


    with st.form("record_form", clear_on_submit=True):
        c_input1, c_input2 = st.columns([1, 1])
        with c_input1:
            writer = st.text_input("작성자", value=form_writer, placeholder="이름 입력", key="form_writer")
        with c_input2:
            selected_date = st.date_input("날짜", value=form_date, key="form_date")
        
        text = st.text_area("내용 (Markdown 지원)", value=form_text, height=300, placeholder="배운 점, 문제 해결 과정 등을 자유롭게 적어주세요. AI가 자동으로 태그를 달아줍니다.", key="form_text")
        
        if st.session_state['edit_mode']:
            submitted = st.form_submit_button("수정 완료", type="primary", use_container_width=True)
        else:
            submitted = st.form_submit_button("기록 저장하기", type="primary", use_container_width=True)


        if submitted:
            # 폼 제출 후 처리 로직 (수정 완료 또는 저장하기)
            if not writer or not text:
                st.error("작성자와 내용을 모두 입력해주세요.")
            else:
                with st.spinner("✨ AI 분석 및 저장 중..."):
                    ai_keywords, ai_cats, used_model = analyze_text(text)
                    if used_model == "None" and GOOGLE_API_KEY != "YOUR_API_KEY":
                         st.error("AI 모델 연결 실패. 잠시 후 다시 시도해주세요.")
                    elif GOOGLE_API_KEY == "YOUR_API_KEY":
                        st.warning("API 키가 없어 자동 분석은 건너뛰었습니다. (태그: #API_KEY_없음)")
                        ai_keywords, ai_cats = ["#API_KEY_없음"], ["기타"]
                        used_model = "Manual"
                    
                    if st.session_state['edit_mode']:
                        update_entry(
                            st.session_state['edit_data']['id'], 
                            writer, text, ai_keywords, ai_cats, selected_date
                        )
                        st.success(f"✅ 수정 완료! (Model: {used_model})")
                        st.session_state['edit_mode'] = False
                        st.session_state['edit_data'] = {}
                        st.rerun()
                    else:
                        save_entry(writer, text, ai_keywords, ai_cats, selected_date)
                        st.success(f"✅ 저장 완료! (태그: {', '.join(ai_cats)} / Model: {used_model})")

    st.markdown("---")
    
    # --------------------------------------------------
    # 2. 기록 목록 및 필터링 (Tab 1 전용)
    # --------------------------------------------------
    st.subheader("🔍 기록 조회")
    
    if not df.empty:
        # 필터 위젯 설정
        all_writers = ["전체"] + sorted(df['writer'].unique().tolist())
        col_filter1, col_filter2 = st.columns([1, 1])
        
        with col_filter1:
            writer_filter = st.selectbox("작성자 필터", all_writers, index=0, key="tab1_writer_filter")
            
        with col_filter2:
            default_date = datetime.date.today()
            date_filter = st.date_input("특정 날짜", value=default_date, key="tab1_date_filter")

        
        # 필터링 로직
        current_week_start, current_week_end = get_current_week_dates()
        
        # 1. 기본 필터 (이번 주)
        filtered_df = df[
            (df['date'] >= current_week_start) & 
            (df['date'] <= current_week_end)
        ].copy()
        
        is_filtered_by_user = (writer_filter != "전체") or (date_filter != default_date)
        
        if is_filtered_by_user:
            filtered_df = df.copy()
            
            if writer_filter != "전체":
                filtered_df = filtered_df[filtered_df['writer'] == writer_filter]
                
            if date_filter != default_date:
                date_filter_ts = pd.Timestamp(date_filter).normalize()
                filtered_df = filtered_df[filtered_df['date'] == date_filter_ts]

            st.caption(f"**필터링**된 기록 (총 {len(filtered_df)}건)")
        else:
            st.caption(f"**이번 주 기록** (총 {len(filtered_df)}건, {current_week_start.date()} ~ {current_week_end.date()})")

        # 목록 출력 (풀어서 표시)
        if not filtered_df.empty:
            filtered_df = filtered_df.sort_values(by="date", ascending=False)
            
            for idx, row in filtered_df.iterrows():
                with st.container(border=True):
                    # [요청 반영] 이름 / 작성일 / 수정 / 삭제 구성 및 수직 중앙 정렬
                    col_info, col_btn_edit, col_btn_del = st.columns([6, 1, 1])
                    
                    date_str = row['date'].strftime('%Y-%m-%d')
                    
                    with col_info:
                        # 순수 HTML/CSS로 스타일링 적용 (마크다운 오류 해결)
                        info_html = f"""
                        <div class='info-block'>
                            <span class='writer-name'>{row['writer']}</span>
                            <span class='date-info'>({date_str} 작성)</span>
                        </div>
                        """
                        st.markdown(info_html, unsafe_allow_html=True)
                    
                    with col_btn_edit:
                        # [수정] 버튼 크기 축소 (CSS로 적용)
                        if st.button("수정", key=f"edit_tab1_{row['id']}", use_container_width=True):
                            st.session_state['edit_mode'] = True
                            st.session_state['edit_data'] = row.to_dict()
                            st.rerun()
                    with col_btn_del:
                        # [수정] 버튼 크기 축소 (CSS로 적용)
                        if st.button("삭제", key=f"del_tab1_{row['id']}", use_container_width=True):
                            confirm_delete_dialog(row['id'])

                    # 내용 및 태그
                    st.markdown("<hr>", unsafe_allow_html=True) # 마진 조정된 hr 사용
                    st.markdown(row['text'])
                    
                    cats = parse_categories(row['category'])
                    try: kws = json.loads(row['keywords'])
                    except: kws = []
                    
                    # [수정] 키워드를 #이 붙은 텍스트로 변경
                    keyword_text = " ".join([f"#{k}" for k in kws])
                    
                    # 카테고리 (작은 뱃지 형태 유지, 보라색 배경)
                    cat_badges = "".join([f'<span class="cat-badge">{c}</span>' for c in cats])
                    
                    
                    # 태그 아래 마진을 위해 .tag-container 사용
                    st.markdown(f"<div class='tag-container'>{cat_badges} <span class='keyword-text'>{keyword_text}</span></div>", unsafe_allow_html=True)
        else:
            if is_filtered_by_user:
                st.info("선택한 조건에 맞는 기록이 없습니다.")
            else:
                st.info("이번 주에 작성된 기록이 없습니다.")
    else:
        st.info("아직 기록이 없습니다.")


# ==============================================================================
# TAB 2: 대시보드 및 전체 목록 (카테고리 필터)
# ==============================================================================
with tab2:
    df = load_data()
    if not df.empty:
        # 데이터 전처리
        all_cats_flat = []
        for c_data in df['category']:
             all_cats_flat.extend(parse_categories(c_data))
        
        total = len(df)
        top_cat = pd.Series(all_cats_flat).mode()[0] if all_cats_flat else "-"
        top_writer = df['writer'].mode()[0] if not df['writer'].empty else "-"
        
        try:
            all_kws = []
            for k in df['keywords']: all_kws.extend(json.loads(k))
        except: all_kws = []
        
        # 1. 핵심 지표
        st.subheader("Key Metrics")
        col_kpi_1, col_kpi_2, col_kpi_3, col_kpi_4 = st.columns(4)
        
        with col_kpi_1: st.metric("총 기록 수", f"{total}건")
        with col_kpi_2: st.metric("가장 핫한 주제", top_cat)
        with col_kpi_3: st.metric("누적 키워드", f"{len(set(all_kws))}개")
        with col_kpi_4: st.metric("최다 작성자", top_writer)
        
        st.divider() 
        
        # 2. 트리맵 (Lesson Map) - 풀 너비
        st.subheader("🗺️ Lesson Map (카테고리 비중)")
        st.caption("가장 많은 기록이 있는 카테고리를 시각적으로 보여줍니다.")
        if all_cats_flat:
            cat_counts = pd.Series(all_cats_flat).value_counts().reset_index()
            cat_counts.columns = ['Category', 'Value']
            
            # Plotly Treemap
            fig_tree = px.treemap(
                cat_counts, 
                path=['Category'], 
                values='Value',
                color='Value',
                color_continuous_scale=[(0, PURPLE_PALETTE[400]), (1, PURPLE_PALETTE[900])]
            )
            # [수정] 배경색 설정 및 template="plotly_dark" 사용
            fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=350, template="plotly_dark", 
                                   paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
            fig_tree.update_traces(textfont=dict(family="Pretendard", color="white", size=18))
            st.plotly_chart(fig_tree, use_container_width=True)
        else:
            st.info("데이터 부족")

        st.divider()
        
        # 3. 파이 차트 & 바 차트
        st.subheader("📊 상세 분석")
        col_pie, col_bar = st.columns(2)

        with col_pie:
            st.caption("Category Ratio")
            if all_cats_flat:
                cat_counts_pie = pd.Series(all_cats_flat).value_counts().reset_index()
                cat_counts_pie.columns = ['category', 'count']
                fig_pie = px.pie(cat_counts_pie, values='count', names='category', hole=0.5, 
                                 color_discrete_sequence=[PURPLE_PALETTE[x] for x in [500, 600, 700, 800, 900]])
                # [수정] 차트 배경색 설정
                fig_pie.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20), template="plotly_dark", 
                                      paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("데이터 부족")
        
        with col_bar:
            st.caption("Top 10 Keywords")
            if all_kws:
                kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                kw_counts.columns = ['keyword', 'count']
                fig_bar = go.Figure(go.Bar(
                    x=kw_counts['count'], y=kw_counts['keyword'], orientation='h',
                    text=kw_counts['count'], textposition='outside',
                    marker=dict(color=PURPLE_PALETTE[600])
                ))
                # [수정] 차트 배경색 설정
                fig_bar.update_layout(
                    xaxis=dict(showgrid=False, visible=False), 
                    yaxis=dict(showgrid=False, autorange="reversed"),
                    height=350, margin=dict(t=20, b=20, l=10, r=40),
                    paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR, template="plotly_dark"
                )
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.info("데이터 부족")

        st.divider()

        # 4. 전체 목록 필터링 (Category Filter) - 조회 전용 (버튼 제거)
        st.subheader("🗂️ 전체 레슨런 목록 (카테고리 필터)")
        
        unique_categories = sorted(list(set(all_cats_flat)))
        
        col_filter, col_empty = st.columns([1, 3])
        with col_filter:
            selected_cat_filter = st.selectbox(
                "카테고리 선택", 
                ["전체 보기"] + unique_categories,
                index=0,
                key="dashboard_cat_filter"
            )
        
        # 데이터 필터링 로직
        if selected_cat_filter == "전체 보기":
            filtered_df_dash = df.copy()
        else:
            filtered_df_dash = df[df['category'].apply(lambda x: selected_cat_filter in parse_categories(x))]
        
        # 목록 출력 (수정/삭제 버튼 제거)
        if not filtered_df_dash.empty:
            filtered_df_dash = filtered_df_dash.sort_values(by="date", ascending=False)
            st.caption(f"총 {len(filtered_df_dash)}건의 기록이 있습니다.")
            
            for idx, row in filtered_df_dash.iterrows():
                with st.container(border=True):
                    # 헤더: 날짜 | 작성자 (버튼 없음)
                    c1 = st.columns([1])[0]
                    with c1:
                        date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                        # 순수 HTML/CSS로 스타일링 적용 (마크다운 오류 해결)
                        info_html = f"""
                        <div class='info-block'>
                            <span class='writer-name'>{row['writer']}</span>
                            <span class='date-info'>{date_str}</span>
                        </div>
                        """
                        st.markdown(info_html, unsafe_allow_html=True)
                    
                    st.markdown("---")
                    st.markdown(row['text'])
                    
                    # 태그 뱃지
                    cats = parse_categories(row['category'])
                    try: kws = json.loads(row['keywords'])
                    except: kws = []
                    
                    # [수정] 키워드를 #이 붙은 텍스트로 변경
                    keyword_text = " ".join([f"#{k}" for k in kws])
                    
                    # 카테고리 (작은 뱃지 형태 유지, 보라색 배경)
                    cat_badges = "".join([f'<span class="cat-badge">{c}</span>' for c in cats])
                    
                    
                    # 태그 아래 마진을 위해 .tag-container 사용
                    st.markdown(f"<div class='tag-container'>{cat_badges} <span class='keyword-text'>{keyword_text}</span></div>", unsafe_allow_html=True)
        else:
            st.info("해당 카테고리의 글이 없습니다.")

    else:
        st.info("데이터를 입력하면 대시보드가 활성화됩니다.")

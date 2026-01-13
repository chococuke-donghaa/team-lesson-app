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
# 1. 페이지 설정 (가장 먼저 실행)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

# -----------------------------------------------------------------------------
# 2. 테마 및 색상 설정 (동적 테마 지원)
# -----------------------------------------------------------------------------
# [핵심] 사이드바에서 다크/라이트 모드 전환
with st.sidebar:
    st.header("⚙️ 설정")
    is_dark_mode = st.toggle("🌙 다크 모드 켜기", value=True)

# 모드에 따른 색상 변수 정의
if is_dark_mode:
    MAIN_BG_COLOR = "#0E1117"  # 다크 모드 배경
    CARD_BG_COLOR = "#0E1117"  # 차트 배경 (앱 배경과 일치시켜 경계 제거)
    TEXT_COLOR = "white"
    PLOTLY_TEMPLATE = "plotly_dark"
    METRIC_BORDER_COLOR = "#30333F"
else:
    MAIN_BG_COLOR = "#FFFFFF"  # 라이트 모드 배경
    CARD_BG_COLOR = "#FFFFFF"  # 차트 배경 (앱 배경과 일치시켜 경계 제거)
    TEXT_COLOR = "black"
    PLOTLY_TEMPLATE = "plotly_white"
    METRIC_BORDER_COLOR = "#E0E0E0"

# [핵심] CSS로 앱 전체 배경색 강제 적용 (차트와 이질감 없애기 위해 필수)
st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; color: {TEXT_COLOR}; }}
    
    /* 앱 전체 배경색 강제 변경 */
    .stApp {{
        background-color: {MAIN_BG_COLOR};
    }}
    
    .appview-container .main .block-container {{ max-width: 1080px; margin: 0 auto; }}
    
    /* 메트릭 박스 스타일 */
    div[data-testid="stMetric"] {{ 
        background-color: {CARD_BG_COLOR}; 
        border: 1px solid {METRIC_BORDER_COLOR}; 
        padding: 15px; 
        border-radius: 10px; 
    }}
    div[data-testid="stMetricLabel"] p {{ color: {'#9CA3AF' if is_dark_mode else '#555'} !important; }}
    div[data-testid="stMetricValue"] div {{ color: {TEXT_COLOR} !important; }}
    
    .tag-container {{ margin-top: 10px; margin-bottom: 20px; }}
    hr {{ margin: 5px 0 5px 0; border-top: 1px solid {METRIC_BORDER_COLOR}; }}
    div[data-testid="stButton"] > button {{ padding-top: 4px; padding-bottom: 4px; font-size: 0.75rem; }}
    .writer-name {{ font-weight: bold; font-size: 1.05rem; color: {TEXT_COLOR}; }}
    .date-info {{ color: {'#9CA3AF' if is_dark_mode else '#666'}; font-size: 0.9em; margin-left: 10px; }}
    
    /* 뱃지 스타일 */
    .cat-badge {{ 
        background-color: {'#4A2EA5' if is_dark_mode else '#E6E6FA'}; 
        color: {'white' if is_dark_mode else '#333'}; 
        padding: 3px 6px; border-radius: 10px; font-size: 0.8rem; font-weight: 500; margin-right: 5px; 
    }}
    .keyword-text {{ 
        color: {'#7E72FA' if is_dark_mode else '#4A2EA5'}; 
        font-size: 0.8rem; font-weight: 500; 
    }}
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 3. 상수 및 데이터 함수
# -----------------------------------------------------------------------------
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"
MODEL_PRIORITY_LIST = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]

DEFAULT_CATEGORIES = [
    "기획/PM", "디자인/UX", "개발/구현", "QA/테스트", "데이터/AI",
    "비즈니스/전략", "마케팅/그로스", "운영/CS", "영업/제휴",
    "인프라/보안", "HR/조직문화", "재무/총무/법무", 
    "협업/커뮤니케이션", "생산성/툴", "자기계발/인사이트", "기타"
]

PURPLE_PALETTE = {
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83"
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
            if col not in df.columns: df[col] = ""

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.normalize()
        
        df = df.fillna("")
        return df
    except:
        return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    if 'date' in save_df.columns:
        save_df['date'] = pd.to_datetime(save_df['date']).dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)

def save_entry(entry_id, writer, text, keywords, categories, date_val):
    df = load_data()
    cat_str = json.dumps(categories if isinstance(categories, list) else [str(categories)], ensure_ascii=False)
    kw_str = json.dumps(keywords if isinstance(keywords, list) else [str(keywords)], ensure_ascii=False)

    new_data = pd.DataFrame({
        "id": [entry_id], "date": [pd.to_datetime(date_val).normalize()],
        "writer": [writer], "text": [text], "keywords": [kw_str], "category": [cat_str] 
    })
    df = pd.concat([df, new_data], ignore_index=True)
    save_data_to_sheet(df)

def update_entry(entry_id, writer, text, keywords, categories, date_val):
    df = load_data()
    idx = df[df['id'] == entry_id].index
    if not idx.empty:
        df.at[idx[0], 'writer'] = writer
        df.at[idx[0], 'text'] = text
        df.at[idx[0], 'keywords'] = json.dumps(keywords, ensure_ascii=False)
        df.at[idx[0], 'category'] = json.dumps(categories, ensure_ascii=False)
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
        return [c.strip() for c in cat_data.split(",")] if "," in cat_data else [cat_data] if cat_data else ["기타"]
    except: return ["기타"]

def analyze_text(text):
    if GOOGLE_API_KEY == "YOUR_API_KEY": return ["#API_KEY_없음"], ["기타"], "None"
    genai.configure(api_key=GOOGLE_API_KEY)
    categories_str = ", ".join(DEFAULT_CATEGORIES)

    for model_name in MODEL_PRIORITY_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            prompt = f"""
            너는 팀의 업무 회고(Lesson Learned)를 분류하는 데이터 관리자야.
            입력된 텍스트를 분석해서 JSON 형식으로 응답해.
            1. categories: 아래 목록 중 가장 적합한 것 1~2개 선택. 목록에 없는 단어 생성 금지.
               목록: {categories_str}
            2. keywords: 구체적인 기술명, 프로젝트명 등을 해시태그(#) 명사로 2~3개 추출.
            텍스트: {text}
            """
            response = model.generate_content(prompt)
            result = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            return result.get("keywords", []), [c for c in result.get("categories", ["기타"]) if c in DEFAULT_CATEGORIES] or ["기타"], model_name
        except: time.sleep(1); continue
    return ["#AI오류"], ["기타"], "None"

# -----------------------------------------------------------------------------
# 4. 주차 계산 함수 (목요일 기준 표준 방식)
# -----------------------------------------------------------------------------
def get_week_label_and_start(date_obj):
    if pd.isna(date_obj): return None, None
    ts = pd.to_datetime(date_obj).normalize()
    start_of_week = ts - datetime.timedelta(days=ts.weekday()) # 월요일
    thursday_of_week = start_of_week + datetime.timedelta(days=3)
    label = f"{thursday_of_week.year % 100}년 {thursday_of_week.month}월 {(thursday_of_week.day - 1) // 7 + 1}주차"
    return label, start_of_week.normalize()

def get_all_week_options(df):
    if df.empty: return ["이번 주 기록"]
    week_label_data = df['date'].dropna().apply(lambda x: get_week_label_and_start(x))
    week_labels = week_label_data.apply(lambda x: x[0]).unique()
    
    current_label, _ = get_week_label_and_start(datetime.date.today())
    options = ([current_label] if current_label not in week_labels else []) + list(week_labels)
    
    def parse_sort(label):
        if '년' in label:
            p = label.split()
            try: return datetime.date(2000 + int(p[0][:-1]), int(p[1][:-1]), 1)
            except: pass
        return datetime.date(2100, 1, 1)
    
    options.sort(key=parse_sort, reverse=True)
    return ["이번 주 기록"] + [o for o in pd.unique(options) if o != current_label and o != "이번 주 기록"]

def get_week_range(week_label):
    if week_label == "이번 주 기록":
        today = datetime.date.today()
        start = today - datetime.timedelta(days=today.weekday())
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    try:
        p = week_label.split()
        target_day = datetime.date(int(p[0][:-1]) + 2000, int(p[1][:-1]), 1) + datetime.timedelta(days=(int(p[2][:-2]) - 1) * 7)
        start = target_day - datetime.timedelta(days=target_day.weekday())
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    except: return get_week_range("이번 주 기록")

# -----------------------------------------------------------------------------
# 5. UI 및 로직
# -----------------------------------------------------------------------------
if 'edit_mode' not in st.session_state: st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state: st.session_state['edit_data'] = {}

@st.dialog("⚠️ 삭제 확인")
def confirm_delete_dialog(entry_id):
    st.write("삭제하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("삭제", type="primary", use_container_width=True):
        delete_entry(entry_id); st.rerun()
    if c2.button("취소", use_container_width=True): st.rerun()

st.title("Team Lesson Learned 🚀")
tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

with tab1:
    df = load_data()
    
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        e_data = st.session_state['edit_data']
        c1, c2 = st.columns(2)
        new_writer = c1.text_input("작성자", value=e_data.get('writer', ''))
        new_date = c2.date_input("날짜", value=e_data.get('date', datetime.date.today()))
        new_text = st.text_area("내용", value=e_data.get('text', ''), height=300)

        col_submit, col_cancel = st.columns([1, 1])
        if col_submit.button("수정 완료", type="primary", use_container_width=True):
            if new_writer and new_text:
                with st.spinner("AI 재분석 중..."):
                    kws, cats, _ = analyze_text(new_text)
                    update_entry(e_data['id'], new_writer, new_text, kws, cats, new_date)
                    st.success("✅ 수정 완료!"); st.session_state['edit_mode'] = False; st.rerun()
            else: st.error("내용을 입력하세요.")
        if col_cancel.button("취소하고 새 글 쓰기", use_container_width=True):
            st.session_state['edit_mode'] = False; st.session_state['edit_data'] = {}; st.rerun()

    else:
        st.subheader("이번주의 레슨런을 기록해주세요")
        with st.form("record_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            writer = c1.text_input("작성자", placeholder="이름 입력")
            date_sel = c2.date_input("날짜", value=datetime.date.today())
            text = st.text_area("내용", height=300, placeholder="배운 점을 자유롭게 적어주세요.")
            if st.form_submit_button("기록 저장하기", type="primary", use_container_width=True):
                if writer and text:
                    with st.spinner("AI 분석 중..."):
                        kws, cats, _ = analyze_text(text)
                        save_entry(str(uuid.uuid4()), writer, text, kws, cats, date_sel)
                        st.success("✅ 저장 완료!"); st.rerun()
                else: st.error("내용 입력 필요")

    st.divider()
    st.subheader("🔍 기록 조회")
    
    if not df.empty:
        c_f1, c_f2 = st.columns(2)
        w_filter = c_f1.selectbox("작성자 필터", ["전체"] + sorted(df['writer'].unique().tolist()))
        t_filter = c_f2.selectbox("주차 필터", get_all_week_options(df))
        
        start_dt, end_dt = get_week_range(t_filter)
        f_df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].copy()
        if w_filter != "전체": f_df = f_df[f_df['writer'] == w_filter]
        
        st.caption(f"**필터링** (총 {len(f_df)}건, {start_dt.date()} ~ {end_dt.date()})")
        
        for _, row in f_df.sort_values("date", ascending=False).iterrows():
            with st.container(border=True):
                c1, c2, c3 = st.columns([6, 1, 1])
                c1.markdown(f"<div class='info-block'><span class='writer-name'>{row['writer']}</span><span class='date-info'>({row['date'].strftime('%Y-%m-%d')})</span></div>", unsafe_allow_html=True)
                if c2.button("수정", key=f"e_{row['id']}", use_container_width=True):
                    st.session_state['edit_mode'] = True; st.session_state['edit_data'] = row.to_dict(); st.rerun()
                if c3.button("삭제", key=f"d_{row['id']}", use_container_width=True): confirm_delete_dialog(row['id'])
                
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown(row['text'])
                try: kws = json.loads(row['keywords'])
                except: kws = []
                st.markdown(f"<div class='tag-container'>{''.join([f'<span class=cat-badge>{c}</span>' for c in parse_categories(row['category'])])} <span class='keyword-text'>{' '.join([f'#{k.replace('#', '')}' for k in kws])}</span></div>", unsafe_allow_html=True)
    else: st.info("기록이 없습니다.")

with tab2:
    df = load_data()
    if not df.empty:
        all_cats = [c for cat in df['category'] for c in parse_categories(cat)]
        all_kws = [k for row in df['keywords'] for k in json.loads(row)] if not df['keywords'].empty else []

        st.subheader("Key Metrics")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 기록 수", f"{len(df)}건")
        k2.metric("Top 카테고리", pd.Series(all_cats).mode()[0] if all_cats else "-")
        k3.metric("누적 키워드", f"{len(set(all_kws))}개")
        k4.metric("최다 작성자", df['writer'].mode()[0] if not df['writer'].empty else "-")
        
        st.divider()
        st.subheader("🗺️ Lesson Map")
        if all_cats:
            cat_counts = pd.Series(all_cats).value_counts().reset_index()
            cat_counts.columns = ['Category', 'Value']
            fig = px.treemap(cat_counts, path=['Category'], values='Value', color='Value',
                             color_continuous_scale=[(0, PURPLE_PALETTE[400]), (1, PURPLE_PALETTE[900])])
            fig.update_layout(
                margin=dict(t=0, l=0, r=0, b=0), height=350,
                template=PLOTLY_TEMPLATE, # [핵심] 템플릿 동적 적용
                paper_bgcolor=CARD_BG_COLOR, # [핵심] 배경색 동적 적용
                plot_bgcolor=CARD_BG_COLOR,
                font=dict(color=TEXT_COLOR, family="Pretendard"),
                coloraxis_showscale=False
            )
            fig.update_traces(
                textfont=dict(size=18, color="white"), # 트리맵 안쪽 글씨는 항상 흰색 유지 (배경이 진하므로)
                marker=dict(line=dict(width=1, color=METRIC_BORDER_COLOR)),
                texttemplate="<b>%{label}</b><br>%{value}건",
                root_color=CARD_BG_COLOR # [핵심] 루트 노드 색상 동적 적용
            )
            st.plotly_chart(fig, use_container_width=True, theme=None)
        
        st.divider()
        st.subheader("📊 상세 분석")
        c1, c2 = st.columns(2)
        with c1:
            st.caption("Category Ratio")
            if all_cats:
                fig_pie = px.pie(pd.Series(all_cats).value_counts().reset_index(name='count').rename(columns={'index':'category'}), 
                                 values='count', names='category', hole=0.5,
                                 color_discrete_sequence=[PURPLE_PALETTE[x] for x in [500, 600, 700, 800, 900]])
                fig_pie.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20), template=PLOTLY_TEMPLATE,
                                      paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                st.plotly_chart(fig_pie, use_container_width=True, theme=None)
        with c2:
            st.caption("Top 10 Keywords")
            if all_kws:
                kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                kw_counts.columns = ['keyword', 'count']
                fig_bar = go.Figure(go.Bar(x=kw_counts['count'], y=kw_counts['keyword'], orientation='h',
                                           marker=dict(color=PURPLE_PALETTE[600]), text=kw_counts['count'], textposition='outside'))
                fig_bar.update_layout(xaxis=dict(visible=False), yaxis=dict(autorange="reversed"),
                                      height=350, margin=dict(t=20, b=20, l=10, r=40),
                                      paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR, template=PLOTLY_TEMPLATE)
                st.plotly_chart(fig_bar, use_container_width=True, theme=None)

        st.divider()
        st.subheader("🗂️ 전체 목록")
        cats_list = sorted(list(set(all_cats)))
        sel_cat = st.selectbox("카테고리 선택", ["전체 보기"] + cats_list, key="dash_cat")
        f_df = df if sel_cat == "전체 보기" else df[df['category'].apply(lambda x: sel_cat in parse_categories(x))]
        
        if not f_df.empty:
            for _, row in f_df.sort_values("date", ascending=False).iterrows():
                with st.container(border=True):
                    st.markdown(f"<div class='info-block'><span class='writer-name'>{row['writer']}</span><span class='date-info'>{row['date'].strftime('%Y-%m-%d')}</span></div>", unsafe_allow_html=True)
                    st.markdown("<hr>", unsafe_allow_html=True)
                    st.markdown(row['text'])
                    kws = json.loads(row['keywords']) if row['keywords'] else []
                    st.markdown(f"<div class='tag-container'>{''.join([f'<span class=cat-badge>{c}</span>' for c in parse_categories(row['category'])])} <span class='keyword-text'>{' '.join([f'#{k.replace('#', '')}' for k in kws])}</span></div>", unsafe_allow_html=True)

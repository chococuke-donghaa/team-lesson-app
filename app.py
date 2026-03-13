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
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"

MODEL_PRIORITY_LIST = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]

DEFAULT_CATEGORIES = [
    "기획/PM", "디자인/UX", "개발/구현", "QA/테스트", "데이터/AI",
    "비즈니스/전략", "마케팅/그로스", "운영/CS", "영업/제휴",
    "인프라/보안", "HR/조직문화", "재무/총무/법무", 
    "협업/커뮤니케이션", "생산성/툴", "자기계발/인사이트",
    "기타"
]

PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83", 950: "#261A4C"
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

# -----------------------------------------------------------------------------
# 2. AI 분석
# -----------------------------------------------------------------------------
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

            [지시사항]
            1. categories: 반드시 아래 [허용된 카테고리 목록] 중에서 본문과 가장 밀접한 것을 1개, 복합적이라면 최대 2개만 선택해.
               - [허용된 카테고리 목록]: {categories_str}
               - ⚠️ 경고: 위 목록에 없는 단어를 창조하지 마시오.
            
            2. keywords: 카테고리만으로는 알 수 없는 구체적인 기술명, 프로젝트명, 문제 원인 등을 해시태그(#) 형태의 명사로 2~3개 추출해.

            텍스트: {text}
            """
            response = model.generate_content(prompt)
            result = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            kws = result.get("keywords", [])
            cats = result.get("categories", ["기타"])
            
            valid_cats = [c for c in cats if c in DEFAULT_CATEGORIES]
            if not valid_cats: valid_cats = ["기타"]

            return kws, valid_cats, model_name
        except: time.sleep(1); continue
    return ["#AI오류"], ["기타"], "None"

# -----------------------------------------------------------------------------
# 3. 주차 관련 함수
# -----------------------------------------------------------------------------
def get_week_label_and_start(date_obj):
    if pd.isna(date_obj): return None, None
    ts = pd.to_datetime(date_obj).normalize()
    start_of_week = ts - datetime.timedelta(days=ts.weekday())
    thursday_of_week = start_of_week + datetime.timedelta(days=3)
    week_num = (thursday_of_week.day - 1) // 7 + 1
    label = f"{thursday_of_week.year % 100}년 {thursday_of_week.month}월 {week_num}주차"
    return label, start_of_week.normalize()

def get_all_week_options(df):
    if df.empty: return ["이번 주 기록"]
    valid_dates = df['date'].dropna()
    week_label_data = valid_dates.apply(lambda x: get_week_label_and_start(x))
    week_labels = week_label_data.apply(lambda x: x[0]).unique()
    
    current_date = datetime.date.today()
    current_week_label, _ = get_week_label_and_start(current_date)
    
    options = []
    if current_week_label not in week_labels: options.append(current_week_label)
    options.extend(week_labels)
    options = list(pd.unique(options))
    
    def parse_sort(label):
        if '년' in label:
            parts = label.split()
            try:
                year = int(parts[0][:-1])
                month = int(parts[1][:-1])
                week = int(parts[2][:-2])
                return (year, month, week)
            except: pass
        return (99, 99, 99) 
    
    options.sort(key=parse_sort, reverse=True)
    return ["이번 주 기록"] + [o for o in options if o != current_week_label and o != "이번 주 기록"]

def get_week_range(week_label):
    today = datetime.date.today()
    if week_label == "이번 주 기록":
        start = today - datetime.timedelta(days=today.weekday())
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    try:
        parts = week_label.split()
        year = int(parts[0][:-1]) + 2000
        month = int(parts[1][:-1])
        week_num = int(parts[2][:-2])
        first_day_of_month = datetime.date(year, month, 1)
        
        offset_to_thursday = (3 - first_day_of_month.weekday()) % 7
        first_thursday = first_day_of_month + datetime.timedelta(days=offset_to_thursday)
        target_thursday = first_thursday + datetime.timedelta(days=(week_num - 1) * 7)
        start = target_thursday - datetime.timedelta(days=3)
        
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    except: return get_week_range("이번 주 기록")

# -----------------------------------------------------------------------------
# 4. Streamlit UI 
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

st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; }}
    
    .appview-container .main .block-container {{ max-width: 1080px; margin: 0 auto; }}
    
    .cat-badge {{ 
        background-color: {PURPLE_PALETTE[800]}; 
        color: white; 
        padding: 3px 6px; 
        border-radius: 10px; 
        font-size: 0.8rem; 
        font-weight: 500; 
        margin-right: 5px; 
    }}
    
    .keyword-text {{ 
        color: {PURPLE_PALETTE[400]}; 
        font-size: 0.8rem; 
        font-weight: 600; 
    }}
    
    .tag-container {{ margin-top: 10px; margin-bottom: 20px; }}
    div[data-testid="stButton"] > button {{ padding-top: 4px; padding-bottom: 4px; font-size: 0.75rem; }}
    .writer-name {{ font-weight: bold; font-size: 1.05rem; }}
    .date-info {{ color: gray; font-size: 0.9em; margin-left: 10px; }}
    </style>
""", unsafe_allow_html=True)

st.title("Team Lesson Learned 🚀")
tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

with tab1:
    df = load_data()
    
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        e_data = st.session_state['edit_data']
        writer_val = e_data.get('writer', '')
        text_val = e_data.get('text', '')
        date_val = e_data.get('date', datetime.date.today())
        if isinstance(date_val, pd.Timestamp): date_val = date_val.date()

        c1, c2 = st.columns(2)
        new_writer = c1.text_input("작성자", value=writer_val)
        new_date = c2.date_input("날짜", value=date_val)
        new_text = st.text_area("내용", value=text_val, height=300)

        col_submit, col_cancel = st.columns([1, 1])
        if col_submit.button("수정 완료", type="primary", use_container_width=True):
            if new_writer and new_text:
                with st.spinner("AI 재분석 중..."):
                    kws, cats, _ = analyze_text(new_text)
                    update_entry(e_data['id'], new_writer, new_text, kws, cats, new_date)
                    st.success("✅ 수정 완료!")
                    st.session_state['edit_mode'] = False
                    st.rerun()
            else:
                st.error("내용을 입력하세요.")

        if col_cancel.button("취소하고 새 글 쓰기", use_container_width=True):
            st.session_state['edit_mode'] = False
            st.session_state['edit_data'] = {}
            st.rerun()

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
                        st.success("✅ 저장 완료!")
                        st.rerun()
                else:
                    st.error("작성자와 내용을 입력해주세요.")

    st.divider()
    st.subheader("🔍 기록 조회")
    
    if not df.empty:
        writers = ["전체"] + sorted(df['writer'].unique().tolist())
        weeks = get_all_week_options(df)
        
        c_f1, c_f2 = st.columns(2)
        w_filter = c_f1.selectbox("작성자 필터", writers)
        t_filter = c_f2.selectbox("주차 필터", weeks)
        
        start_dt, end_dt = get_week_range(t_filter)
        f_df = df[(df['date'] >= start_dt) & (df['date'] <= end_dt)].copy()
        if w_filter != "전체": f_df = f_df[f_df['writer'] == w_filter]
        
        st.caption(f"**필터링** (총 {len(f_df)}건, {start_dt.date()} ~ {end_dt.date()})")
        
        for _, row in f_df.sort_values("date", ascending=False).iterrows():
            with st.container(border=True):
                c_info, c_edit, c_del = st.columns([6, 1, 1])
                d_str = row['date'].strftime('%Y-%m-%d')
                c_info.markdown(f"<div class='info-block'><span class='writer-name'>{row['writer']}</span><span class='date-info'>({d_str} 작성)</span></div>", unsafe_allow_html=True)
                
                if c_edit.button("수정", key=f"edit_{row['id']}", use_container_width=True):
                    st.session_state['edit_mode'] = True
                    st.session_state['edit_data'] = row.to_dict()
                    st.rerun()
                if c_del.button("삭제", key=f"del_{row['id']}", use_container_width=True):
                    confirm_delete_dialog(row['id'])
                
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown(row['text'])
                
                cats = parse_categories(row['category'])
                try: kws_list = json.loads(row['keywords'])
                except: kws_list = []
                
                kw_text = " ".join([f"#{k.replace('#', '')}" for k in kws_list])
                badges = "".join([f'<span class="cat-badge">{c}</span>' for c in cats])
                st.markdown(f"<div class='tag-container'>{badges} <span class='keyword-text'>{kw_text}</span></div>", unsafe_allow_html=True)
    else:
        st.info("기록이 없습니다.")

with tab2:
    df = load_data()
    if not df.empty:
        all_cats = []
        for c in df['category']: all_cats.extend(parse_categories(c))
        
        try: all_kws = [k for row in df['keywords'] for k in json.loads(row)]
        except: all_kws = []

        st.subheader("Key Metrics")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 기록 수", f"{len(df)}건")
        k2.metric("Top 카테고리", pd.Series(all_cats).mode()[0] if all_cats else "-")
        k3.metric("누적 키워드", f"{len(set(all_kws))}개")
        k4.metric("최다 작성자", df['writer'].mode()[0] if not df['writer'].empty else "-")
        
        # ---------------------------------------------------------
        # [수정] 키워드 및 비중 분석 (파이/바 차트)를 위로 올림
        # ---------------------------------------------------------
        st.divider()
        st.subheader("📊 키워드 및 비중 분석")
        c_pie, c_bar = st.columns(2)
        
        with c_pie:
            st.caption("Category Ratio")
            if all_cats:
                fig_pie = px.pie(pd.Series(all_cats).value_counts().reset_index(name='count').rename(columns={'index':'category'}), 
                                 values='count', names='category', hole=0.5,
                                 color_discrete_sequence=[PURPLE_PALETTE[x] for x in [500, 600, 700, 800, 900]])
                fig_pie.update_layout(height=350, margin=dict(t=20, b=20, l=20, r=20))
                st.plotly_chart(fig_pie, use_container_width=True)
            else: st.info("데이터 부족")
        
        with c_bar:
            st.caption("Top 10 Keywords")
            if all_kws:
                kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                kw_counts.columns = ['keyword', 'count']
                fig_bar = go.Figure(go.Bar(x=kw_counts['count'], y=kw_counts['keyword'], orientation='h',
                                           marker=dict(color=PURPLE_PALETTE[400]), text=kw_counts['count'], textposition='outside'))
                fig_bar.update_layout(xaxis=dict(visible=False), yaxis=dict(autorange="reversed"),
                                      height=350, margin=dict(t=20, b=20, l=10, r=40))
                st.plotly_chart(fig_bar, use_container_width=True)
            else: st.info("데이터 부족")

        # ---------------------------------------------------------
        # [수정] Lesson Map (트리맵)을 아래로 내림
        # ---------------------------------------------------------
        st.divider()
        st.subheader("🗺️ Lesson Map (카테고리 비중)")
        if all_cats:
            cat_counts = pd.Series(all_cats).value_counts().reset_index()
            cat_counts.columns = ['Category', 'Value']
            
            fig = px.treemap(cat_counts, path=['Category'], values='Value', color='Value',
                             color_continuous_scale=[(0, PURPLE_PALETTE[400]), (1, PURPLE_PALETTE[900])])
            
            fig.update_layout(
                margin=dict(t=0, l=0, r=0, b=0),
                height=350,
                coloraxis_showscale=False
            )
            fig.update_traces(
                texttemplate="<b>%{label}</b><br>%{value}건",
                textfont=dict(size=18)
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터 부족")

        st.divider()
        st.subheader("🗂️ 전체 레슨런 목록 (카테고리 필터)")
        
        unique_categories = sorted(list(set(all_cats)))
        
        col_list_filter, _ = st.columns([1, 3])
        with col_list_filter:
            selected_cat_filter = st.selectbox("카테고리 선택", ["전체 보기"] + unique_categories, key="tab2_cat_filter")
        
        if selected_cat_filter == "전체 보기":
            f_df_dash = df.copy()
        else:
            f_df_dash = df[df['category'].apply(lambda x: selected_cat_filter in parse_categories(x))]
        
        if not f_df_dash.empty:
            f_df_dash = f_df_dash.sort_values(by="date", ascending=False)
            st.caption(f"총 {len(f_df_dash)}건")
            
            for _, row in f_df_dash.iterrows():
                with st.container(border=True):
                    d_str = row['date'].strftime('%Y-%m-%d')
                    st.markdown(f"<div class='info-block'><span class='writer-name'>{row['writer']}</span><span class='date-info'>{d_str}</span></div>", unsafe_allow_html=True)
                    st.markdown("<hr>", unsafe_allow_html=True)
                    st.markdown(row['text'])
                    
                    cats = parse_categories(row['category'])
                    try: kws_list = json.loads(row['keywords'])
                    except: kws_list = []
                    
                    kw_text = " ".join([f"#{k.replace('#', '')}" for k in kws_list])
                    badges = "".join([f'<span class="cat-badge">{c}</span>' for c in cats])
                    st.markdown(f"<div class='tag-container'>{badges} <span class='keyword-text'>{kw_text}</span></div>", unsafe_allow_html=True)
        else:
            st.info("해당 카테고리의 글이 없습니다.")

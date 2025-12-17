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

# 1. 기본 설정
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"
CARD_BG_COLOR = "#0E1117" # 앱 메인 배경색

MODEL_PRIORITY_LIST = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-1.5-flash"]
DEFAULT_CATEGORIES = ["기획", "디자인", "개발", "데이터", "QA", "비즈니스", "협업", "HR", "기타"]

PURPLE_PALETTE = {
    400: "#7E72FA", # 키워드 텍스트 색상
    800: "#4A2EA5", # 카테고리 라벨 배경색
    900: "#3F2C83"
}

# 2. 데이터 처리 함수
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
    for model_name in MODEL_PRIORITY_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            prompt = f"텍스트를 분석해 JSON 형식으로 핵심주제(keywords, 2-3개, #포함)와 직무분야(categories, 1-2개)를 추출해줘. 텍스트: {text}"
            response = model.generate_content(prompt)
            result = json.loads(response.text.replace("```json", "").replace("```", "").strip())
            return result.get("keywords", ["#일반"]), result.get("categories", ["기타"]), model_name
        except: continue
    return ["#AI오류"], ["기타"], "None"

# 3. 주차 관련 함수
def get_week_label(date_obj):
    if pd.isna(date_obj): return None, None
    dt = pd.to_datetime(date_obj).normalize()
    week_num = (dt.day - 1) // 7 + 1
    label = f"{dt.year % 100}년 {dt.month}월 {week_num}주차"
    start_of_week = dt - datetime.timedelta(days=dt.weekday())
    return label, start_of_week.normalize()

def get_week_range(week_label):
    today = datetime.date.today()
    if week_label == "이번 주 기록":
        start = today - datetime.timedelta(days=today.weekday())
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    try:
        parts = week_label.split()
        year, month, week_num = int(parts[0][:-1]) + 2000, int(parts[1][:-1]), int(parts[2][:-2])
        current_day = datetime.date(year, month, (week_num-1)*7 + 1)
        start = current_day - datetime.timedelta(days=current_day.weekday())
        return pd.to_datetime(start).normalize(), pd.to_datetime(start + datetime.timedelta(days=6)).normalize()
    except: return get_week_range("이번 주 기록")

# 4. Streamlit UI
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

if 'edit_mode' not in st.session_state: st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state: st.session_state['edit_data'] = {}

st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; }}
    .appview-container .main .block-container {{ max-width: 1080px; margin: 0 auto; }}
    div[data-testid="stMetric"] {{ background-color: {CARD_BG_COLOR}; border: 1px solid #30333F; padding: 15px; border-radius: 10px; }}
    hr {{ margin: 5px 0 10px 0; border-top: 1px solid #30333F; }}
    div[data-testid="stHorizontalBlock"] {{ align-items: center; }}
    div[data-testid="stButton"] > button {{ font-size: 0.75rem; padding: 4px 8px; }}
    .writer-name {{ font-weight: bold; font-size: 1.05rem; color: white; }}
    .date-info {{ color: #9CA3AF; font-size: 0.9em; margin-left: 10px; }}
    .cat-badge {{ background-color: {PURPLE_PALETTE[800]}; color: white; padding: 3px 8px; border-radius: 12px; font-size: 0.8rem; margin-right: 8px; }}
    .kw-text {{ color: {PURPLE_PALETTE[400]}; font-size: 0.8rem; font-weight: 500; }}
    </style>
""", unsafe_allow_html=True)

st.title("Team Lesson Learned 🚀")
tab1, tab2 = st.tabs(["📝 레슨런 기록하기", "📊 통합 대시보드"])

with tab1:
    df = load_data()
    if st.session_state['edit_mode']:
        if st.button("취소하고 새 글 쓰기", type="secondary"):
            st.session_state['edit_mode'] = False
            st.rerun()
    
    with st.form("record_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        writer = c1.text_input("작성자", value=st.session_state.get('edit_data', {}).get('writer', ""))
        date_val = c2.date_input("날짜", value=st.session_state.get('edit_data', {}).get('date', datetime.date.today()))
        text = st.text_area("내용", value=st.session_state.get('edit_data', {}).get('text', ""), height=300)
        submit_label = "수정 완료" if st.session_state['edit_mode'] else "기록 저장하기"
        if st.form_submit_button(submit_label, type="primary", use_container_width=True):
            if writer and text:
                with st.spinner("AI 분석 중..."):
                    kws, cats, model = analyze_text(text)
                    if st.session_state['edit_mode']:
                        update_entry(st.session_state['edit_data']['id'], writer, text, kws, cats, date_val)
                    else:
                        save_entry(str(uuid.uuid4()), writer, text, kws, cats, date_val)
                    st.session_state['edit_mode'] = False
                    st.rerun()

    st.subheader("🔍 레슨런 목록")
    if not df.empty:
        col_f1, col_f2 = st.columns(2)
        writer_filter = col_f1.selectbox("작성자", ["전체"] + sorted(df['writer'].unique().tolist()))
        week_options = sorted(df['date'].apply(lambda x: get_week_label(x)[0]).unique().tolist(), reverse=True)
        week_filter = col_f2.selectbox("주차 선택", ["이번 주 기록"] + week_options)
        
        start_f, end_f = get_week_range(week_filter)
        f_df = df[(df['date'] >= start_f) & (df['date'] <= end_f)]
        if writer_filter != "전체": f_df = f_df[f_df['writer'] == writer_filter]
        
        for _, row in f_df.sort_values("date", ascending=False).iterrows():
            with st.container(border=True):
                c_info, c_edit, c_del = st.columns([6, 1, 1])
                c_info.markdown(f"<div class='info-block'><span class='writer-name'>{row['writer']}</span><span class='date-info'>({row['date'].strftime('%Y-%m-%d')} 작성)</span></div>", unsafe_allow_html=True)
                if c_edit.button("수정", key=f"e_{row['id']}"):
                    st.session_state.update({'edit_mode': True, 'edit_data': row.to_dict()})
                    st.rerun()
                if c_del.button("삭제", key=f"d_{row['id']}"):
                    delete_entry(row['id']); st.rerun()
                st.markdown("<hr>", unsafe_allow_html=True)
                st.markdown(row['text'])
                cats = parse_categories(row['category'])
                kws = " ".join([f"#{k.strip('#')}" for k in parse_categories(row['keywords'])])
                badges = "".join([f"<span class='cat-badge'>{c}</span>" for c in cats])
                st.markdown(f"<div class='tag-container'>{badges}<span class='kw-text'>{kws}</span></div>", unsafe_allow_html=True)

with tab2:
    df = load_data()
    if not df.empty:
        st.subheader("Key Metrics")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("총 기록 수", f"{len(df)}건")
        
        st.subheader("🗺️ Lesson Map (카테고리 비중)")
        all_cats = []
        for c in df['category']: all_cats.extend(parse_categories(c))
        cat_counts = pd.Series(all_cats).value_counts().reset_index()
        cat_counts.columns = ['Category', 'Value']
        
        fig = px.treemap(cat_counts, path=['Category'], values='Value', color='Value',
                         color_continuous_scale=[(0, PURPLE_PALETTE[400]), (1, PURPLE_PALETTE[900])])
        fig.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=350, template="plotly_dark",
                          paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR,
                          font=dict(color="white", family="Pretendard"), coloraxis_showscale=False)
        fig.update_traces(textfont=dict(size=18, color="white"), texttemplate="<b>%{label}</b><br>%{value}건",
                          marker=dict(line=dict(width=1, color="#30333F")))
        st.plotly_chart(fig, use_container_width=True, theme=None)
        
        # 상세 분석 및 전체 목록 (생략 가능하나 구조 유지)
        st.divider()
        st.info("카테고리별 상세 데이터는 목록 필터를 이용해주세요.")

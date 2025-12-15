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
GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"] if "GOOGLE_API_KEY" in st.secrets else "YOUR_API_KEY"
CARD_BG_COLOR = "#0E1117"

# [색상 팔레트]
PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83", 950: "#261A4C"
}

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data(force_reload=False):
    conn = get_connection()
    try:
        # 사용량 초과 방지: 10분 캐싱
        ttl_val = 0 if force_reload else "10m"
        df = conn.read(ttl=ttl_val)
        
        if df.empty:
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])
        
        df.columns = [c.strip().lower() for c in df.columns]
        
        if 'id' not in df.columns:
            df['id'] = [str(uuid.uuid4()) for _ in range(len(df))]

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        df = df.fillna("")
        return df
    except Exception as e:
        if "Quota" in str(e) or "429" in str(e):
            st.toast("⏳ 구글 시트가 바쁩니다. 잠시만 기다려주세요.", icon="⚠️")
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])
        else:
            st.error(f"데이터 로드 실패: {e}")
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    if 'date' in save_df.columns:
        save_df['date'] = save_df['date'].dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)
    st.cache_data.clear()

def save_entry(writer, text, keywords, category, date_val):
    df = load_data(force_reload=True)
    if isinstance(category, list): cat_str = json.dumps(category, ensure_ascii=False)
    else: cat_str = json.dumps([str(category)], ensure_ascii=False)
    
    new_data = pd.DataFrame({
        "id": [str(uuid.uuid4())],
        "date": [pd.to_datetime(date_val)],
        "writer": [writer],
        "text": [text],
        "keywords": [json.dumps(keywords, ensure_ascii=False)],
        "category": [cat_str]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    save_data_to_sheet(df)

def update_entry(entry_id, writer, text, keywords, category, date_val):
    df = load_data(force_reload=True)
    idx = df[df['id'] == entry_id].index
    
    if isinstance(category, list): cat_str = json.dumps(category, ensure_ascii=False)
    else: cat_str = json.dumps([str(category)], ensure_ascii=False)

    if not idx.empty:
        df.at[idx[0], 'writer'] = writer
        df.at[idx[0], 'text'] = text
        df.at[idx[0], 'keywords'] = json.dumps(keywords, ensure_ascii=False)
        df.at[idx[0], 'category'] = cat_str
        df.at[idx[0], 'date'] = pd.to_datetime(date_val)
        save_data_to_sheet(df)

def delete_entry(entry_id):
    df = load_data(force_reload=True)
    df = df[df['id'] != entry_id]
    save_data_to_sheet(df)

def parse_json_list(data_str):
    try:
        if not data_str or pd.isna(data_str): return []
        if isinstance(data_str, list): return data_str
        s = str(data_str).strip()
        if s.startswith("[") and s.endswith("]"): 
            s = s.replace("'", '"')
            try: return json.loads(s)
            except: pass
        clean_s = s.replace('[','').replace(']','').replace('"','').replace("'", "")
        if "," in clean_s: return [x.strip() for x in clean_s.split(",") if x.strip()]
        return [clean_s] if clean_s else []
    except: return []

# [진단 기능] 설치된 버전 확인 및 모델 테스트
def check_ai_status():
    status_log = []
    try:
        # 1. 라이브러리 버전 확인
        lib_version = genai.__version__
        status_log.append(f"📦 라이브러리 버전: {lib_version}")
        
        # 2. 키 확인
        if not GOOGLE_API_KEY or GOOGLE_API_KEY == "YOUR_API_KEY":
            status_log.append("❌ API 키 없음")
            return False, status_log, "API Key Missing"
        
        genai.configure(api_key=GOOGLE_API_KEY)
        
        # 3. 모델 목록 조회 시도
        models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                models.append(m.name)
        
        status_log.append(f"📋 사용 가능 모델: {', '.join(models)}")
        
        if not models:
            return False, status_log, "No Models Found"
            
        return True, status_log, None
        
    except Exception as e:
        return False, status_log, str(e)

# [수정] AI 분석 함수 (에러 발생 시 중단하지 않고 메시지 반환)
def analyze_text(text):
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        
        # gemini-pro 사용 (가장 호환성 좋음)
        model = genai.GenerativeModel("gemini-pro") 

        prompt = f"""
        너는 팀의 레슨런을 분류하는 관리자야. 텍스트를 분석해서 JSON으로 답해줘.
        1. keywords: 핵심 단어 2~3개 (Array)
        2. category: 글의 성격을 나타내는 명사형 단어 1개 (String). 예: 기획, 디자인
        [형식] {{"keywords": ["키워드1"], "category": "카테고리명"}}
        텍스트: {text}
        """
        
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text_resp)
        cat = result.get("category", "기타")
        if isinstance(cat, list): cat = cat[0] if cat else "기타"
        
        return result.get("keywords", ["분석불가"]), cat, None # None은 에러 없음 의미

    except Exception as e:
        # 에러 객체를 그대로 반환하여 UI에서 출력
        return ["AI연동실패"], "기타", str(e)

def get_month_week_str(date_obj):
    try:
        if pd.isna(date_obj): return ""
        week_num = (date_obj.day - 1) // 7 + 1
        return f"{date_obj.strftime('%y')}년 {date_obj.month}월 {week_num}주차"
    except: return ""

# -----------------------------------------------------------------------------
# 2. UI 디자인
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

if 'edit_mode' not in st.session_state: st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state: st.session_state['edit_data'] = {}

st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; }}
    .stApp {{ background-color: {CARD_BG_COLOR}; }}
    
    .ai-status-ok {{ color: {PURPLE_PALETTE[500]}; font-weight: bold; font-size: 0.9rem; border: 1px solid {PURPLE_PALETTE[500]}; padding: 5px 10px; border-radius: 20px; }}
    .ai-status-fail {{ color: #F44336; font-weight: bold; font-size: 0.9rem; border: 1px solid #F44336; padding: 5px 10px; border-radius: 20px; }}

    div[data-testid="stMetric"] {{ background-color: {CARD_BG_COLOR}; border: 1px solid #30333F; padding: 15px; border-radius: 10px; color: white; margin-bottom: 10px; }}
    div[data-testid="stMetricLabel"] {{ color: #9CA3AF !important; }}
    div[data-testid="stMetricValue"] {{ color: white !important; font-weight: 700 !important; }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{ background-color: {CARD_BG_COLOR} !important; border: 1px solid #30333F !important; border-radius: 10px !important; padding: 20px !important; overflow: hidden !important; }}
    
    button[data-testid="stTab"] {{ font-size: 1.2rem !important; font-weight: 700 !important; }}
    button[kind="secondary"] {{ border: 1px solid #30333F; color: #9CA3AF; padding: 4px 10px; font-size: 0.85rem; line-height: 1.2; margin-top: 0px !important; }}
    button[kind="secondary"]:hover {{ border-color: {PURPLE_PALETTE[500]}; color: {PURPLE_PALETTE[500]}; }}
    </style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# [신규] 사이드바에 AI 진단 도구 추가
# -----------------------------------------------------------------------------
with st.sidebar:
    st.header("🔧 시스템 상태")
    if st.button("AI 연결 진단하기", type="primary"):
        with st.spinner("진단 중..."):
            is_ok, logs, err = check_ai_status()
            
            st.markdown("### 📋 진단 로그")
            for log in logs:
                st.text(log)
            
            if is_ok:
                st.success("✅ AI 시스템 정상!")
            else:
                st.error("🚨 AI 연결 실패")
                st.code(err)
                if "404" in str(err) and "models" in str(err):
                    st.warning("💡 팁: requirements.txt의 버전이 낮아서 그렇습니다. 앱을 재배포(Delete -> Deploy)하면 해결됩니다.")

col_head1, col_head2 = st.columns([5, 1])
with col_head1:
    st.title("Team Lesson Learned 🚀")
    st.caption("팀의 배움을 기록하고 공유하는 아카이브")
with col_head2:
    if GOOGLE_API_KEY and GOOGLE_API_KEY != "YOUR_API_KEY":
        st.markdown(f'<div style="text-align: right;"><span class="ai-status-ok">🟢 AI 연결됨 (Key Found)</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align: right;"><span class="ai-status-fail">🔴 AI 미설정</span></div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

with tab1:
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        if st.button("취소"):
            st.session_state['edit_mode'] = False; st.session_state['edit_data'] = {}; st.rerun()
        
        form_writer = st.session_state['edit_data'].get('writer', '')
        form_text = st.session_state['edit_data'].get('text', '')
        d_val = st.session_state['edit_data'].get('date')
        form_date = d_val.date() if isinstance(d_val, pd.Timestamp) else datetime.datetime.now().date()
    else:
        st.subheader("이번주의 레슨런을 기록해주세요")
        form_writer = ""
        form_text = ""
        form_date = datetime.datetime.now().date()

    with st.form("record_form", clear_on_submit=True):
        c_input1, c_input2 = st.columns([1, 1])
        with c_input1: writer = st.text_input("작성자", value=form_writer, placeholder="이름 입력")
        with c_input2: selected_date = st.date_input("날짜", value=form_date)
        text = st.text_area("내용 (Markdown 지원)", value=form_text, height=150)
        
        submitted = st.form_submit_button("수정 완료" if st.session_state['edit_mode'] else "기록 저장하기", use_container_width=True)
        
        if submitted:
            if not writer or not text: st.error("내용을 입력해주세요.")
            else:
                with st.spinner("✨ AI 분석 중..."):
                    # 분석 결과와 에러 메시지를 함께 받음
                    keywords, category, error_msg = analyze_text(text)
                    
                    # 에러가 있었다면 저장을 멈추고 에러 내용을 고정해서 보여줌 (사라지지 않음)
                    if error_msg:
                        st.error("🚨 AI 분석 중 오류가 발생했습니다!")
                        st.code(error_msg)
                        st.info("이 메시지를 캡쳐해서 알려주세요. (데이터는 저장되지 않았습니다)")
                    else:
                        # 에러가 없을 때만 저장 진행
                        if st.session_state['edit_mode']:
                            update_entry(st.session_state['edit_data']['id'], writer, text, keywords, category, selected_date)
                            st.success("✅ 수정 완료!")
                            st.session_state['edit_mode'] = False
                            st.session_state['edit_data'] = {}
                            st.rerun()
                        else:
                            save_entry(writer, text, keywords, category, selected_date)
                            st.success(f"✅ 저장 완료! ({category})")

    st.markdown("---")
    
    col_t, col_r = st.columns([8, 2])
    with col_t: st.subheader("📜 이전 기록 참고하기")
    with col_r: 
        if st.button("🔄 새로고침", use_container_width=True): st.cache_data.clear(); st.rerun()
    
    df = load_data()
    if not df.empty and "writer" in df.columns:
        df['week_str'] = df['date'].apply(get_month_week_str)
        fc1, fc2 = st.columns(2)
        writers = ["전체 보기"] + sorted(list(set(df['writer'].dropna())))
        weeks = ["전체 기간"] + sorted(list(set(df['week_str'].dropna())), reverse=True)
        with fc1: selected_writer = st.selectbox("작성자", writers, label_visibility="collapsed")
        with fc2: selected_week = st.selectbox("주차 선택", weeks, label_visibility="collapsed")
        
        view_df = df.copy()
        if selected_writer != "전체 보기": view_df = view_df[view_df['writer'] == selected_writer]
        if selected_week != "전체 기간": view_df = view_df[view_df['week_str'] == selected_week]
        view_df = view_df.sort_values(by="date", ascending=False)
        
        for idx, row in view_df.iterrows():
            with st.container(border=True):
                hc1, hc2, hc3 = st.columns([8.8, 0.6, 0.6])
                d_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                with hc1: st.markdown(f"**{row['writer']}** <span style='color:#888'>| {d_str}</span>", unsafe_allow_html=True)
                with hc2: 
                    if st.button("수정", key=f"e_{row['id']}"):
                        st.session_state['edit_mode'] = True; st.session_state['edit_data'] = row.to_dict(); st.rerun()
                with hc3:
                    if st.button("삭제", key=f"d_{row['id']}"): confirm_delete_dialog(row['id'])
                
                st.markdown(f'<hr style="border:0; border-top:1px solid #30333F; margin:5px 0 15px 0;">', unsafe_allow_html=True)
                st.markdown(row['text'])
                
                cats = parse_json_list(row['category'])
                kws = parse_json_list(row['keywords'])
                badges = "".join([f"<span style='background:{PURPLE_PALETTE[800]}; color:white; padding:4px 10px; border-radius:12px; font-size:0.8rem; font-weight:bold; margin-right:5px;'>{c}</span>" for c in cats])
                kw_str = "  ".join([f"#{k}" for k in kws])
                st.markdown(f"<div style='margin-top:20px;'>{badges} <span style='color:{PURPLE_PALETTE[400]}; font-size:0.9rem; margin-left:5px;'>{kw_str}</span></div>", unsafe_allow_html=True)
                st.markdown("<div style='height:15px;'></div>", unsafe_allow_html=True)
    else: st.info("아직 기록된 내용이 없습니다.")

def get_relative_color(val, max_val):
    if max_val == 0: return PURPLE_PALETTE[400]
    ratio = val / max_val
    if ratio >= 0.75: return PURPLE_PALETTE[900]
    elif ratio >= 0.50: return PURPLE_PALETTE[700]
    elif ratio >= 0.25: return PURPLE_PALETTE[500]
    else: return PURPLE_PALETTE[400]

with tab2:
    df = load_data()
    if not df.empty and "category" in df.columns:
        total = len(df)
        all_cats = []; all_kws = []
        for idx, row in df.iterrows():
            cats = parse_json_list(row['category']); kws = parse_json_list(row['keywords'])
            all_cats.extend(cats); all_kws.extend(kws)
            
        top_cat = pd.Series(all_cats).mode()[0] if all_cats else "-"
        top_writer = df['writer'].mode()[0] if not df['writer'].empty else "-"
        
        row1_col1, row1_col2 = st.columns([1, 3])
        with row1_col1:
            st.subheader("Key Metrics")
            st.metric("총 기록 수", f"{total}건")
            st.metric("최다 카테고리", top_cat)
            st.metric("누적 키워드", f"{len(set(all_kws))}개")
            st.metric("최다 작성자", top_writer)

        with row1_col2:
            st.subheader("🗺️ Keyword Map (키워드 맵)")
            with st.container(border=True):
                tree_data = []
                for idx, row in df.iterrows():
                    cats = parse_json_list(row['category']); kws = parse_json_list(row['keywords'])
                    temp_cats = cats if cats else ["기타"]; temp_kws = kws if kws else ["General"]
                    for c in temp_cats:
                        for k in temp_kws:
                            tree_data.append({'Category': c, 'Keyword': k, 'Value': 1})

                if tree_data:
                    tree_df = pd.DataFrame(tree_data).groupby(['Category', 'Keyword']).sum().reset_index()
                    max_frequency = tree_df['Value'].max() if not tree_df.empty else 1
                    
                    ids, labels, parents, values, colors, display_texts = [], [], [], [], [], []
                    
                    categories = tree_df['Category'].unique()
                    for cat in categories:
                        cat_total = tree_df[tree_df['Category'] == cat]['Value'].sum()
                        ids.append(f"CAT-{cat}")
                        labels.append(cat)
                        parents.append("")
                        values.append(cat_total)
                        colors.append(PURPLE_PALETTE[950])
                        display_texts.append(cat)

                    for idx, row in tree_df.iterrows():
                        ids.append(f"KW-{row['Category']}-{row['Keyword']}")
                        labels.append(row['Keyword'])
                        parents.append(f"CAT-{row['Category']}")
                        values.append(row['Value'])
                        colors.append(get_relative_color(row['Value'], max_frequency))
                        display_texts.append(row['Keyword'])

                    fig_tree = go.Figure(go.Treemap(
                        ids=ids, labels=labels, parents=parents, values=values,
                        marker=dict(colors=colors, line=dict(width=8, color=PURPLE_PALETTE[950])),
                        text=display_texts, textinfo="text",
                        textfont=dict(family="Pretendard", color="white", size=20),
                        branchvalues="total", pathbar=dict(visible=False), textposition="middle center"
                    ))
                    fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=520, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                    st.plotly_chart(fig_tree, use_container_width=True)
                else: st.info("데이터가 부족합니다.")
        
        st.markdown("---")
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.subheader("📊 카테고리 비중")
            with st.container(border=True):
                if all_cats:
                    cat_counts = pd.Series(all_cats).value_counts().reset_index()
                    cat_counts.columns = ['category', 'count']
                    fig_pie = px.pie(cat_counts, values='count', names='category', hole=0.6, color_discrete_sequence=[PURPLE_PALETTE[i] for i in [500, 600, 700, 800, 900, 400]])
                    fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=350, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                    st.plotly_chart(fig_pie, use_container_width=True)
        with col_c2:
            st.subheader("🏆 Top 키워드")
            with st.container(border=True):
                if all_kws:
                    kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                    kw_counts.columns = ['keyword', 'count']
                    fig_bar = go.Figure(go.Bar(x=kw_counts['count'], y=kw_counts['keyword'], orientation='h', text=kw_counts['count'], textposition='outside', marker=dict(color=PURPLE_PALETTE[600], opacity=1.0, line=dict(width=0))))
                    fig_bar.update_layout(xaxis=dict(showgrid=False, visible=False), yaxis=dict(showgrid=False, autorange="reversed"), margin=dict(t=20, b=20, l=10, r=40), height=350, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                    st.plotly_chart(fig_bar, use_container_width=True)
    else: st.info("데이터가 없습니다.")

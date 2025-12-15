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

PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83", 950: "#261A4C"
}

# [기존 테마] 여기에 없는 카테고리가 나오면 '기타'와 같은 색상을 씁니다.
CATEGORY_THEMES = {
    "기타": (400, 600), "기획": (500, 700), "개발": (600, 800),
    "디자인": (700, 900), "협업": (500, 700), "프로세스": (600, 800)
}

def get_text_color(palette_index):
    return "#FFFFFF"

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data():
    conn = get_connection()
    try:
        df = conn.read(ttl=0)
        if df.empty:
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])
        
        df.columns = [c.strip().lower() for c in df.columns]
        
        if 'id' not in df.columns:
            st.error("❌ 구글 시트에 'id' 컬럼이 없습니다. 1행 제목을 확인해주세요.")
            return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
        
        df = df.fillna("")
        return df
    except Exception as e:
        st.error(f"데이터를 불러오는 중 문제가 발생했습니다: {e}")
        return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    if 'date' in save_df.columns:
        save_df['date'] = save_df['date'].dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)

def save_entry(writer, text, keywords, category, date_val):
    df = load_data()
    new_data = pd.DataFrame({
        "id": [str(uuid.uuid4())],
        "date": [pd.to_datetime(date_val)],
        "writer": [writer],
        "text": [text],
        "keywords": [json.dumps(keywords, ensure_ascii=False)],
        "category": [category]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    save_data_to_sheet(df)

def update_entry(entry_id, writer, text, keywords, category, date_val):
    df = load_data()
    idx = df[df['id'] == entry_id].index
    if not idx.empty:
        df.at[idx[0], 'writer'] = writer
        df.at[idx[0], 'text'] = text
        df.at[idx[0], 'keywords'] = json.dumps(keywords, ensure_ascii=False)
        df.at[idx[0], 'category'] = category
        df.at[idx[0], 'date'] = pd.to_datetime(date_val)
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

def analyze_text(text):
    try:
        model_name = get_available_model()
        if not model_name: return ["AI연동실패"], "기타"
        
        model = genai.GenerativeModel(model_name)
        
        # [수정] 카테고리 제한 해제 프롬프트
        prompt = f"""
        너는 팀의 레슨런(Lesson Learned)을 분류하는 데이터 관리자야.
        입력된 텍스트를 분석해서 다음 규칙에 맞춰 JSON으로 응답해.

        [키워드 작성 규칙]
        1. keywords: 총 2~3개의 키워드를 배열로 작성.
           - 데이터 그룹핑을 위해 '기획', '개발', '디자인', '협업', '프로세스' 같은 표준 단어가 있다면 첫 번째 키워드로 넣어줘.
           - 없다면 본문을 잘 설명하는 핵심 단어를 넣어줘.
           
        [카테고리 작성 규칙]
        2. category: **텍스트의 성격을 가장 잘 나타내는 명사형 단어 1개**를 작성해.
           - 예시: 기획, 개발, 디자인, 협업, 프로세스, 마케팅, 비즈니스, HR, 복지 등 제한 없음.
           - 너무 긴 문장은 안 되고, 핵심 주제 단어여야 해.

        [응답 형식 (JSON)]
        {{
            "keywords": ["키워드1", "키워드2"],
            "category": "카테고리명"
        }}
        
        텍스트: {text}
        """
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text_resp)
        
        cat = result.get("category", "기타")
        
        # [삭제] 여기에 있던 'if cat not in CATEGORY_THEMES: cat = "기타"' 코드를 지웠습니다.
        # 이제 AI가 뱉은 카테고리를 그대로 사용합니다.
        
        return result.get("keywords", ["분석불가"]), cat
    except Exception as e:
        return ["AI연동실패"], "기타"

def get_month_week_str(date_obj):
    try:
        if pd.isna(date_obj): return ""
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
        saved_date = st.session_state['edit_data'].get('date')
        if isinstance(saved_date, pd.Timestamp):
            form_date = saved_date.date()
        else:
            form_date = datetime.datetime.now().date()
            
    else:
        st.subheader("이번주의 레슨런을 기록해주세요")
        form_writer = ""
        form_text = ""
        form_date = datetime.datetime.now().date()

    with st.form("record_form", clear_on_submit=True):
        c_input1, c_input2 = st.columns([1, 1])
        with c_input1:
            writer = st.text_input("작성자", value=form_writer, placeholder="이름 입력")
        with c_input2:
            selected_date = st.date_input("날짜", value=form_date)
            
        text = st.text_area("내용 (Markdown 지원)", value=form_text, height=150)
        submitted = st.form_submit_button("수정 완료" if st.session_state['edit_mode'] else "기록 저장하기", use_container_width=True)
        
        if submitted:
            if not writer or not text:
                st.error("내용을 입력해주세요.")
            else:
                with st.spinner("✨ AI 분석 중..."):
                    keywords, category = analyze_text(text)
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
                st.markdown(row['text'])
                
                try: kw_list = json.loads(row['keywords'])
                except: kw_list = []
                kw_str = "  ".join([f"#{k}" for k in kw_list])
                
                st.markdown(f"""<div style="margin-top: 20px; display: flex; align-items: center; gap: 10px;"><span style="background-color: {PURPLE_PALETTE[800]}; color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold;">{row['category']}</span><span style="color: {PURPLE_PALETTE[400]}; font-size: 0.9rem;">{kw_str}</span></div>""", unsafe_allow_html=True)
                st.markdown("<div style='height: 20px;'></div>", unsafe_allow_html=True)
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
    else:
        st.info("아직 기록된 내용이 없습니다.")

with tab2:
    df = load_data()
    if not df.empty:
        total = len(df)
        top_cat = df['category'].mode()[0] if not df['category'].empty else "-"
        top_writer = df['writer'].mode()[0] if not df['writer'].empty else "-"
        try:
            all_kws = []
            for k in df['keywords']: all_kws.extend(json.loads(k))
        except: all_kws = []
        
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
                if all_kws:
                    tree_data = []
                    for idx, row in df.iterrows():
                        try: kws = json.loads(row['keywords'])
                        except: kws = []
                        for k in kws: tree_data.append({'Category': row['category'], 'Keyword': k, 'Value': 1})
                    
                    if tree_data:
                        tree_df = pd.DataFrame(tree_data).groupby(['Category', 'Keyword']).sum().reset_index()
                        labels, parents, values, colors, text_colors, display_texts = [], [], [], [], [], []
                        
                        categories = tree_df['Category'].unique()
                        for cat in categories:
                            cat_total = tree_df[tree_df['Category'] == cat]['Value'].sum()
                            labels.append(cat); parents.append(""); values.append(cat_total)
                            
                            # [핵심] 새로운 카테고리가 나오면 '기타' 색상을 기본값으로 사용 (에러 방지)
                            color_indices = CATEGORY_THEMES.get(cat, CATEGORY_THEMES["기타"])
                            
                            colors.append(PURPLE_PALETTE[color_indices[0]])
                            text_colors.append(get_text_color(color_indices[0]))
                            display_texts.append(f"{cat}")

                        for idx, row in tree_df.iterrows():
                            labels.append(row['Keyword']); parents.append(row['Category']); values.append(row['Value'])
                            
                            # [핵심] 키워드도 마찬가지로 안전하게 색상 처리
                            color_indices = CATEGORY_THEMES.get(row['Category'], CATEGORY_THEMES["기타"])
                            
                            colors.append(PURPLE_PALETTE[color_indices[1]])
                            text_colors.append(get_text_color(color_indices[1]))
                            display_texts.append(f"{row['Keyword']}")

                        fig_tree = go.Figure(go.Treemap(
                            labels=labels, parents=parents, values=values,
                            marker=dict(colors=colors, line=dict(width=0, color=CARD_BG_COLOR)),
                            text=display_texts, 
                            textinfo="text",
                            textfont=dict(family="Pretendard", color=text_colors, size=20),
                            branchvalues="total", pathbar=dict(visible=False), textposition="middle center" 
                        ))
                        fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=520, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                        st.plotly_chart(fig_tree, use_container_width=True)
                else: st.info("데이터가 부족합니다.")
        st.markdown("---")
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.subheader("📊 카테고리 비중")
            with st.container(border=True):
                cat_counts = df['category'].value_counts().reset_index()
                cat_counts.columns = ['category', 'count']
                fig_pie = px.pie(cat_counts, values='count', names='category', hole=0.6, color_discrete_sequence=[PURPLE_PALETTE[i] for i in [500, 600, 700, 800, 900, 400]])
                fig_pie.update_layout(margin=dict(t=20, b=20, l=20, r=20), height=350, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                st.plotly_chart(fig_pie, use_container_width=True)
        with col_chart2:
            st.subheader("🏆 Top 키워드")
            with st.container(border=True):
                if all_kws:
                    kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                    kw_counts.columns = ['keyword', 'count']
                    fig_bar = go.Figure(go.Bar(x=kw_counts['count'], y=kw_counts['keyword'], orientation='h', text=kw_counts['count'], textposition='outside', marker=dict(color=PURPLE_PALETTE[600], opacity=1.0, line=dict(width=0))))
                    fig_bar.update_layout(xaxis=dict(showgrid=False, visible=False), yaxis=dict(showgrid=False, autorange="reversed"), margin=dict(t=20, b=20, l=10, r=40), height=350, paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR)
                    st.plotly_chart(fig_bar, use_container_width=True)
                else: st.info("데이터가 없습니다.")
    else: st.info("첫 기록을 남겨보세요!")

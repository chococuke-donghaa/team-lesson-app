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
CARD_BG_COLOR = "#0E1117"

# 모델 우선순위
MODEL_PRIORITY_LIST = [
    "gemini-2.5-flash",       
    "gemini-2.5-flash-lite",  
    "gemini-1.5-flash"        
]

# [수정] 참고용 카테고리 (AI에게 가이드만 주고 강제하지 않음)
DEFAULT_CATEGORIES = [
    "기획", "디자인", "개발", "데이터", "QA", "비즈니스", "협업", "HR", "기타"
]

PURPLE_PALETTE = {
    50: "#EEEFFF", 100: "#DFE1FF", 200: "#C6C7FF", 300: "#A3A3FE",
    400: "#7E72FA", 500: "#7860F4", 600: "#6A43E8", 700: "#5B35CD",
    800: "#4A2EA5", 900: "#3F2C83", 950: "#261A4C"
}

def get_relative_color(val, max_val):
    if max_val == 0: return PURPLE_PALETTE[400]
    ratio = val / max_val
    if ratio >= 0.8: return PURPLE_PALETTE[900]
    elif ratio >= 0.6: return PURPLE_PALETTE[800]
    elif ratio >= 0.4: return PURPLE_PALETTE[600]
    elif ratio >= 0.2: return PURPLE_PALETTE[500]
    else: return PURPLE_PALETTE[400]

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
        "date": [pd.to_datetime(date_val)],
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
        df.at[idx[0], 'date'] = pd.to_datetime(date_val)
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
# 2. AI 분석 (프롬프트 강화)
# -----------------------------------------------------------------------------
def analyze_text(text):
    genai.configure(api_key=GOOGLE_API_KEY)
    
    for model_name in MODEL_PRIORITY_LIST:
        try:
            model = genai.GenerativeModel(model_name)
            
            # [수정] 프롬프트: 자유로운 카테고리 생성 허용 및 구체적 키워드 요구
            prompt = f"""
            너는 팀의 레슨런(Lesson Learned)을 분석하는 데이터 전문가야.
            입력된 텍스트를 분석해서 JSON 형식으로 응답해.

            [규칙 1: 키워드 (keywords)]
            - 본문의 핵심 주제를 '명사형'으로 1~3개 추출해. (예: "API최적화", "디자인시스템", "코드리뷰")
            - 추상적인 단어보다는 구체적인 단어를 사용해.

            [규칙 2: 카테고리 (categories)]
            - 본문이 속하는 큰 직무/분야를 1~2개 선택해.
            - 참고 목록: {', '.join(DEFAULT_CATEGORIES)}
            - **주의:** 참고 목록에 없더라도, 내용에 더 적합한 카테고리가 있다면 자유롭게 새로 만들어도 돼. (예: "DevOps", "UX라이팅" 등)
            
            [응답 예시]
            {{
                "keywords": ["디자인시스템", "일관성"],
                "categories": ["디자인", "프로세스"]
            }}
            
            텍스트: {text}
            """
            
            response = model.generate_content(prompt)
            text_resp = response.text.replace("```json", "").replace("```", "").strip()
            result = json.loads(text_resp)
            
            kws = result.get("keywords", [])
            cats = result.get("categories", ["기타"])
            
            # 빈 키워드 필터링
            kws = [k for k in kws if k and str(k).strip() and k != "#분석불가"]
            if not kws: kws = ["일반"] # 키워드가 아예 없으면 '일반' 태그 부여
            
            if isinstance(cats, str): cats = [cats]
            
            print(f"✅ Success with {model_name}")
            return kws, cats, model_name

        except Exception as e:
            print(f"⚠️ {model_name} failed: {e}")
            time.sleep(1) 
            continue
    
    return ["일반"], ["기타"], "None"

def get_month_week_str(date_obj):
    try:
        if pd.isna(date_obj): return ""
        if isinstance(date_obj, str): date_obj = pd.to_datetime(date_obj)
        week_num = (date_obj.day - 1) // 7 + 1
        return f"{date_obj.strftime('%y')}년 {date_obj.month}월 {week_num}주차"
    except:
        return ""

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
    </style>
""", unsafe_allow_html=True)

col_head1, col_head2 = st.columns([5, 1])
with col_head1:
    st.title("Team Lesson Learned 🚀")
    st.caption("AI 자동 분류 (키워드/카테고리) 및 모델 자동 전환 지원")
with col_head2:
    if GOOGLE_API_KEY != "YOUR_API_KEY":
        st.markdown(f'<div style="text-align: right;"><span style="color:{PURPLE_PALETTE[500]}; font-weight:bold; border:1px solid {PURPLE_PALETTE[500]}; padding:5px 10px; border-radius:20px;">🟢 AI Ready</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align: right;"><span style="color:#F44336; font-weight:bold; border:1px solid #F44336; padding:5px 10px; border-radius:20px;">🔴 API Key Missing</span></div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 배움 기록하기", "📊 통합 대시보드"])

# --- TAB 1: 입력 ---
with tab1:
    if st.session_state['edit_mode']:
        st.subheader("✏️ 기록 수정하기")
        if st.button("취소하고 새 글 쓰기"):
            st.session_state['edit_mode'] = False
            st.session_state['edit_data'] = {}
            st.rerun()
            
        form_writer = st.session_state['edit_data'].get('writer', '')
        form_text = st.session_state['edit_data'].get('text', '')
        saved_date = st.session_state['edit_data'].get('date')
        if isinstance(saved_date, (pd.Timestamp, datetime.datetime)):
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
        
        text = st.text_area("내용 (Markdown 지원)", value=form_text, height=150, placeholder="배운 점, 문제 해결 과정 등을 자유롭게 적어주세요. AI가 자동으로 태그를 달아줍니다.")
        
        submitted = st.form_submit_button("수정 완료" if st.session_state['edit_mode'] else "기록 저장하기", use_container_width=True)
        
        if submitted:
            if not writer or not text:
                st.error("작성자와 내용을 모두 입력해주세요.")
            else:
                with st.spinner("✨ AI가 내용을 분석하고 있습니다..."):
                    ai_keywords, ai_cats, used_model = analyze_text(text)
                    
                    if used_model == "None":
                         st.error("AI 모델 연결 실패. 잠시 후 다시 시도해주세요.")
                    else:
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
                            st.success(f"✅ 저장 완료! (태그: {', '.join(ai_keywords)} / Model: {used_model})")

    st.markdown("---")
    
    # 리스트 뷰
    df = load_data()
    c_title, c_filter1, c_filter2 = st.columns([2, 1, 1], gap="small")
    with c_title: st.subheader("📜 이전 기록 참고하기")
    
    if not df.empty:
        df['week_str'] = df['date'].apply(get_month_week_str)
        all_writers = sorted(list(set(df['writer'].dropna())))
        
        with c_filter1: 
            selected_writer = st.selectbox("작성자", ["전체 보기"] + all_writers, label_visibility="collapsed")
        with c_filter2: 
            week_options = ["전체 기간"] + sorted(list(set(df['week_str'].dropna())), reverse=True)
            selected_week = st.selectbox("주차 선택", week_options, label_visibility="collapsed")
        
        display_df = df.copy()
        if selected_writer != "전체 보기": display_df = display_df[display_df['writer'] == selected_writer]
        if selected_week != "전체 기간": display_df = display_df[display_df['week_str'] == selected_week]
        
        display_df = display_df.sort_values(by="date", ascending=False)
        
        for idx, row in display_df.iterrows():
            with st.container(border=True):
                c_head, c_btn1, c_btn2 = st.columns([8.8, 0.6, 0.6], gap="small", vertical_alignment="center")
                with c_head:
                    date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                    st.markdown(f"""<div style="display: flex; align-items: center;"><span style="color: #9CA3AF; font-size: 0.9rem;">{date_str}</span><span style="margin: 0 10px; color: #555;">|</span><span style="font-weight: bold; font-size: 1.1rem;">{row['writer']}</span></div>""", unsafe_allow_html=True)
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
                
                cats = parse_categories(row['category'])
                cat_badges = ""
                for c in cats:
                      cat_badges += f'<span style="background-color: {PURPLE_PALETTE[800]}; color: white; padding: 4px 10px; border-radius: 12px; font-size: 0.8rem; font-weight: bold; margin-right: 5px;">{c}</span>'
                
                kw_badges = ""
                for k in kw_list:
                    kw_badges += f'<span style="background-color: #30333F; color: #CCC; padding: 4px 8px; border-radius: 12px; font-size: 0.75rem; margin-right: 5px;">#{k}</span>'

                st.markdown(f"""<div style="margin-top: 20px; display: flex; align-items: center; flex-wrap: wrap; gap: 5px;">{cat_badges}{kw_badges}</div>""", unsafe_allow_html=True)
                st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    else:
        st.info("아직 기록된 내용이 없습니다.")

# --- TAB 2: 대시보드 ---
with tab2:
    df = load_data()
    if not df.empty:
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
        
        row1_col1, row1_col2 = st.columns([1, 3])
        with row1_col1:
            st.subheader("Key Metrics")
            st.metric("총 기록 수", f"{total}건")
            st.metric("가장 핫한 주제", top_cat)
            st.metric("누적 키워드", f"{len(set(all_kws))}개")
            st.metric("최다 작성자", top_writer)

        with row1_col2:
            st.subheader("🗺️ Lesson Map (주제별 탐색)")
            st.caption("🔍 박스를 클릭하면, 하단에 관련 내용이 표시됩니다.")
            
            with st.container(border=True):
                # [트리맵 데이터 전처리] 카테고리 > 키워드 계층 구조 생성
                tree_data = []
                
                for idx, row in df.iterrows():
                    cats = parse_categories(row['category'])
                    try: kws = json.loads(row['keywords'])
                    except: kws = []
                    
                    # 키워드 정제 (빈 것 제거)
                    clean_kws = [k for k in kws if k and str(k).strip() and k != "#분석불가"]
                    if not clean_kws: clean_kws = ["일반"] # 키워드 없으면 일반으로 분류

                    for c in cats:
                        for k in clean_kws:
                            tree_data.append({'Category': c, 'Keyword': k, 'Value': 1})
                
                if tree_data:
                    tree_df = pd.DataFrame(tree_data).groupby(['Category', 'Keyword']).sum().reset_index()
                    max_val = tree_df['Value'].max()
                    
                    labels, parents, values, colors, ids = [], [], [], [], []
                    
                    # 1. 부모 노드 (Category)
                    for cat in tree_df['Category'].unique():
                        val = tree_df[tree_df['Category'] == cat]['Value'].sum()
                        labels.append(cat)
                        parents.append("")
                        values.append(val)
                        ids.append(cat)
                        colors.append(PURPLE_PALETTE[950]) # 부모는 아주 진한 색

                    # 2. 자식 노드 (Keyword)
                    for idx, row in tree_df.iterrows():
                        labels.append(row['Keyword'])
                        parents.append(row['Category'])
                        values.append(row['Value'])
                        ids.append(f"{row['Category']}-{row['Keyword']}")
                        # 자식은 빈도에 따라 밝은 색
                        colors.append(get_relative_color(row['Value'], max_val))
                    
                    fig_tree = go.Figure(go.Treemap(
                        ids=ids,
                        labels=labels, parents=parents, values=values,
                        marker=dict(colors=colors, line=dict(width=2, color=CARD_BG_COLOR)),
                        textinfo="label+value",
                        textfont=dict(family="Pretendard", color="white", size=18),
                        branchvalues="total",
                        hovertemplate='<b>%{label}</b><br>관련 글: %{value}건<extra></extra>'
                    ))
                    fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0), height=500, paper_bgcolor=CARD_BG_COLOR)
                    
                    # [핵심] 클릭 이벤트 리턴
                    event = st.plotly_chart(fig_tree, use_container_width=True, on_select="rerun")
                else:
                    st.info("시각화할 데이터가 부족합니다.")
                    event = None
        
        # --- [Drill-Down] 상세 내용 보기 ---
        st.markdown("---")
        
        selected_label = None
        if event and event.selection and event.selection.points:
            selected_label = event.selection.points[0].get("label")
        
        if selected_label:
            st.subheader(f"📂 '{selected_label}' 관련 레슨런")
            
            # 필터링 로직: 선택된 라벨이 '카테고리'에 있거나 OR '키워드'에 있으면 보여줌
            def filter_func(row):
                c_list = parse_categories(row['category'])
                try: k_list = json.loads(row['keywords'])
                except: k_list = []
                return (selected_label in c_list) or (selected_label in k_list)

            filtered_df = df[df.apply(filter_func, axis=1)]
            
            if not filtered_df.empty:
                filtered_df = filtered_df.sort_values(by="date", ascending=False)
                for idx, row in filtered_df.iterrows():
                    with st.container(border=True):
                        date_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                        st.markdown(f"**{row['writer']}** | <span style='color:#9CA3AF'>{date_str}</span>", unsafe_allow_html=True)
                        st.markdown(f'<hr style="border: 0; border-top: 1px solid #30333F; margin: 5px 0 10px 0;">', unsafe_allow_html=True)
                        st.markdown(row['text'])
                        
                        # 태그 표시
                        cats = parse_categories(row['category'])
                        try: kws = json.loads(row['keywords'])
                        except: kws = []
                        
                        badges = ""
                        # 카테고리 뱃지
                        for c in cats:
                            bg = PURPLE_PALETTE[800] if c == selected_label else "#444"
                            badges += f'<span style="background-color:{bg}; color:white; padding:4px 8px; border-radius:12px; font-size:0.75rem; margin-right:5px;">{c}</span>'
                        # 키워드 뱃지
                        for k in kws:
                            bg = PURPLE_PALETTE[600] if k == selected_label else "#30333F"
                            badges += f'<span style="background-color:{bg}; color:#DDD; padding:4px 8px; border-radius:12px; font-size:0.75rem; margin-right:5px;">#{k}</span>'
                            
                        st.markdown(f"<div style='margin-top:10px;'>{badges}</div>", unsafe_allow_html=True)
            else:
                st.info("해당 주제의 글을 찾을 수 없습니다.")
        else:
            st.info("👆 위 차트에서 **카테고리(큰 박스)**나 **키워드(작은 박스)**를 클릭하면, 여기에 관련 글 목록이 나타납니다.")

        st.markdown("---")
        
        col_chart1, col_chart2 = st.columns(2)
        with col_chart1:
            st.subheader("📊 카테고리 비중")
            with st.container(border=True):
                cat_counts = pd.Series(all_cats_flat).value_counts().reset_index()
                cat_counts.columns = ['category', 'count']
                fig_pie = px.pie(cat_counts, values='count', names='category', hole=0.5, 
                                 color_discrete_sequence=[PURPLE_PALETTE[x] for x in [500, 600, 700, 800, 900]])
                fig_pie.update_layout(height=350, margin=dict(t=20, b=20), paper_bgcolor=CARD_BG_COLOR)
                st.plotly_chart(fig_pie, use_container_width=True)
                
        with col_chart2:
            st.subheader("🏆 Top 키워드")
            with st.container(border=True):
                if all_kws:
                    kw_counts = pd.Series(all_kws).value_counts().head(10).reset_index()
                    kw_counts.columns = ['keyword', 'count']
                    # 상위 10개만
                    fig_bar = go.Figure(go.Bar(
                        x=kw_counts['count'], y=kw_counts['keyword'], orientation='h',
                        text=kw_counts['count'], textposition='outside',
                        marker=dict(color=PURPLE_PALETTE[600])
                    ))
                    fig_bar.update_layout(
                        xaxis=dict(showgrid=False, visible=False), 
                        yaxis=dict(showgrid=False, autorange="reversed"),
                        height=350, margin=dict(t=20, b=20, l=10, r=40),
                        paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR
                    )
                    st.plotly_chart(fig_bar, use_container_width=True)
    else: st.info("데이터를 입력하면 대시보드가 활성화됩니다.")

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

def get_connection():
    return st.connection("gsheets", type=GSheetsConnection)

def load_data(force_reload=False):
    conn = get_connection()
    try:
        # [수정] ttl="10m" 설정으로 10분간 캐싱하여 'Quota exceeded' 에러 방지
        # force_reload가 True일 때만 즉시 갱신 (ttl=0)
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
        # 에러 발생 시 사용자에게 친절하게 안내
        if "Quota" in str(e) or "429" in str(e):
            st.error("🚨 구글 시트 요청량이 너무 많습니다. 잠시(1~2분) 뒤에 다시 시도해주세요.")
        else:
            st.error(f"데이터 로드 실패: {e}")
        return pd.DataFrame(columns=["id", "date", "writer", "text", "keywords", "category"])

def save_data_to_sheet(df):
    conn = get_connection()
    save_df = df.copy()
    if 'date' in save_df.columns:
        save_df['date'] = save_df['date'].dt.strftime('%Y-%m-%d')
    conn.update(data=save_df)
    st.cache_data.clear() # 저장 후 캐시 초기화

def save_entry(writer, text, keywords, categories, date_val):
    df = load_data(force_reload=True) # 저장 전 최신 데이터 로드
    
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
    df = load_data(force_reload=True)
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
    df = load_data(force_reload=True)
    df = df[df['id'] != entry_id]
    save_data_to_sheet(df)

# [핵심] 데이터 파싱 함수 (JSON 리스트 & 일반 문자열 모두 처리)
def parse_json_list(data_str):
    try:
        if not data_str or pd.isna(data_str): return []
        
        # 이미 리스트라면 바로 반환
        if isinstance(data_str, list): return data_str
        
        s = str(data_str).strip()
        # 홑따옴표(')를 쌍따옴표(")로 변환하여 JSON 파싱 시도
        if s.startswith("[") and s.endswith("]"): 
            s = s.replace("'", '"')
            try:
                parsed = json.loads(s)
                return parsed if isinstance(parsed, list) else [str(parsed)]
            except:
                pass # 파싱 실패 시 아래 로직으로 이동
        
        # JSON이 아니거나 실패한 경우, 콤마로 분리하거나 그대로 반환
        clean_s = s.replace('[','').replace(']','').replace('"','').replace("'", "")
        if "," in clean_s:
            return [x.strip() for x in clean_s.split(",") if x.strip()]
        return [clean_s] if clean_s else []
    except:
        return []

def get_available_model():
    try:
        genai.configure(api_key=GOOGLE_API_KEY)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods: return m.name
        return None
    except: return None

def analyze_text(text):
    try:
        model_name = get_available_model()
        if not model_name: return ["AI연동실패"], ["기타"]
        
        model = genai.GenerativeModel(model_name)
        prompt = f"""
        너는 팀의 레슨런을 분류하는 관리자야. 텍스트를 분석해서 JSON으로 답해줘.
        1. keywords: 핵심 단어 2~3개 (Array)
        2. categories: 글의 성격을 나타내는 대분류 (Array). 예: ["기획", "디자인"], ["개발"]
           - 추천: 기획, 디자인, 개발, QA, 배포, 프로세스, 기타
        [형식] {{"keywords": ["키워드1"], "categories": ["카테고리1"]}}
        텍스트: {text}
        """
        response = model.generate_content(prompt)
        text_resp = response.text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text_resp)
        
        cats = result.get("categories", ["기타"])
        kws = result.get("keywords", ["분석불가"])
        
        if isinstance(cats, str): cats = [cats]
        if isinstance(kws, str): kws = [kws]
        
        return kws, cats
    except: return ["AI연동실패"], ["기타"]

def get_month_week_str(date_obj):
    try:
        if pd.isna(date_obj): return ""
        week_num = (date_obj.day - 1) // 7 + 1
        return f"{date_obj.strftime('%y')}년 {date_obj.month}월 {week_num}주차"
    except: return ""

# -----------------------------------------------------------------------------
# 2. UI 및 디자인 설정
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Team Lesson Learned", layout="wide")

if 'edit_mode' not in st.session_state: st.session_state['edit_mode'] = False
if 'edit_data' not in st.session_state: st.session_state['edit_data'] = {}

@st.dialog("⚠️ 삭제 확인")
def confirm_delete_dialog(entry_id):
    st.write("정말 삭제하시겠습니까?")
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("삭제", type="primary", use_container_width=True):
            delete_entry(entry_id)
            st.rerun()
    with col_b:
        if st.button("취소", use_container_width=True): st.rerun()

# [CSS 스타일] 다크 모드 & Pretendard 폰트 강제 적용
st.markdown(f"""
    <style>
    @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css');
    * {{ font-family: 'Pretendard', sans-serif !important; }}
    
    .stApp {{ background-color: {CARD_BG_COLOR}; }}
    
    div[data-testid="stMetric"] {{ 
        background-color: {CARD_BG_COLOR}; 
        border: 1px solid #30333F; 
        padding: 15px; 
        border-radius: 10px; 
    }}
    div[data-testid="stMetricLabel"] {{ color: #9CA3AF !important; font-size: 0.9rem; }}
    div[data-testid="stMetricValue"] {{ color: white !important; font-weight: 700; }}

    div[data-testid="stVerticalBlockBorderWrapper"] {{ 
        background-color: {CARD_BG_COLOR} !important; 
        border: 1px solid #30333F !important; 
        border-radius: 10px !important; 
        padding: 20px !important; 
    }}
    
    .ai-ok {{ color: {PURPLE_PALETTE[500]}; border: 1px solid {PURPLE_PALETTE[500]}; padding: 4px 10px; border-radius: 15px; font-size: 0.8rem; font-weight: bold; }}
    .ai-fail {{ color: #F44336; border: 1px solid #F44336; padding: 4px 10px; border-radius: 15px; font-size: 0.8rem; font-weight: bold; }}
    </style>
""", unsafe_allow_html=True)

# 헤더 영역
c1, c2 = st.columns([5, 1])
with c1:
    st.title("Team Lesson Learned 🚀")
with c2:
    if get_available_model():
        st.markdown(f'<div style="text-align: right; margin-top: 15px;"><span class="ai-ok">AI Ready</span></div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div style="text-align: right; margin-top: 15px;"><span class="ai-fail">AI Offline</span></div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["📝 기록하기", "📊 대시보드"])

# -----------------------------------------------------------------------------
# TAB 1: 기록하기
# -----------------------------------------------------------------------------
with tab1:
    if st.session_state['edit_mode']:
        st.info("✏️ 수정 모드")
        if st.button("취소"):
            st.session_state['edit_mode'] = False; st.session_state['edit_data'] = {}; st.rerun()
        init_writer = st.session_state['edit_data'].get('writer', '')
        init_text = st.session_state['edit_data'].get('text', '')
        d_val = st.session_state['edit_data'].get('date')
        init_date = d_val.date() if isinstance(d_val, pd.Timestamp) else datetime.datetime.now().date()
    else:
        init_writer = ""; init_text = ""; init_date = datetime.datetime.now().date()

    with st.form("main_form", clear_on_submit=True):
        col_f1, col_f2 = st.columns(2)
        with col_f1: writer = st.text_input("작성자", value=init_writer)
        with col_f2: date_val = st.date_input("날짜", value=init_date)
        text = st.text_area("내용", value=init_text, height=120)
        
        submitted = st.form_submit_button("저장하기", use_container_width=True)
        if submitted:
            if not writer or not text: st.error("내용을 입력하세요.")
            else:
                with st.spinner("AI 분석 중..."):
                    kws, cats = analyze_text(text)
                    if st.session_state['edit_mode']:
                        update_entry(st.session_state['edit_data']['id'], writer, text, kws, cats, date_val)
                        st.session_state['edit_mode'] = False; st.session_state['edit_data'] = {}
                    else: save_entry(writer, text, kws, cats, date_val)
                    st.success("저장되었습니다!"); st.rerun()

    st.divider()

    # 데이터 로드 및 새로고침 버튼
    col_list_title, col_refresh = st.columns([8, 2])
    with col_list_title: st.subheader("📜 이전 기록")
    with col_refresh: 
        if st.button("🔄 데이터 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    df = load_data()
    if not df.empty:
        df['week_str'] = df['date'].apply(get_month_week_str)
        fc1, fc2 = st.columns(2)
        writers = ["전체"] + sorted(list(set(df['writer'].dropna())))
        weeks = ["전체"] + sorted(list(set(df['week_str'].dropna())), reverse=True)
        with fc1: f_writer = st.selectbox("작성자 필터", writers)
        with fc2: f_week = st.selectbox("기간 필터", weeks)
        
        view_df = df.copy()
        if f_writer != "전체": view_df = view_df[view_df['writer'] == f_writer]
        if f_week != "전체": view_df = view_df[view_df['week_str'] == f_week]
        view_df = view_df.sort_values('date', ascending=False)
        
        for idx, row in view_df.iterrows():
            with st.container(border=True):
                hc1, hc2, hc3 = st.columns([7, 1, 1])
                d_str = row['date'].strftime('%Y-%m-%d') if isinstance(row['date'], pd.Timestamp) else str(row['date'])[:10]
                with hc1: st.markdown(f"**{row['writer']}** <span style='color:#888; font-size:0.9em;'>({d_str})</span>", unsafe_allow_html=True)
                with hc2: 
                    if st.button("수정", key=f"e_{row['id']}"):
                        st.session_state['edit_mode'] = True; st.session_state['edit_data'] = row.to_dict(); st.rerun()
                with hc3:
                    if st.button("삭제", key=f"d_{row['id']}"): confirm_delete_dialog(row['id'])
                
                st.markdown(row['text'])
                
                # 태그 표시
                cats = parse_json_list(row['category'])
                kws = parse_json_list(row['keywords'])
                badges = "".join([f"<span style='background:{PURPLE_PALETTE[800]}; color:white; padding:3px 8px; border-radius:10px; font-size:0.8em; margin-right:5px;'>{c}</span>" for c in cats])
                kw_text = " ".join([f"#{k}" for k in kws])
                st.markdown(f"<div style='margin-top:10px;'>{badges} <span style='color:#AAA; font-size:0.9em;'>{kw_text}</span></div>", unsafe_allow_html=True)
    else: st.info("데이터가 없거나 로드 중입니다.")

# -----------------------------------------------------------------------------
# TAB 2: 대시보드 (수정됨: 키워드맵 ID충돌 해결 + 디자인)
# -----------------------------------------------------------------------------
with tab2:
    df = load_data()
    if df.empty:
        st.info("데이터가 충분하지 않습니다.")
    else:
        # 데이터 전처리
        all_cats, all_kws, tree_data = [], [], []
        for idx, row in df.iterrows():
            cats = parse_json_list(row['category'])
            kws = parse_json_list(row['keywords'])
            
            all_cats.extend(cats)
            all_kws.extend(kws)
            
            # Treemap 데이터 준비
            temp_kws = kws if kws else ["General"]
            temp_cats = cats if cats else ["기타"]
            for c in temp_cats:
                for k in temp_kws:
                    tree_data.append({'Category': c, 'Keyword': k, 'Value': 1})

        # 상단 지표
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("총 기록", f"{len(df)}건")
        top_cat = pd.Series(all_cats).mode()
        m2.metric("최다 카테고리", top_cat[0] if not top_cat.empty else "-")
        m3.metric("누적 키워드", f"{len(set(all_kws))}개")
        top_writer = df['writer'].mode()
        m4.metric("최다 작성자", top_writer[0] if not top_writer.empty else "-")
        
        st.divider()
        c_left, c_right = st.columns([2, 1])
        
        # [왼쪽] Treemap (ID 충돌 방지 + 다크 모드 디자인)
        with c_left:
            st.subheader("🗺️ 주제별 키워드 맵")
            if tree_data:
                tdf = pd.DataFrame(tree_data).groupby(['Category', 'Keyword']).sum().reset_index()
                
                ids, labels, parents, values = [], [], [], []
                
                # 1. 부모 노드 (카테고리)
                cat_sums = tdf.groupby('Category')['Value'].sum()
                for cat, val in cat_sums.items():
                    ids.append(f"CAT-{cat}")  # 고유 ID
                    labels.append(cat)
                    parents.append("")
                    values.append(val)
                
                # 2. 자식 노드 (키워드)
                for i, row in tdf.iterrows():
                    ids.append(f"KW-{row['Category']}-{row['Keyword']}") # 고유 ID (부모 포함)
                    labels.append(row['Keyword'])
                    parents.append(f"CAT-{row['Category']}")
                    values.append(row['Value'])
                
                fig = go.Figure(go.Treemap(
                    ids=ids, 
                    labels=labels, 
                    parents=parents, 
                    values=values,
                    branchvalues="total", 
                    textinfo="label+value",
                    marker=dict(colorscale='Purples', line=dict(width=1, color=CARD_BG_COLOR)),
                    textfont=dict(family="Pretendard", color="white")
                ))
                fig.update_layout(
                    margin=dict(t=0, l=0, r=0, b=0), height=500,
                    paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR
                )
                st.plotly_chart(fig, use_container_width=True)
            else: st.info("데이터 없음")

        # [오른쪽] 기타 차트
        with c_right:
            st.subheader("📊 카테고리 비중")
            if all_cats:
                cat_counts = pd.Series(all_cats).value_counts().reset_index()
                cat_counts.columns = ['Category', 'Count']
                fig_pie = px.pie(cat_counts, values='Count', names='Category', hole=0.6,
                                 color_discrete_sequence=px.colors.sequential.Purples_r)
                fig_pie.update_layout(
                    margin=dict(t=0, l=0, r=0, b=0), height=250,
                    paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR,
                    font=dict(family="Pretendard", color="white"),
                    showlegend=True
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            
            st.markdown("---")
            st.subheader("🏆 Top 키워드")
            if all_kws:
                kw_counts = pd.Series(all_kws).value_counts().head(7).reset_index()
                kw_counts.columns = ['Keyword', 'Count']
                fig_bar = px.bar(kw_counts, x='Count', y='Keyword', orientation='h',
                                 text='Count', color='Count', color_continuous_scale='Purples')
                fig_bar.update_layout(
                    yaxis={'categoryorder':'total ascending'}, xaxis={'visible': False},
                    margin=dict(t=0, l=0, r=0, b=0), height=250, 
                    paper_bgcolor=CARD_BG_COLOR, plot_bgcolor=CARD_BG_COLOR,
                    font=dict(family="Pretendard", color="white"),
                    coloraxis_showscale=False
                )
                st.plotly_chart(fig_bar, use_container_width=True)

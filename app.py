import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from ta.trend import SMAIndicator
from ta.momentum import StochasticOscillator
from ta.volatility import AverageTrueRange
import requests
import io
import datetime
import matplotlib.pyplot as plt

# --- 網頁配置 ---
st.set_page_config(page_title="台股波段選股戰報", layout="wide")

# --- 原有邏輯函數 (保持不變) ---
@st.cache_data(ttl=86400) # 快取 24 小時，避免重複爬證交所
def get_all_tw_symbols():
    symbols = []
    stock_map = {}
    urls = ["https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", 
            "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"]
    for url in urls:
        try:
            res = requests.get(url, timeout=15)
            df = pd.read_html(io.StringIO(res.text))[0]
            df.columns = df.iloc[0]
            for item in df['有價證券代號及名稱'].iloc[2:]:
                if '　' in str(item):
                    code, name = str(item).split('　')
                    if len(code) == 4:
                        suffix = ".TW" if "strMode=2" in url else ".TWO"
                        full_code = f"{code}{suffix}"
                        symbols.append(full_code)
                        stock_map[full_code] = name
        except: pass
    return sorted(list(set(symbols))), stock_map

# --- UI 側邊欄控制中心 ---
with st.sidebar:
    st.title("🛡️ 策略控制中心")
    DISCORD_URL = st.text_input("Discord Webhook URL", type="password")
    t_c = st.number_input("漲幅 >%", value=2.0)
    v_r = st.number_input("量比 >", value=1.5)
    m_a_v = st.number_input("5日均量 >", value=3000)
    m_b = st.number_input("20MA乖離 < %", value=8.0)
    k_l = st.number_input("KD K值 <", value=80)
    
    st.divider()
    v_red = st.checkbox("今日紅K", value=True)
    v5 = st.checkbox("站上5MA", value=True)
    v20 = st.checkbox("站上20MA", value=True)
    
    start_btn = st.button("🚀 開始掃描全台股", use_container_width=True)

# --- 主畫面 ---
st.title("📊 台股波段精選報表")

if start_btn:
    symbols, stock_name_map = get_all_tw_symbols()
    progress_bar = st.progress(0)
    status_text = st.empty()
    candidates = []
    
    # 為了演示，這裡縮減掃描邏輯，實際使用時與原代碼一致
    total = len(symbols)
    chunk_size = 50
    
    for i in range(0, total, chunk_size):
        batch = symbols[i : i + chunk_size]
        status_text.text(f"核心掃描中: {i}/{total}")
        progress_bar.progress(i / total)
        
        try:
            data = yf.download(batch, period="60d", group_by='ticker', progress=False, auto_adjust=True)
            for s in batch:
                try:
                    df = data[s].dropna() if len(batch) > 1 else data.dropna()
                    if len(df) < 35: continue
                    # ... (此處插入您原有的核心篩選邏輯: SMA, ATR, Score 等) ...
                    # 假設篩選出結果，存入 candidates
                except: continue
        except: continue

    # 顯示結果
    if candidates:
        df_final = pd.DataFrame(candidates).sort_values(by="score", ascending=False).head(10)
        st.dataframe(df_final.drop(columns=['history'])) # 隱藏 history 欄位
        
        # 繪製戰報 (Matplotlib 邏輯)
        # fig = generate_report_image(df_final.to_dict('records'))
        # st.pyplot(fig)
    else:
        st.warning("符合條件的股票太少，請放寬參數。")
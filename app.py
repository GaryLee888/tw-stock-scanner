import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from ta.trend import SMAIndicator
from ta.momentum import StochasticOscillator
from ta.volatility import AverageTrueRange
import requests
import io
import time
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 頁面配置 ---
st.set_page_config(page_title="台股波段完整診斷版", layout="wide")

# --- 設定區：請在此輸入您的預設 Webhook 網址 ---
DEFAULT_WEBHOOK = "https://discord.com/api/webhooks/1457393304537927764/D2vpM73dMl2Z-bLfI0Us52eGdCQyjztASwkBP3RzyF2jaALzEeaigajpXQfzsgLdyzw4"

@st.cache_data(ttl=86400)
def get_all_tw_symbols():
    symbols = []
    stock_map = {}
    urls = ["https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"]
    headers = {'User-Agent': 'Mozilla/5.0'}
    for url in urls:
        try:
            res = requests.get(url, headers=headers, timeout=15, verify=False)
            res.encoding = 'big5'
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

# --- 側邊欄：完整參數保持 ---
with st.sidebar:
    st.header("⚙️ 策略完整參數")
    webhook_url = st.text_input("Discord Webhook", value=DEFAULT_WEBHOOK, type="password")
    
    col1, col2 = st.columns(2)
    with col1:
        t_c = st.number_input("漲幅 >%", value=2.0)
        v_ratio = st.number_input("量比 >", value=1.5)
        m_avg_vol = st.number_input("5日均量 >", value=3000)
    with col2:
        m_bias = st.number_input("20MA乖離 < %", value=8.0)
        vcp_limit = st.number_input("VCP比 <", value=1.3)
        atr_multi = st.number_input("ATR倍數", value=2.5)
    
    k_limit = st.slider("KD K值 <", 0, 100, 80)
    
    st.divider()
    v_red = st.checkbox("今日紅K", value=True)
    v5 = st.checkbox("站上5MA", value=True)
    v20 = st.checkbox("站上20MA", value=True)
    
    start_btn = st.button("🚀 開始全參數掃描", use_container_width=True)

# --- 主畫面 ---
st.title("📊 台股波段精選系統")

if start_btn:
    symbols, stock_name_map = get_all_tw_symbols()
    candidates = []
    stats = {
        "total": len(symbols), "scanned": 0, "fail": 0, 
        "r_change": 0, "r_red": 0, "r_ma": 0, "r_bias": 0, 
        "r_vol": 0, "r_vcp": 0, "r_kd": 0, "pass": 0
    }

    m1, m2, m3 = st.columns(3)
    stat_total = m1.metric("掃描總數", f"{stats['total']}")
    stat_scan = m2.metric("已完成", "0")
    stat_pass = m3.metric("符合條件標的", "0")
    
    st.subheader("🛠️ 即時過濾診斷日誌")
    diag_status = st.empty() 
    progress_bar = st.progress(0)
    
    chunk_size = 40
    for i in range(0, stats['total'], chunk_size):
        batch = symbols[i : i + chunk_size]
        progress_bar.progress(i / stats['total'])
        
        try:
            data = yf.download(batch, period="60d", group_by='ticker', progress=False, auto_adjust=True, threads=False)
            for s in batch:
                stats["scanned"] += 1
                try:
                    df = data[s].dropna() if len(batch) > 1 else data.dropna()
                    if len(df) < 35: stats["fail"] += 1; continue
                    
                    c, h, l, v, o = df['Close'], df['High'], df['Low'], df['Volume'], df['Open']
                    p_today, p_prev = float(c.iloc[-1]), float(c.iloc[-2])
                    change = ((p_today - p_prev) / p_prev) * 100
                    
                    # 邏輯過濾區 (與原版一致)
                    if change < t_c: stats["r_change"] += 1; continue
                    if v_red and p_today <= o.iloc[-1]: stats["r_red"] += 1; continue
                    
                    ma5 = SMAIndicator(c, window=5).sma_indicator().iloc[-1]
                    ma20 = SMAIndicator(c, window=20).sma_indicator().iloc[-1]
                    if (v5 and p_today < ma5) or (v20 and p_today < ma20): stats["r_ma"] += 1; continue
                    
                    bias = ((p_today - ma20) / ma20) * 100
                    if bias > m_bias: stats["r_bias"] += 1; continue
                    
                    vma5 = v.rolling(5).mean().iloc[-1]
                    if (vma5 / 1000) < m_avg_vol or (v.iloc[-1] / vma5) < v_ratio: stats["r_vol"] += 1; continue
                    
                    atr_s = AverageTrueRange(h, l, c, window=14).average_true_range()
                    vcp_val = (atr_s.iloc[-1] / atr_s.tail(20).mean())
                    if vcp_val > vcp_limit: stats["r_vcp"] += 1; continue
                        
                    stoch = StochasticOscillator(h, l, c, window=9)
                    if not (stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1] and stoch.stoch().iloc[-1] < k_limit):
                        stats["r_kd"] += 1; continue

                    stats["pass"] += 1
                    score = (change * 0.4) + ((v.iloc[-1] / vma5) * 4) + (10 - bias)
                    sl = max(p_today - (atr_s.iloc[-1] * atr_multi), l.tail(10).min() * 0.99)
                    
                    candidates.append({
                        "代碼": s, "名稱": stock_name_map.get(s, "未知"), "現價": round(p_today, 2), 
                        "漲幅%": round(change, 2), "評分": round(score, 1), "乖離%": round(bias, 1),
                        "VCP比": round(vcp_val, 2), "score": score, "sl": sl, "tp": p_today + (p_today-sl)*2
                    })
                except: stats["fail"] += 1
        except: pass
        
        stat_scan.metric("已完成", f"{stats['scanned']}")
        stat_pass.metric("符合條件標的", f"{stats['pass']}")
        
        # 顯示即時診斷文字
        diag_text = f"""
        - 📥 下載失敗或資料不足: **{stats['fail']}**
        - ❌ 漲幅不足 (<{t_c}%): **{stats['r_change']}**
        - ❌ 未收紅K: **{stats['r_red']}**
        - ❌ 均線未站上 (5MA/20MA): **{stats['r_ma']}**
        - ❌ 乖離率過高 (>{m_bias}%): **{stats['r_bias']}**
        - ❌ 成交量能不足 (量比/均量): **{stats['r_vol']}**
        - ❌ VCP波動過大 (>{vcp_limit}): **{stats['r_vcp']}**
        - ❌ KD指標不符: **{stats['r_kd']}**
        """
        diag_status.markdown(diag_text)

    st.divider()
    if candidates:
        st.success(f"✅ 掃描完成！發現 {len(candidates)} 檔標的。")
        final_df = pd.DataFrame(candidates).sort_values("score", ascending=False).head(10)
        st.subheader("🏆 波段精選 Top 10")
        st.dataframe(final_df.drop(columns=['score', 'sl', 'tp']), use_container_width=True)
        
        if webhook_url:
            msg = "📊 **台股波段掃描戰報**\n"
            for _, row in final_df.iterrows():
                msg += f"🔹 {row['代碼']} {row['名稱']} | 價: {row['現價']} | 漲: {row['漲幅%']}% | 評分: {row['評分']}\n"
            requests.post(webhook_url, json={"content": msg})
    else:
        st.error("😭 掃描完成，無符合條件標的。請檢查日誌調整參數。")


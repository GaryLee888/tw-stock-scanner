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
import matplotlib.pyplot as plt
import urllib3

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

st.set_page_config(page_title="台股波段選股診斷版", layout="wide")

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

# --- 介面設計 ---
st.title("🚀 台股強勢選股 (含偵測診斷系統)")

with st.sidebar:
    st.header("⚙️ 策略與推播")
    webhook_url = st.text_input("Discord Webhook", type="password")
    t_c = st.number_input("漲幅 >%", value=2.0, step=0.1)
    v_ratio = st.number_input("量比 >", value=1.5, step=0.1)
    m_avg_vol = st.number_input("5日均量 >(張)", value=3000)
    
    st.divider()
    v_red = st.checkbox("今日紅K", value=True)
    v5 = st.checkbox("站上5MA", value=True)
    v20 = st.checkbox("站上20MA", value=True)
    start_btn = st.button("🚀 開始全自動掃描", use_container_width=True)

if start_btn:
    symbols, stock_name_map = get_all_tw_symbols()
    candidates = []
    
    # --- 診斷統計初始化 ---
    stats = {
        "total": len(symbols),
        "scanned": 0,
        "fail_download": 0,
        "reject_change": 0,
        "reject_red_k": 0,
        "reject_ma": 0,
        "reject_vol": 0,
        "reject_kd": 0,
        "passed": 0
    }

    # 建立診斷顯示區
    diag_col1, diag_col2, diag_col3 = st.columns(3)
    stat_total = diag_col1.metric("掃描總數", f"{stats['total']}")
    stat_scan = diag_col2.metric("已完成", "0")
    stat_pass = diag_col3.metric("符合條件", "0", delta_color="normal")
    
    debug_area = st.expander("🛠️ 詳細篩選診斷日誌 (即時更新)", expanded=True)
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
                    if len(df) < 35:
                        stats["fail_download"] += 1
                        continue
                    
                    c, h, l, v, o = df['Close'], df['High'], df['Low'], df['Volume'], df['Open']
                    p_today, p_prev = float(c.iloc[-1]), float(c.iloc[-2])
                    change = ((p_today - p_prev) / p_prev) * 100
                    
                    # 診斷篩選過程
                    if change < t_c:
                        stats["reject_change"] += 1; continue
                    if v_red and p_today <= o.iloc[-1]:
                        stats["reject_red_k"] += 1; continue
                    
                    ma5 = SMAIndicator(c, window=5).sma_indicator().iloc[-1]
                    ma20 = SMAIndicator(c, window=20).sma_indicator().iloc[-1]
                    if (v5 and p_today < ma5) or (v20 and p_today < ma20):
                        stats["reject_ma"] += 1; continue
                    
                    vma5 = v.rolling(5).mean().iloc[-1]
                    if (vma5 / 1000) < m_avg_vol or (v.iloc[-1] / vma5) < v_ratio:
                        stats["reject_vol"] += 1; continue
                        
                    stoch = StochasticOscillator(h, l, c, window=9)
                    if not (stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1]):
                        stats["reject_kd"] += 1; continue

                    # 通過篩選
                    stats["passed"] += 1
                    atr_now = AverageTrueRange(h, l, c, window=14).average_true_range().iloc[-1]
                    score = (change * 0.4) + ((v.iloc[-1] / vma5) * 4)
                    sl = max(p_today - (atr_now * 2.5), l.tail(10).min() * 0.99)
                    
                    candidates.append({
                        "代碼": s, "名稱": stock_name_map.get(s, "未知"), "現價": round(p_today, 2), 
                        "漲幅%": round(change, 2), "評分": round(score, 1), "score": score,
                        "history": c, "tp": p_today + (p_today-sl)*2, "sl": sl
                    })
                except: stats["fail_download"] += 1
        except: pass
        
        # 每批次更新一次 UI
        stat_scan.metric("已完成", f"{stats['scanned']}")
        stat_pass.metric("符合條件", f"{stats['passed']}")
        with debug_area:
            st.write(f"⏱️ 診斷狀態: 下載失敗({stats['fail_download']}) | 漲幅不符({stats['reject_change']}) | 未收紅({stats['reject_red_k']}) | 均線不符({stats['reject_ma']}) | 量能不足({stats['reject_vol']})")

    progress_bar.progress(1.0)
    
    # --- 結果展示 ---
    if candidates:
        st.success(f"✅ 掃描完成！發現 {len(candidates)} 檔標的")
        final_df = pd.DataFrame(candidates).sort_values("score", ascending=False).head(10)
        st.dataframe(final_df.drop(columns=['score', 'history', 'tp', 'sl']), use_container_width=True)
    else:
        st.error("❌ 掃描結束，無任何股票符合條件。請參考上方的詳細診斷日誌調整參數。")

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
import time
import matplotlib.pyplot as plt

# --- 頁面設定 ---
st.set_page_config(page_title="台股波段選股戰報", layout="wide")

# --- 核心函數：獲取股票清單 ---
@st.cache_data(ttl=86400)
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
        except:
            pass
    return sorted(list(set(symbols))), stock_map

# --- 核心函數：生成 Discord 戰報圖 ---
def generate_report_image(target_list, page_num=1):
    try:
        plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'sans-serif'] # 雲端主機通常無中文字體，建議用預設
        fig = plt.figure(figsize=(12, 10), dpi=100)
        fig.patch.set_facecolor('#0d1117')
        plt.suptitle(f"🚀 台股波段精選 (Page {page_num})", color='#d2a8ff', fontsize=24, y=0.98)

        for i, row in enumerate(target_list):
            ax_chart = plt.subplot2grid((5, 10), (i, 0), colspan=6)
            ax_chart.set_facecolor('#161b22')
            prices = row['history'].tail(30)
            ax_chart.plot(range(len(prices)), prices.values, color='#58a6ff', lw=2)
            ax_chart.axhline(row['tp'], color='#ff7b72', linestyle='--', alpha=0.6)
            ax_chart.axhline(row['sl'], color='#7ee787', linestyle='--', alpha=0.6)
            ax_chart.axis('off')

            ax_text = plt.subplot2grid((5, 10), (i, 6), colspan=4)
            ax_text.set_facecolor('#0d1117')
            ax_text.axis('off')
            ax_text.text(0, 0.5, f"{row['name']} ({row['code']})\nPrice: {row['price']:.1f}\nTP: {row['tp']:.1f} / SL: {row['sl']:.1f}", 
                         color='white', fontsize=12, verticalalignment='center')
        
        plt.tight_layout(rect=[0, 0.03, 1, 0.95])
        buf = io.BytesIO()
        plt.savefig(buf, format='png', facecolor=fig.get_facecolor())
        buf.seek(0)
        plt.close(fig)
        return buf
    except:
        return None

# --- 側邊欄控制 ---
with st.sidebar:
    st.title("🛡️ 策略控制中心")
    webhook_url = st.text_input("Discord Webhook URL", type="password", help="若不填寫則不發送推播")
    
    st.subheader("參數設定")
    t_c = st.number_input("漲幅 >%", value=2.0)
    v_ratio = st.number_input("量比 >", value=1.5)
    m_avg_vol = st.number_input("5日均量 > (張)", value=3000)
    m_bias = st.number_input("20MA乖離 < %", value=8.0)
    k_limit = st.slider("KD K值 <", 0, 100, 80)
    vcp_limit = st.number_input("VCP波動比 <", value=1.3)
    atr_multi = st.number_input("ATR停損倍數", value=2.5)
    
    st.divider()
    v_red = st.checkbox("今日紅K", value=True)
    v5 = st.checkbox("站上5MA", value=True)
    v20 = st.checkbox("站上20MA", value=True)
    
    start_btn = st.button("🚀 開始掃描全台股", use_container_width=True)

# --- 主畫面邏輯 ---
st.header("📈 即時選股戰報")

if start_btn:
    symbols, stock_name_map = get_all_tw_symbols()
    candidates = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    # 執行掃描
    chunk_size = 50
    total = len(symbols)
    
    for i in range(0, total, chunk_size):
        batch = symbols[i : i + chunk_size]
        status_text.text(f"正在掃描第 {i} ~ {min(i+chunk_size, total)} 檔股票...")
        progress_bar.progress(i / total)
        
        try:
            data = yf.download(batch, period="60d", group_by='ticker', progress=False, auto_adjust=True)
            for s in batch:
                try:
                    df = data[s].dropna() if len(batch) > 1 else data.dropna()
                    if len(df) < 35: continue
                    
                    c, h, l, v, o = df['Close'], df['High'], df['Low'], df['Volume'], df['Open']
                    p_today, p_prev = float(c.iloc[-1]), float(c.iloc[-2])
                    change = ((p_today - p_prev) / p_prev) * 100
                    
                    # 篩選邏輯
                    if change < t_c: continue
                    if v_red and p_today <= o.iloc[-1]: continue
                    
                    ma20 = SMAIndicator(c, window=20).sma_indicator().iloc[-1]
                    bias = ((p_today - ma20) / ma20) * 100
                    if bias > m_bias: continue
                    
                    if v5 and p_today < SMAIndicator(c, window=5).sma_indicator().iloc[-1]: continue
                    if v20 and p_today < ma20: continue
                    
                    vma5 = v.rolling(5).mean().iloc[-1]
                    if (vma5 / 1000) < m_avg_vol or (v.iloc[-1] / vma5) < v_ratio: continue
                    
                    atr_s = AverageTrueRange(h, l, c, window=14).average_true_range()
                    vcp_val = (atr_s.iloc[-1] / atr_s.tail(20).mean())
                    if vcp_val > vcp_limit: continue
                    
                    stoch = StochasticOscillator(h, l, c, window=9)
                    if not (stoch.stoch().iloc[-1] > stoch.stoch_signal().iloc[-1] and stoch.stoch().iloc[-1] < k_limit): continue

                    # 評分與計算
                    score = (change * 0.4) + ((v.iloc[-1] / vma5) * 4) + (10 - bias)
                    sl = max(p_today - (atr_s.iloc[-1] * atr_multi), l.tail(10).min() * 0.99)
                    tp = p_today + (p_today - sl) * 2
                    
                    candidates.append({
                        "code": s, "name": stock_name_map.get(s, "未知"), "price": p_today, "change": change,
                        "score": score, "tp": tp, "sl": sl, "bias": bias, "vcp": vcp_val, "avg_vol": vma5/1000,
                        "history": c
                    })
                except: continue
        except: continue
        time.sleep(0.1)

    progress_bar.progress(1.0)
    status_text.text("掃描完成！")

    if candidates:
        top_10 = sorted(candidates, key=lambda x: x['score'], reverse=True)[:10]
        df_display = pd.DataFrame(top_10).drop(columns=['history'])
        st.subheader("🏆 精選 Top 10")
        st.dataframe(df_display.style.format(precision=2))
        
        # 下載 Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_display.to_excel(writer, index=False)
        st.download_button("📥 下載 Excel 報表", output.getvalue(), "pick.xlsx")
        
        # Discord 發送
        if webhook_url:
            for idx in range(0, len(top_10), 5):
                img_buf = generate_report_image(top_10[idx:idx+5], page_num=(idx//5)+1)
                if img_buf:
                    requests.post(webhook_url, files={"file": ("report.png", img_buf, "image/png")}, data={"content": "📊 手機端掃描戰報"})
            st.success("戰報已推播至 Discord！")
    else:
        st.error("找不到符合條件的股票，請調整參數。")

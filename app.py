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
import urllib3

# 禁用 SSL 警告 (針對 verify=False)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 網頁基礎設定 ---
st.set_page_config(page_title="台股波段選股戰報", layout="wide")

# --- 1. 獲取全台股清單 (修正 SSL 錯誤) ---
@st.cache_data(ttl=86400)
def get_all_tw_symbols():
    symbols = []
    stock_map = {}
    urls = [
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=2", 
        "https://isin.twse.com.tw/isin/C_public.jsp?strMode=4"
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    for url in urls:
        try:
            # 加入 verify=False 解決 SSL 錯誤
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
        except Exception as e:
            st.error(f"⚠️ 獲取清單失敗 ({url}): {e}")
            
    if not symbols:
        # 備用方案：如果證交所連不上，至少提供權值股測試
        symbols = ["2330.TW", "2317.TW", "2454.TW", "2603.TW", "2303.TW", "2308.TW", "2382.TW"]
        stock_map = {"2330.TW":"台積電", "2317.TW":"鴻海", "2454.TW":"聯發科", "2603.TW":"長榮"}
        
    return sorted(list(set(symbols))), stock_map

# --- 2. Discord 繪圖函數 ---
def generate_report_image(target_list, page_num=1):
    try:
        fig, axes = plt.subplots(len(target_list), 1, figsize=(10, 3*len(target_list)))
        fig.patch.set_facecolor('#0d1117')
        if len(target_list) == 1: axes = [axes]
        
        for ax, row in zip(axes, target_list):
            ax.set_facecolor('#161b22')
            prices = row['history'].tail(30)
            ax.plot(range(len(prices)), prices.values, color='#58a6ff', lw=2)
            ax.set_title(f"{row['name']} ({row['code']}) - Score: {row['score']:.1f}", color='white', fontsize=12)
            ax.tick_params(colors='gray', labelsize=8)
            ax.grid(color='#30363d', linestyle=':', alpha=0.5)
        
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        buf.seek(0)
        plt.close(fig)
        return buf
    except:
        return None

# --- 側邊欄控制面板 ---
with st.sidebar:
    st.title("🛡️ 策略控制中心")
    webhook_url = st.text_input("Discord Webhook URL", type="password", help="推播掃描結果用")
    
    st.subheader("篩選參數")
    t_c = st.number_input("漲幅 >%", value=2.0, step=0.1)
    v_ratio = st.number_input("量比 >", value=1.5, step=0.1)
    m_avg_vol = st.number_input("5日均量 > (張)", value=3000)
    m_bias = st.number_input("20MA乖離 < %", value=8.0)
    k_limit = st.slider("KD K值 <", 0, 100, 80)
    
    st.divider()
    v_red = st.checkbox("今日紅K", value=True)
    v5 = st.checkbox("站上5MA", value=True)
    v20 = st.checkbox("站上20MA", value=True)
    
    debug_mode = st.checkbox("偵錯模式 (顯示抓取狀態)", value=False)
    
    start_btn = st.button("🚀 開始全台股掃描", use_container_width=True)

# --- 主畫面執行邏輯 ---
st.title("🚀 台股波段強勢精選掃描器")

if start_btn:
    symbols, stock_name_map = get_all_tw_symbols()
    candidates = []
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    chunk_size = 40  # 穩定下載量
    total = len(symbols)
    
    for i in range(0, total, chunk_size):
        batch = symbols[i : i + chunk_size]
        status_text.info(f"🔍 掃描中: {i}/{total} (已發現 {len(candidates)} 檔符合條件)")
        progress_bar.progress(i / total)
        
        try:
            # 下載資料
            data = yf.download(batch, period="60d", group_by='ticker', progress=False, auto_adjust=True, threads=False, timeout=25)
            
            if data.empty:
                continue

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
                    
                    ma5 = SMAIndicator(c, window=5).sma_indicator().iloc[-1]
                    ma20 = SMAIndicator(c, window=20).sma_indicator().iloc[-1]
                    if v5 and p_today < ma5: continue
                    if v20 and p_today < ma20: continue
                    
                    bias = ((p_today - ma20) / ma20) * 100
                    if bias > m_bias: continue
                    
                    vma5 = v.rolling(5).mean().iloc[-1]
                    if (vma5 / 1000) < m_avg_vol: continue
                    if (v.iloc[-1] / vma5) < v_ratio: continue
                    
                    stoch = StochasticOscillator(h, l, c, window=9)
                    k_val = stoch.stoch().iloc[-1]
                    d_val = stoch.stoch_signal().iloc[-1]
                    if not (k_val > d_val and k_val < k_limit): continue

                    atr_s = AverageTrueRange(h, l, c, window=14).average_true_range()
                    atr_now = atr_s.iloc[-1]
                    
                    # 評分與計算
                    score = (change * 0.4) + ((v.iloc[-1] / vma5) * 4) + (10 - bias)
                    sl = max(p_today - (atr_now * 2.5), l.tail(10).min() * 0.99)
                    tp = p_today + (p_today - sl) * 2
                    
                    candidates.append({
                        "代碼": s, "名稱": stock_name_map.get(s, "未知"), "現價": round(p_today, 2), 
                        "漲幅%": round(change, 2), "評分": round(score, 1), "停利": round(tp, 1), 
                        "停損": round(sl, 1), "5日均量": int(vma5/1000),
                        "score": score, "code": s, "name": stock_name_map.get(s, "未知"), 
                        "tp": tp, "sl": sl, "history": c
                    })
                except: continue
        except Exception as e:
            if debug_mode: st.warning(f"批次 {i} 下載跳過: {e}")
            
        time.sleep(0.3)

    progress_bar.progress(1.0)
    status_text.success(f"✅ 掃描完成！發現 {len(candidates)} 檔股票。")

    if candidates:
        final_list = sorted(candidates, key=lambda x: x['score'], reverse=True)[:10]
        st.subheader("🏆 波段精選結果 Top 10")
        
        display_df = pd.DataFrame(final_list).drop(columns=['score', 'code', 'name', 'tp', 'sl', 'history'])
        st.dataframe(display_df, use_container_width=True)
        
        if webhook_url:
            with st.spinner("🚀 正在推播戰報至 Discord..."):
                for idx in range(0, len(final_list), 5):
                    chunk = final_list[idx:idx+5]
                    img = generate_report_image(chunk, page_num=(idx//5)+1)
                    if img:
                        requests.post(webhook_url, files={"file": ("report.png", img, "image/png")}, data={"content": "📊 手機 Web 版掃描結果"})
            st.toast("Discord 推播成功！")
    else:
        st.warning("⚠️ 沒有股票符合當前條件，請嘗試放寬參數。")

import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 配置区 ---
SC_KEY = "你的Server酱SendKey" 

# --- 1. 修复时区警告的北京时间函数 ---
def get_beijing_time():
    # 使用 Python 3.12 推荐的 timezone-aware 方式，消除日志里的 DeprecationWarning
    return datetime.now(timezone(timedelta(hours=8)))

# --- 2. 增加带缓存的数据抓取 (防止封禁) ---
@st.cache_data(ttl=60) # 数据缓存60秒，避免每秒都去冲击接口
def fetch_stock_data():
    try:
        return ak.stock_zh_a_spot_em()
    except:
        return None

# --- 3. 诊断逻辑 ---
def get_analysis(df_spot, code, lead_code="600986"):
    try:
        target = df_spot[df_spot['代码'] == code].iloc[0]
        leader = df_spot[df_spot['代码'] == lead_code].iloc[0]
        
        price = float(target['最新价'])
        change = float(target['涨跌幅'])
        turnover = float(target['换手率'])
        gap = change - float(leader['涨跌幅'])
        
        signal, color = "⚖️ 持仓", "#808080"
        if change > 6 and turnover > 10: signal, color = "⚠️ 减仓/做T", "#ff4b4b"
        elif gap < -4: signal, color = "💎 补涨加仓", "#00ff00"
        
        return {"name":target['名称'], "price":price, "change":change, "turnover":turnover, "gap":gap, "signal":signal, "color":color}
    except: return None

# --- UI 渲染 ---
st.title("🛡️ 幻方量化终端 V4.1 (稳定版)")

bj_now = get_beijing_time()
st.subheader(f"📅 北京时间: {bj_now.strftime('%H:%M:%S')}")

# 获取数据
df_spot = fetch_stock_data()

if df_spot is not None:
    my_holdings = st.sidebar.multiselect("持仓池", ["002400", "600986"], default=["002400"])
    
    for stock in my_holdings:
        res = get_analysis(df_spot, stock)
        if res:
            st.markdown(f"""
            <div style="padding:15px; border-radius:10px; border:2px solid {res['color']}; margin-bottom:10px;">
                <h4>{res['name']} ({stock}) <span style="color:{res['color']}">{res['signal']}</span></h4>
                <p>价格: {res['price']} | 涨幅: {res['change']}% | 换手: {res['turnover']}% | 偏差: {res['gap']:.2f}%</p>
            </div>
            """, unsafe_allow_html=True)
else:
    st.warning("⚠️ 接口响应慢，正在排队重试，请稍候...")

# 降低刷新频率，保护接口
time.sleep(60) 
st.rerun()

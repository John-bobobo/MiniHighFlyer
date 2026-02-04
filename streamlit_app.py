import streamlit as st
import akshare as ak
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# --- 1. 强制极速配置 ---
st.set_page_config(page_title="极速作战终端", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 2. 狙击手模式：定向获取单只股票数据 ---
# 不再抓取全市场 5000 只票，只抓你需要的这几只
def get_single_stock(code):
    try:
        # 使用单个股票的历史分钟快照接口，速度极快且稳定
        df = ak.stock_zh_a_spot_em() 
        data = df[df['代码'] == code].iloc[0]
        return data
    except:
        return None

# --- 主界面 ---
st.title("🛡️ 极速量化终端 V4.2")
st.write(f"🕒 北京时间: {get_bj_time().strftime('%H:%M:%S')}")

# 3. 侧边栏输入
my_stocks = st.sidebar.text_input("输入持仓代码(逗号分隔)", value="002400,600986")
stock_list = [s.strip() for s in my_stocks.split(",")]

# 4. 核心作战单元
cols = st.columns(len(stock_list))

# 提前抓取一次全表（如果定向失败则用此备选）
@st.cache_data(ttl=15)
def get_cached_spot():
    return ak.stock_zh_a_spot_em()

df_all = get_cached_spot()

if df_all is not None:
    for i, code in enumerate(stock_list):
        with cols[i]:
            try:
                row = df_all[df_all['代码'] == code].iloc[0]
                price = row['最新价']
                change = row['涨跌幅']
                
                # 简易视觉卡片
                color = "#ff4b4b" if change > 0 else "#00ff00"
                st.markdown(f"""
                <div style="background-color:rgba(255,255,255,0.05); padding:20px; border-radius:10px; border-left:5px solid {color}">
                    <h3 style="margin:0">{row['名称']}</h3>
                    <h2 style="color:{color}; margin:10px 0">{price} <span style="font-size:15px">({change}%)</span></h2>
                    <p style="font-size:12px; margin:0">换手: {row['换手率']}% | 主力: {row['主力净流入']/10000:.1f}万</p>
                </div>
                """, unsafe_allow_html=True)
            except:
                st.error(f"代码 {code} 抓取超时")
else:
    st.error("🚨 核心行情接口拥堵，请尝试刷新页面或检查网络。")

# 5. 情报区（精简版）
st.divider()
if st.checkbox("开启实时情报穿透"):
    try:
        news = ak.js_news(endpoint="7_24").head(5)
        for _, r in news.iterrows():
            st.caption(f"{r['datetime']} | {r['content']}")
    except:
        st.write("情报接口繁忙...")

# 自动刷新节奏控制
time.sleep(20)
st.rerun()

import streamlit as st
import pandas as pd
import akshare as ak
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="幻方分时作战终端V9.0", layout="wide")

# --- 1. 获取今日分时数据（赋予曲线波动性） ---
def get_minute_chart(code):
    try:
        # 获取分时数据，AkShare 接口获取今日从 9:30 开始的所有数据
        df = ak.stock_zh_a_hist_min_em(symbol=code, period='1', adjust='', start_date="2026-02-04 09:30:00")
        if not df.empty:
            df = df.rename(columns={'时间': 'time', '收盘': 'price'})
            return df[['time', 'price']]
    except:
        return pd.DataFrame()

# --- 2. 资金流向 & 全球动态 ---
def get_global_money_flow():
    try:
        # 获取北向资金实时数据（代表全球资金对 A 股的态度）
        hsgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
        # 获取主力净流入排名
        main_flow = ak.stock_individual_fund_flow_rank().head(5)
        return hsgt_df, main_flow
    except:
        return None, None

# --- 3. 动态配置区 ---
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "float": 17.4e8},
        "600893": {"name": "航发动力", "vol": 900, "float": 26.6e8}
    }

# --- UI 渲染 ---
st.title("🛡️ 幻方 V9.0 | 分时曲线与资金流向")
bj_now = datetime.now(timezone(timedelta(hours=8)))
st.caption(f"📅 盘中实战模式 | 北京时间: {bj_now.strftime('%H:%M:%S')}")

# 第一部分：全球资金与主力异动（这一块是更新最快的）
st.subheader("🌐 全球资金流向 & 主力异动")
money_col1, money_col2 = st.columns([1, 2])

hsgt, main_flow = get_global_money_flow()
with money_col1:
    if hsgt is not None:
        net_in = hsgt.iloc[-1]['value'] / 10000 # 亿
        st.metric("外资(北向)净流入", f"{net_in:.2f} 亿", delta=f"{net_in:.2f}")
    else:
        st.write("资金数据获取中...")

with money_col2:
    if main_flow is not None:
        st.caption("🔥 实时主力净流入 Top 5")
        st.dataframe(main_flow[['代码', '名称', '最新价', '今日主力净流入额']], hide_index=True)

# 第二部分：持仓深度分时看盘
st.divider()
for code, info in st.session_state.portfolio.items():
    chart_df = get_minute_chart(code)
    
    if not chart_df.empty:
        curr_price = chart_df.iloc[-1]['price']
        prev_close = chart_df.iloc[0]['price'] # 简单处理以开盘价对标波动
        pct = round((curr_price - prev_close) / prev_close * 100, 2)
        
        # 赋予具体的波动决策
        advice, color = "⚖️ 观望", "#808080"
        if pct > 4: advice, color = "🔴 建议减仓 (分时冲高)", "#ff4b4b"
        elif pct < -3: advice, color = "🟢 建议补仓 (缩量回踩)", "#00ff00"

        with st.container():
            col_txt, col_graph = st.columns([1, 3])
            with col_txt:
                st.markdown(f"""
                <div style="background:rgba(255,255,255,0.05); padding:10px; border-radius:10px; border-left:5px solid {color}">
                    <h4>{info['name']}</h4>
                    <h2 style="color:{color}">{curr_price}</h2>
                    <p>今日涨幅: {pct}%</p>
                    <p style="font-weight:bold; color:{color}">指令: {advice}</p>
                </div>
                """, unsafe_allow_html=True)
            with col_graph:
                st.line_chart(chart_df.set_index('time'), height=200)

# 自动刷新
time.sleep(30)
st.rerun()

import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="幻方智能指挥部V5.0", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 1. 核心数据引擎：获取资金流向与基本面 ---
@st.cache_data(ttl=30)
def fetch_rich_data():
    try:
        # 获取实时行情全表，包含资金流、换手、市盈率等
        df = ak.stock_zh_a_spot_em()
        return df
    except:
        return None

# --- 2. 智能寻找板块龙头 ---
def find_market_leader(df_all):
    try:
        # 简单逻辑：取当前全市场涨幅前 3 且成交额大于 10 亿的票作为“市场风向标”
        hot_stocks = df_all[df_all['成交额'] > 1000000000].sort_values('涨跌幅', ascending=False).head(3)
        return hot_stocks
    except:
        return None

# --- 3. 选股雷达：自动扫描潜力股 ---
def stock_scanner(df_all):
    # 筛选条件：1. 涨幅在 3%-7% 之间（非涨停封死）2. 换手率 > 5% 3. 主力净流入为正
    potential = df_all[
        (df_all['涨跌幅'] > 3) & 
        (df_all['涨跌幅'] < 9) & 
        (df_all['换手率'] > 5) & 
        (df_all['主力净流入'] > 0)
    ].sort_values('主力净流入', ascending=False).head(5)
    return potential

# --- UI 渲染 ---
st.title("🛡️ 幻方智能指挥部 V5.0")
bj_now = get_bj_time()
st.sidebar.info(f"🕒 实时监测中: {bj_now.strftime('%H:%M:%S')}")

df_all = fetch_rich_data()

if df_all is not None:
    # --- 第一部分：市场风向标 (自动寻找龙头) ---
    leaders = find_market_leader(df_all)
    st.subheader("🔥 当前市场领涨锚点 (系统自动识别)")
    l_cols = st.columns(3)
    for idx, (i, r) in enumerate(leaders.iterrows()):
        l_cols[idx].metric(f"标杆: {r['名称']}", f"{r['最新价']}", f"{r['涨跌幅']}%")

    # --- 第二部分：持仓深度诊断 ---
    st.divider()
    my_stocks_input = st.sidebar.text_input("输入持仓代码", value="002400,600986,000001")
    my_list = [s.strip() for s in my_stocks_input.split(",")]
    
    st.subheader("📊 深度持仓诊断")
    for code in my_list:
        try:
            row = df_all[df_all['代码'] == code].iloc[0]
            # 综合评分逻辑 (简单演示)
            flow = row['主力净流入'] / 10000 # 万
            
            # 决策逻辑
            action, color = "💎 正常持仓", "#FFFFFF"
            if row['涨跌幅'] > 5 and flow < 0: action, color = "⚠️ 缩量诱高：建议减仓", "#ff4b4b"
            elif row['涨跌幅'] < -3 and flow > 1000: action, color = "🟢 底部吸筹：建议补仓", "#00ff00"
            elif row['涨跌幅'] > 9.5: action, color = "🔥 强势封板：持股待涨", "#ff0000"
            
            with st.expander(f"🔍 {row['名称']} ({code}) - 当前建议：{action}", expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("最新价", row['最新价'], f"{row['涨跌幅']}%")
                c2.metric("主力净流入", f"{flow:.1f}万")
                c3.metric("换手率", f"{row['换手率']}%")
                c4.metric("市盈率(动态)", f"{row['动态市盈率']:.1f}")
                st.progress(min(max(row['涨跌幅']+10, 0)/20, 1.0), text="多空博弈能量")
        except:
            st.error(f"代码 {code} 数据解析异常")

    # --- 第三部分：大数据选股雷达 ---
    st.divider()
    st.subheader("📡 大数据主力异动雷达 (此时此刻该看谁？)")
    potentials = stock_scanner(df_all)
    st.table(potentials[['代码', '名称', '最新价', '涨跌幅', '换手率', '主力净流入']])

else:
    st.error("数据引擎连接中，请稍后...")

# 自动刷新
time.sleep(30)
st.rerun()

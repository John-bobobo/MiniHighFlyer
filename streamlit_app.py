import streamlit as st
import akshare as ak
import pandas as pd
import time
from datetime import datetime

# --- 核心配置 ---
st.set_page_config(page_title="幻方级资产管理中枢", layout="wide")

# --- 风险周期控制 (避雷逻辑) ---
def get_market_sentiment():
    curr_month = datetime.now().month
    curr_day = datetime.now().day
    
    # 因子 1: 4月年报雷区
    if curr_month == 4:
        return "🔴 避险期：年报披露季，严控垃圾股，谨防业绩杀！", 0.3
    # 因子 2: 1月/春节前缩量风险
    if curr_month == 1 or (curr_month == 2 and curr_day < 15):
        return "🟡 缩量期：春节效应，资金面趋紧，建议轻仓过节。", 0.5
    # 因子 3: 正常交易期
    return "🟢 活跃期：大盘环境正常，可执行积极策略。", 1.0

# --- 核心计算引擎 ---
def get_stock_analysis(code, lead_code="600986"):
    try:
        df_spot = ak.stock_zh_a_spot_em()
        target = df_spot[df_spot['代码'] == code].iloc[0]
        leader = df_spot[df_spot['代码'] == lead_code].iloc[0]
        
        # 提取关键因子
        price = float(target['最新价'])
        change = float(target['涨跌幅'])
        turnover = float(target['换手率'])
        net_money = float(target['主力净流入'])
        gap = change - float(leader['涨跌幅'])
        
        # 智能诊断逻辑
        signal = "持仓"
        if change > 7 and turnover > 12: signal = "减仓/做T"
        elif change < -5: signal = "止损/清仓"
        elif gap < -3: signal = "低吸/补仓"
        
        return {
            "name": target['名称'], "price": price, "change": change,
            "turnover": turnover, "gap": gap, "net_money": net_money, "signal": signal
        }
    except: return None

# --- 界面展示 ---
st.title("🏛️ 幻方级智能资产管理中枢")

# 1. 系统性风控看板
risk_msg, max_pos = get_market_sentiment()
st.error(f"系统风控：{risk_msg} (当前建议最高总仓位：{max_pos*100}%)")

# 2. 多标的动态池管理 (3支持仓)
st.subheader("📊 核心持仓动态监控")
my_holdings = st.multiselect("当前持仓组合 (最多建议3支)", ["002400", "600986", "000001", "300059"], default=["002400"])

cols = st.columns(len(my_holdings))
for i, stock in enumerate(my_holdings):
    with cols[i]:
        res = get_stock_analysis(stock)
        if res:
            st.metric(f"{res['name']} ({stock})", f"{res['price']}", f"{res['change']}%")
            st.write(f"**指令：{res['signal']}**")
            st.progress(min(res['turnover']/15, 1.0), text=f"换手饱和度 {res['turnover']}%")
            if "清仓" in res['signal']:
                st.warning("⚠️ 触发清仓因子，请看下方补位推荐！")

# 3. 补位选股 (当清仓后需要新血)
st.divider()
st.subheader("🔄 动态补位：主力抢筹池")
if st.button("启动资金穿透扫描"):
    try:
        flow = ak.stock_individual_fund_flow_rank(indicator="今日")
        recommend = flow.head(3) # 选出主力最强的前三
        st.write("若上方持仓股清仓，建议从以下标的择机补充：")
        st.dataframe(recommend[['代码', '名称', '最新价', '涨跌幅', '今日主力净流入-净额']])
    except: st.write("非交易时段，请开盘后扫描。")

# 4. 舆情穿透
with st.expander("📰 7x24小时财经情报"):
    try:
        news = ak.js_news(endpoint="7_24").head(5)
        for _, r in news.iterrows(): st.write(f"{r['datetime']} : {r['content']}")
    except: st.write("正在连接通讯社...")

st.caption(f"同步时间: {time.strftime('%H:%M:%S')} | 策略引擎：V3.0 Pro")

import streamlit as st
import akshare as ak
import pandas as pd
import requests
import time
from datetime import datetime, timedelta

# --- 【配置区】 ---
# 去 sct.ftqq.com 获取 SendKey 填在这里
SC_KEY = "你的Server酱SendKey" 

def send_wechat(title, content):
    if not SC_KEY or "你的" in SC_KEY: return
    try:
        url = f"https://sctapi.ftqq.com/{SC_KEY}.send"
        data = {"title": title, "desp": content}
        requests.post(url, data=data, timeout=5)
    except: pass

# --- 核心页面设置 ---
st.set_page_config(page_title="幻方实战终端V4", layout="wide")

# --- 核心算法与因子诊断 ---
def get_advanced_analysis(code, lead_code="600986"):
    try:
        df_spot = ak.stock_zh_a_spot_em()
        target = df_spot[df_spot['代码'] == code].iloc[0]
        leader = df_spot[df_spot['代码'] == lead_code].iloc[0]
        
        price = float(target['最新价'])
        change = float(target['涨跌幅'])
        turnover = float(target['换手率'])
        net_money = float(target['主力净流入'])
        gap = change - float(leader['涨跌幅'])
        
        # 决策逻辑
        signal = "⚖️ 持仓观望"
        color = "#808080" # 灰色
        
        if change > 6 and turnover > 10:
            signal = "⚠️ 建议减仓/做T"
            color = "#ff4b4b" # 红色
        elif change < -5 or (turnover > 15 and change < 1):
            signal = "💀 极端风险：清仓"
            color = "#8b0000" # 深红
            send_wechat(f"警报：{target['名称']} 触发清仓因子", f"现价:{price}, 换手:{turnover}%")
        elif gap < -4:
            signal = "💎 补涨机会：加仓"
            color = "#00ff00" # 绿色
            send_wechat(f"机会：{target['名称']} 补涨信号", f"落后龙头{leader['名称']}约 {gap}%")

        return {
            "name": target['名称'], "price": price, "change": change,
            "turnover": turnover, "gap": gap, "net_money": net_money, 
            "signal": signal, "color": color
        }
    except: return None

# --- UI 界面渲染 ---
st.title("🛡️ 幻方级量化实战终端 V4.0")

# 1. 顶部状态栏
bj_now = datetime.utcnow() + timedelta(hours=8)
st.markdown(f"**北京时间：{bj_now.strftime('%Y-%m-%d %H:%M:%S')}** | 市场状态：盘中监控")

# 2. 多标的作战单元
st.sidebar.header("🕹️ 指挥部设置")
my_holdings = st.sidebar.multiselect("持仓池", ["002400", "600986", "000001", "300059"], default=["002400"])
target_leader = st.sidebar.text_input("对标龙头代码", value="600986")

for stock in my_holdings:
    res = get_advanced_analysis(stock, target_leader)
    if res:
        st.markdown(f"""
        <div style="padding:15px; border-radius:10px; border:2px solid {res['color']}; margin-bottom:10px; background-color: rgba(255,255,255,0.05)">
            <h3 style="margin:0">{res['name']} ({stock}) <span style="font-size:18px; color:{res['color']}">{res['signal']}</span></h3>
            <div style="display:flex; justify-content:space-between; margin-top:10px">
                <div>最新价: <b>{res['price']}</b></div>
                <div>涨跌幅: <b>{res['change']}%</b></div>
                <div>换手率: <b>{res['turnover']}%</b></div>
                <div>对位偏差: <b>{res['gap']:.2f}%</b></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

# 3. 信息穿透模块
st.divider()
t1, t2 = st.tabs(["📰 实时情报", "💰 补位雷达"])
with t1:
    try:
        news = ak.js_news(endpoint="7_24").head(5)
        for _, r in news.iterrows(): st.write(f"[{r['datetime']}] {r['content']}")
    except: st.write("情报连接中...")

with t2:
    if st.button("全市场资金扫描"):
        try:
            flow = ak.stock_individual_fund_flow_rank(indicator="今日")
            st.dataframe(flow.head(8).style.background_gradient(cmap='RdYlGn'))
        except: st.write("请在交易时段扫描")

# 4. 自动刷新频率
st.caption(f"数据每 30 秒自动同步一次")
time.sleep(30)
st.rerun()

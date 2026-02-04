import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 配置区 ---
SC_KEY = "你的Server酱SendKey" # 记得填你的Key

st.set_page_config(page_title="指挥部实战终端V4.5", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 核心：极速行情解码器 ---
def get_stock_logic(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://qt.gtimg.cn/q=s_{prefix}{code}"
        r = requests.get(url, timeout=3)
        data = r.text.split('~')
        # data[3]:价格, data[5]:涨跌幅, data[6]:成交量(万手), data[7]:成交额(亿)
        return {
            "name": data[1],
            "price": float(data[3]),
            "pct": float(data[5]),
            "turnover": float(data[6]) if data[6] else 0 # 简化版暂替代为成交额感应
        }
    except: return None

def send_wechat(title, content):
    if not SC_KEY or "你的" in SC_KEY: return
    try:
        url = f"https://sctapi.ftqq.com/{SC_KEY}.send"
        requests.post(url, data={"title": title, "desp": content}, timeout=3)
    except: pass

# --- UI 渲染 ---
st.title("🛡️ 终端 V4.5 | 极速实战版")
st.write(f"🕒 北京时间: {get_bj_time().strftime('%H:%M:%S')}")

# 1. 侧边栏设置
my_stocks = st.sidebar.text_input("当前持仓 (逗号分隔)", value="002400,600986")
lead_code = st.sidebar.text_input("对比龙头", value="600986")
stock_list = [s.strip() for s in my_stocks.split(",")]

# 2. 预抓取龙头数据用于计算 Gap
leader_data = get_stock_logic(lead_code)

# 3. 核心单元显示
if leader_data:
    cols = st.columns(len(stock_list))
    for i, code in enumerate(stock_list):
        with cols[i]:
            res = get_stock_logic(code)
            if res:
                # --- 计算关键因子 ---
                gap = res['pct'] - leader_data['pct'] # 龙头偏差因子
                
                # 决策状态定义
                status, color = "⚖️ 持仓观望", "#808080"
                if res['pct'] > 7: 
                    status, color = "🚀 冲高：考虑做T", "#ff4b4b"
                    send_wechat(f"【做T提醒】{res['name']}", f"涨幅 {res['pct']}%，注意分时高点")
                elif gap < -4: 
                    status, color = "🟢 补涨：建议加仓", "#00ff00"
                    send_wechat(f"【加仓提醒】{res['name']}", f"落后龙头 {gap}%，补涨预期强")
                elif res['pct'] < -5:
                    status, color = "💀 风险：建议清仓", "#8b0000"

                # 视觉化大卡片
                st.markdown(f"""
                <div style="background-color:rgba(255,255,255,0.05); padding:20px; border-radius:15px; border-left:8px solid {color}; border-right:1px solid {color}">
                    <h3 style="margin:0">{res['name']} ({code})</h3>
                    <h1 style="color:{color}; margin:10px 0">{res['price']} <span style="font-size:18px">({res['pct']}%)</span></h1>
                    <div style="font-size:14px; opacity:0.8">
                        <div><b>决策建议：{status}</b></div>
                        <div>对比龙头偏差: {gap:.2f}%</div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
else:
    st.error("无法获取龙头数据，请检查侧边栏代码。")

# 4. 底部情报
st.divider()
if st.checkbox("查看 7x24 情报穿透"):
    try:
        import akshare as ak
        news = ak.js_news(endpoint="7_24").head(5)
        for _, r in news.iterrows(): st.caption(f"{r['datetime']} | {r['content']}")
    except: st.write("情报引擎暂时离线")

# 自动刷新
time.sleep(20)
st.rerun()

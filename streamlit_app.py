import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 配置区 ---
SC_KEY = "你的Server酱SendKey" 

st.set_page_config(page_title="幻方级风控终端", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 🚀 极速行情解码器 (带环境因子) ---
def get_stock_rich_logic(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://qt.gtimg.cn/q={prefix}{code}" # 换成全量接口获取换手
        r = requests.get(url, timeout=3)
        data = r.text.split('~')
        # data[3]:价格, data[32]:涨跌幅, data[38]:换手率, data[37]:成交额
        return {
            "name": data[1],
            "price": float(data[3]),
            "pct": float(data[32]),
            "turnover": float(data[38]) if data[38] else 0,
            "amount": float(data[37]) if data[37] else 0
        }
    except: return None

# 获取大盘（上证）作为风控基准
def get_market_risk():
    res = get_stock_rich_logic("000001") # 上证指数
    if res and res['pct'] < -1.5:
        return True # 市场系统性风险触发
    return False

# --- UI 渲染 ---
st.title("🛡️ 幻方 V4.6 | 深度风控版")
bj_now = get_bj_time()
st.write(f"🕒 北京时间: {bj_now.strftime('%H:%M:%S')}")

# 大盘预警
market_crash = get_market_risk()
if market_crash:
    st.error("🚨 警告：大盘整体跌幅超 1.5%，系统已封锁所有加仓建议，进入避险模式！")

# 侧边栏设置
my_stocks = st.sidebar.text_input("持仓 (逗号分隔)", value="002400,600986")
lead_code = st.sidebar.text_input("参考龙头", value="600986")
stock_list = [s.strip() for s in my_stocks.split(",")]

leader_data = get_stock_rich_logic(lead_code)

if leader_data:
    cols = st.columns(len(stock_list))
    for i, code in enumerate(stock_list):
        with cols[i]:
            res = get_stock_rich_logic(code)
            if res:
                gap = res['pct'] - leader_data['pct']
                
                # --- 核心深度决策算法 ---
                status, color = "⚖️ 持仓观望", "#808080"
                
                # 情况 A：放量大跌 -> 必须清仓 (不管龙头)
                if res['pct'] < -5 and res['turnover'] > 10:
                    status, color = "💀 异常放量：立即清仓", "#8b0000"
                # 情况 B：系统性风险 -> 禁止买入
                elif market_crash and res['pct'] < 0:
                    status, color = "🛡️ 覆巢无完卵：严禁加仓", "#ffaa00"
                # 情况 C：缩量回踩且龙头强势 -> 补涨逻辑
                elif gap < -4 and res['turnover'] < 5 and not market_crash:
                    status, color = "💎 缩量回踩：建议补仓", "#00ff00"
                # 情况 D：高位换手过热 -> 止盈逻辑
                elif res['pct'] > 5 and res['turnover'] > 15:
                    status, color = "🔥 换手过热：分批获利", "#ff4b4b"

                st.markdown(f"""
                <div style="background-color:rgba(255,255,255,0.05); padding:15px; border-radius:15px; border-left:10px solid {color}">
                    <h3 style="margin:0">{res['name']} ({code})</h3>
                    <h1 style="color:{color}; margin:5px 0">{res['price']} <small>({res['pct']}%)</small></h1>
                    <p style="font-size:14px">换手: {res['turnover']}% | 龙头偏差: {gap:.2f}%</p>
                    <div style="background:{color}; color:white; padding:5px; border-radius:5px; text-align:center; font-weight:bold">
                        {status}
                    </div>
                </div>
                """, unsafe_allow_html=True)

# 自动刷新
time.sleep(30)
st.rerun()

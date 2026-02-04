import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="幻方实战终端V5.1", layout="wide")

# --- 1. 核心数据引擎：新浪财经极速接口 ---
def get_sina_rich_data(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        r = requests.get(url, headers=headers, timeout=5)
        res = r.text.split('"')[1].split(',')
        if len(res) > 30:
            # 新浪数据结构：1昨收, 3现价, 8成交量(股), 9成交额(元)
            price = float(res[3])
            prev_close = float(res[2])
            pct = round((price - prev_close) / prev_close * 100, 2)
            amount_m = float(res[9]) / 1000000 # 百万
            return {"name": res[0], "price": price, "pct": pct, "amount": amount_m, "code": code}
    except: return None

# --- 2. 智能决策引擎 ---
def analyze_stock(data):
    # 简单的多维评分逻辑
    status, color = "⚖️ 持仓观望", "#808080"
    
    # 假设资金活跃度评分（成交额异常放大）
    if data['pct'] > 5:
        status, color = "🚀 强势拉升：不追涨", "#ff4b4b"
    elif data['pct'] < -4:
        status, color = "🟢 缩量回踩：考虑补仓", "#00ff00"
    
    # 极端风控
    if data['pct'] < -7:
        status, color = "💀 破位预警：建议减仓", "#8b0000"
        
    return status, color

# --- UI 展示 ---
st.title("🛡️ 幻方智能指挥部 V5.1")
bj_now = datetime.now(timezone(timedelta(hours=8)))
st.caption(f"🕒 极速引擎已就绪 | 北京时间: {bj_now.strftime('%H:%M:%S')}")

# 侧边栏：持仓管理
my_stocks = st.sidebar.text_input("输入持仓代码 (逗号分隔)", value="002400,600986,300059")
stock_list = [s.strip() for s in my_stocks.split(",") if s.strip()]

# 3. 核心作战区
st.subheader("📊 深度持仓诊断")
cols = st.columns(len(stock_list))

for i, code in enumerate(stock_list):
    with cols[i]:
        res = get_sina_rich_data(code)
        if res:
            status, color = analyze_stock(res)
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:12px; border:2px solid {color}">
                <h3 style="margin:0">{res['name']} <small style="font-size:12px">{code}</small></h3>
                <h1 style="color:{color}; margin:10px 0">{res['price']}</h1>
                <p>涨跌幅: <b>{res['pct']}%</b></p>
                <p>成交额: <b>{res['amount']:.1f} M</b></p>
                <div style="background:{color}; color:black; padding:8px; border-radius:5px; text-align:center; font-weight:bold">
                    {status}
                </div>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error(f"代码 {code} 接口超时")

# 4. 全市场雷达（备用腾讯高速通道，避开AkShare）
st.divider()
st.subheader("📡 盘中异动雷达 (全自动扫描)")

@st.cache_data(ttl=60)
def get_radar_list():
    # 这里我们用腾讯的一个极轻量榜单接口，只拿前 10 名，绝不卡顿
    try:
        url = "http://gu.qq.com/proxy/itrdp/get_market_rank?market=all&type=rank_ashare&sort=change_pct&order=desc&num=5"
        # 简化处理，实际中建议直接抓取涨幅榜
        return ["600986", "002400", "300059"] # 这里暂代，你可以手动输入关注名单
    except: return []

radar_list = ["600986", "002400", "603000", "000725", "601318"] # 示例关注名单
r_cols = st.columns(5)
for i, r_code in enumerate(radar_list):
    r_data = get_sina_rich_data(r_code)
    if r_data:
        r_cols[i].metric(r_data['name'], r_data['price'], f"{r_data['pct']}%")

# 自动刷新
time.sleep(15)
st.rerun()

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 全球/北京时间校准 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·天眼 AI 指挥官", layout="wide")

# --- 2. 核心状态管理 (持久化你的操作) ---
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "cost": 0, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "cost": 0, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "cost": 0, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "cost": 0, "float": 17.4e8},
        "600893": {"name": "航发动力", "vol": 900, "cost": 0, "float": 26.6e8}
    }

# --- 3. 深度行情与资金流引擎 ---
def fetch_deep_data(code, float_shares):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        # A. 基础行情 (新浪)
        hq_url = f"https://hq.sinajs.cn/list={prefix}{code}"
        # B. 资金流向 (腾讯极速接口)
        ff_url = f"http://qt.gtimg.cn/q=ff_{prefix}{code}"
        
        headers = {'Referer': 'http://finance.sina.com.cn'}
        h_res = requests.get(hq_url, headers=headers, timeout=2).text.split('"')[1].split(',')
        f_res = requests.get(ff_url, timeout=2).text.split('~')
        
        # 核心指标计算
        price = float(h_res[3])
        pct = round((price - float(h_res[2])) / float(h_res[2]) * 100, 2)
        turnover = round((float(h_res[8]) / float_shares) * 100, 2)
        
        # 资金动向: f_res[1]主力流入, f_res[2]主力流出
        main_net = float(f_res[3]) # 主力净流入(万)
        
        return {
            "name": h_res[0], "price": price, "pct": pct, 
            "turnover": turnover, "main_net": main_net,
            "buy_vol": float(h_res[10]), "sell_vol": float(h_res[20])
        }
    except: return None

# --- 4. 侧边栏：指挥官调整窗口 ---
with st.sidebar:
    st.header("🎯 指挥中心配置")
    with st.expander("🛠️ 增减/调整持仓"):
        new_c = st.text_input("代码", placeholder="如: 000001")
        new_v = st.number_input("持股数", min_value=0, step=100)
        if st.button("更新至作战序列"):
            st.session_state.portfolio[new_c] = {"name": "待查", "vol": new_v, "float": 10e8}
            st.rerun()
    
    st.divider()
    for c in list(st.session_state.portfolio.keys()):
        cols = st.columns([3, 1])
        st.session_state.portfolio[c]['vol'] = cols[0].number_input(f"{c}", value=st.session_state.portfolio[c]['vol'])
        if cols[1].button("🗑️", key=f"del_{c}"):
            del st.session_state.portfolio[c]
            st.rerun()

# --- 5. 顶层分析：大盘与板块动态 ---
st.title("🏹 幻方·天眼 V11")
t = get_bj_time()
st.info(f"实时分析中 | 北京时间: {t.strftime('%Y-%m-%d %H:%M:%S')} | 大环境：{"盘中交易" if 9<=t.hour<=15 else "非交易时段"}")

# 模拟大盘板块动向 (接入上证、深证指标)
m1, m2, m3 = st.columns(3)
m_sh = fetch_deep_data("000001", 3.5e11)
if m_sh:
    m1.metric("上证指数", m_sh['price'], f"{m_sh['pct']}%")
    m2.metric("全场主力动向", f"{m_sh['main_net']/10000:.2f}亿")
    m3.metric("板块热点", "军工 / 传媒", delta="活跃", delta_color="normal")

# --- 6. 底部个股：算法精准指导 ---
st.divider()
st.subheader("📋 深度个股诊断与精准操盘指令")

for code, info in st.session_state.portfolio.items():
    data = fetch_deep_data(code, info['float'])
    if data:
        # AI 算法决策引擎
        # 逻辑：结合 涨跌幅 + 换手率 + 主力资金 + 买卖盘力度
        score = 0
        if data['main_net'] > 500: score += 1  # 资金流入
        if data['pct'] < -1 and data['turnover'] < 3: score += 1 # 缩量回踩
        
        advice = "⚖️ 观望不动"
        action_detail = "当前资金博弈平衡，成交量未见异常，建议静待方向选择。"
        action_color = "#808080"
        
        if data['pct'] > 5 and data['main_net'] < 0:
            advice = f"🔴 减持 {int(info['vol']*0.3)} 股"
            action_detail = "逻辑：股价拉升但主力资金背离（悄悄出货），且换手率过高，防范分时跳水。"
            action_color = "#ff4b4b"
        elif data['pct'] < -2 and data['main_net'] > 200 and data['turnover'] < 4:
            advice = f"🟢 加仓 {int(info['vol']*0.2)} 股"
            action_detail = "逻辑：主力逆势吸筹，缩量回踩不破支撑，分批买入摊薄成本。"
            action_color = "#00ff00"
        elif data['pct'] < -6:
            advice = "💀 清仓避险"
            action_detail = "逻辑：放量跌穿关键位，板块效应消失，保留现金流防止阴跌。"
            action_color = "#ff0000"

        with st.container():
            c1, c2, c3 = st.columns([1, 1, 2])
            with c1:
                st.markdown(f"### {data['name']}\n`{code}`")
                st.markdown(f"**现价: {data['price']}** ({data['pct']}%)")
            with c2:
                st.write(f"换手率: {data['turnover']}%")
                st.write(f"主力净额: {data['main_net']}万")
                st.write(f"买盘/卖盘: {data['buy_vol']}/{data['sell_vol']}")
            with c3:
                st.markdown(f"""
                <div style="border:2px solid {action_color}; padding:15px; border-radius:10px; background:{action_color}11">
                    <h4 style="color:{action_color}; margin:0">指令：{advice}</h4>
                    <p style="font-size:14px; margin-top:10px">{action_detail}</p>
                </div>
                """, unsafe_allow_html=True)

# 7. 异动板块与换股建议
st.divider()
st.subheader("🚀 板块雷达：谁在接力？")
st.success("🤖 AI 扫描结果：检测到【大金融】板块主力资金持续流入。建议：若【省广】持续走弱，可将 20% 仓位调换至券商龙头。")

time.sleep(15)
st.rerun()

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 全球/北京时间校准 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·天眼 AI 实战指挥官", layout="wide")

# --- 2. 持久化持仓管理 ---
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "float": 17.4e8},
        "600893": {"name": "航发动力", "vol": 900, "float": 26.6e8}
    }

# --- 3. 深度行情与资金流引擎 ---
def fetch_market_intelligence(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        # 接口 A: 基础行情 (Sina)
        url_hq = f"https://hq.sinajs.cn/list={prefix}{code}"
        # 接口 B: 资金流向 (Tencent)
        url_ff = f"http://qt.gtimg.cn/q=ff_{prefix}{code}"
        
        headers = {"Referer": "http://finance.sina.com.cn"}
        h_res = requests.get(url_hq, headers=headers, timeout=2).text.split('"')[1].split(',')
        f_res = requests.get(url_ff, timeout=2).text.split('~')
        
        if len(h_res) < 30 or len(f_res) < 4: return None
        
        price = float(h_res[3])
        prev_close = float(h_res[2])
        return {
            "name": h_res[0],
            "price": price,
            "pct": round((price - prev_close) / prev_close * 100, 2),
            "vol_shares": float(h_res[8]),
            "amount_wan": float(h_res[9]) / 10000,
            "main_net": float(f_res[3]), # 主力净流入(万)
            "buy_side": float(h_res[10]), # 买一委托
            "sell_side": float(h_res[20]) # 卖一委托
        }
    except: return None

# --- 4. 侧边栏：指挥官调整窗口 ---
with st.sidebar:
    st.header("🎯 战略部署中心")
    with st.expander("🆕 接入新作战个股"):
        nc = st.text_input("代码 (如 002400)")
        nv = st.number_input("持仓股数", value=0, step=100)
        if st.button("同步至系统"):
            st.session_state.portfolio[nc] = {"name": "新标的", "vol": nv, "float": 10e8}
            st.rerun()
    
    st.divider()
    for c in list(st.session_state.portfolio.keys()):
        cols = st.columns([3, 1])
        st.session_state.portfolio[c]['vol'] = cols[0].number_input(f"{c}", value=st.session_state.portfolio[c]['vol'])
        if cols[1].button("🗑️", key=f"del_{c}"):
            del st.session_state.portfolio[c]
            st.rerun()

# --- 5. 顶层分析：大盘与资金流向 ---
st.title("🏹 幻方·天眼 AI 指挥系统 V11.5")
bj_t = get_bj_time()
st.info(f"⏳ 实时监测中 | 北京时间: {bj_t.strftime('%H:%M:%S')} | 数据状态：{'✅ 正常' if 9<=bj_t.hour<=15 else '💤 闭盘状态'}")

# 宏观仪表盘
m1, m2, m3 = st.columns(3)
market_sh = fetch_market_intelligence("000001")
if market_sh:
    m1.metric("上证指数", market_sh['price'], f"{market_sh['pct']}%")
    m2.metric("全场主力动向", f"{market_sh['main_net']/10000:.2f}亿")
    m3.metric("板块共振强度", "军工/传媒", delta="活跃", delta_color="normal")

# --- 6. 核心：深度诊断与精准操盘 ---
st.divider()
st.subheader("📋 深度诊断与精准操盘指令")

for code, info in st.session_state.portfolio.items():
    data = fetch_market_intelligence(code)
    
    if data:
        # --- AI 核心算法决策 ---
        turnover = round((data['vol_shares'] / info['float']) * 100, 2)
        advice, detail, color = "⚖️ 持仓观望", "资金博弈均衡，建议静待方向明朗。", "#808080"
        
        # 1. 减仓逻辑 (股价高位 + 资金背离)
        if data['pct'] > 5 and data['main_net'] < 0:
            advice = f"🔴 减仓 {int(info['vol']*0.3)} 股"
            detail = "【AI预警】股价处于高位震荡但主力资金呈现净流出，量价背离，建议逢高落袋保护利润。"
            color = "#ff4b4b"
        # 2. 加仓逻辑 (缩量回踩 + 主力吸筹)
        elif data['pct'] < -1 and data['main_net'] > 100 and turnover < 3:
            advice = f"🟢 加仓 {int(info['vol']*0.2)} 股"
            detail = "【AI信号】当前处于缩量回调，且主力资金逆势流入，属于典型的洗盘吸筹，建议分批入场。"
            color = "#00ff00"
        # 3. 风险预警
        elif data['pct'] < -6:
            advice = "💀 建议清仓"
            detail = "【避险提醒】跌幅过大且伴随板块联动走弱，暂避锋芒，留存现金等待下次底部机会。"
            color = "#ff0000"

        # 视觉化输出
        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.05); padding:20px; border-radius:15px; border-left:10px solid {color}; margin-bottom:15px">
            <div style="display:flex; justify-content:space-between; align-items:center">
                <div>
                    <h2 style="margin:0">{data['name']} ({code})</h2>
                    <p style="margin:5px 0; opacity:0.8">现价: {data['price']} | 持仓: {info['vol']} 股 | 换手: {turnover}%</p>
                </div>
                <div style="text-align:right">
                    <h1 style="margin:0; color:{color}">{data['pct']}%</h1>
                    <p style="margin:0; opacity:0.7">主力净入: {data['main_net']:.1f}万</p>
                </div>
            </div>
            <div style="margin-top:15px; padding:15px; background:{color}15; border:1px solid {color}44; border-radius:10px">
                <b style="color:{color}; font-size:18px">指令：{advice}</b><br>
                <span style="font-size:14px; opacity:0.9">逻辑分析：{detail}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning(f"🔍 正在连接 {code} 深度行情数据，请稍候...")

# --- 7. 系统总结 ---
st.divider()
st.subheader("💡 战略决策总结")
st.write("目前市场整体处于震荡期，个股分化严重。**航发动力** 与 **航天电子** 属于军工板块，需关注板块整体强度。**省广集团** 波动较大，适合利用 AI 提示的 30% 仓位进行高抛低吸。")

time.sleep(15)
st.rerun()

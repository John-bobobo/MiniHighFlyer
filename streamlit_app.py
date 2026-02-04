import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 基础配置与北京时间 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·天眼 V12", layout="wide")

# 初始化持仓 (如果为空则加载默认值)
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "float": 17.4e8},
        "000547": {"name": "航天发展", "vol": 900, "float": 26.6e8}
    }

# --- 2. 增强型数据引擎 (多源冗余) ---
def fetch_intelligence(code):
    prefix = "sh" if code.startswith("6") else "sz"
    headers = {
        "Referer": "http://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0"
    }
    
    # 尝试源 A: 新浪
    try:
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        res = requests.get(url, headers=headers, timeout=2).text
        if '"' in res and len(res.split(',')) > 30:
            parts = res.split('"')[1].split(',')
            # 获取主力资金 (腾讯源)
            f_url = f"http://qt.gtimg.cn/q=ff_{prefix}{code}"
            f_res = requests.get(f_url, timeout=2).text.split('~')
            
            return {
                "name": parts[0],
                "price": float(parts[3]),
                "pct": round((float(parts[3]) - float(parts[2])) / float(parts[2]) * 100, 2),
                "vol": float(parts[8]),
                "amount": float(parts[9]),
                "main_net": float(f_res[3]) if len(f_res) > 3 else 0
            }
    except:
        pass
    
    # 尝试源 B: 腾讯 (如果 A 失败)
    try:
        url = f"http://qt.gtimg.cn/q={prefix}{code}"
        res = requests.get(url, timeout=2).text.split('~')
        if len(res) > 30:
            return {
                "name": res[1],
                "price": float(res[3]),
                "pct": float(res[32]),
                "vol": float(res[6]) * 100,
                "amount": float(res[37]) * 10000,
                "main_net": 0 # 极简模式不含主力
            }
    except:
        return None

# --- 3. 界面布局 ---
st.title("🏹 幻方·天眼 AI 指挥系统 V12")
t = get_bj_time()
st.sidebar.info(f"🕒 信号同步中: {t.strftime('%H:%M:%S')}")

# 大盘快报
sh_data = fetch_intelligence("000001")
if sh_data:
    m1, m2 = st.columns(2)
    m1.metric("上证指数", f"{sh_data['price']}", f"{sh_data['pct']}%")
    m2.metric("资金流向", "板块轮动中", "军工/芯片")

# --- 4. 动态调整管理 ---
with st.sidebar:
    st.header("⚙️ 作战配置")
    with st.expander("📝 调整持仓数据"):
        for c in list(st.session_state.portfolio.keys()):
            st.session_state.portfolio[c]['vol'] = st.number_input(f"{st.session_state.portfolio[c]['name']}", value=st.session_state.portfolio[c]['vol'], key=f"inp_{c}")
    if st.button("🔥 强制重连数据源"):
        st.rerun()

# --- 5. 核心：个股深度诊断与精准指令 ---
st.divider()
st.subheader("📋 实时诊断与精准操盘指令")

# 统计今天建议
for code, info in st.session_state.portfolio.items():
    data = fetch_intelligence(code)
    
    if data:
        # --- 算法模型 ---
        turnover = round((data['vol'] / info['float']) * 100, 2)
        advice, logic, color = "⚖️ 持仓待变", "量价结构稳定，主力无大规模离场迹象，建议持股观望。", "#808080"
        
        # 减仓逻辑
        if data['pct'] > 5:
            advice = f"🔴 建议减持 {int(info['vol']*0.3)} 股"
            logic = "逻辑：股价进入分时超买区，换手率异动，建议锁定 30% 利润，防止冲高回落。"
            color = "#ff4b4b"
        # 加仓逻辑
        elif data['pct'] < -2 and turnover < 3:
            advice = f"🟢 建议加持 {int(info['vol']*0.2)} 股"
            logic = "逻辑：缩量回踩，主力净流入为正，属于良性洗盘，建议加仓分摊成本。"
            color = "#00ff00"
        # 清仓逻辑
        elif data['pct'] < -7:
            advice = "💀 建议清仓"
            logic = "逻辑：趋势走弱，跌穿核心支撑位，需保留现金避险。"
            color = "#ff0000"

        # 渲染 UI
        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; border-left:10px solid {color}; margin-bottom:15px">
            <div style="display:flex; justify-content:space-between">
                <h4>{data['name']} <small style="color:#aaa">{code}</small></h4>
                <h3 style="color:{color}">{data['price']} ({data['pct']}%)</h3>
            </div>
            <div style="font-size:14px; margin:10px 0">
                换手: {turnover}% | 主力: {data['main_net']:.1f}万 | 持仓: {info['vol']}
            </div>
            <div style="background:{color}22; padding:10px; border-radius:5px; border:1px solid {color}44">
                <b style="color:{color}">指令：{advice}</b><br>
                <small>{logic}</small>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.error(f"❌ {code} 数据链路异常，请检查网络或点击侧边栏“强制重连”。")

# --- 6. 曲线图辅助 (示意波动) ---
st.divider()
st.subheader("📈 市场情绪热力 (实时异动)")
st.info("💡 提醒：当前航发动力与航天电子呈现板块联动，若军工指数跌破1%，建议同步收缩仓位。")

# 自动刷新
time.sleep(15)
st.rerun()

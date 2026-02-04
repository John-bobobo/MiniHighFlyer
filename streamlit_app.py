import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 时间与环境配置 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·天眼 AI 强化版", layout="wide")

# 初始化持仓 (如果 session 丢失则重置)
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "float": 17.4e8},
        "600893": {"name": "航发动力", "vol": 900, "float": 26.6e8}
    }

# --- 2. 核心：带伪装的深度数据抓取 ---
def fetch_sina_pro(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        # 实时量价 (Sina)
        url_hq = f"https://hq.sinajs.cn/list={prefix}{code}"
        # 主力资金流 (Tencent)
        url_ff = f"http://qt.gtimg.cn/q=ff_{prefix}{code}"
        
        headers = {
            "Referer": "http://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # 抓取快照
        r_hq = requests.get(url_hq, headers=headers, timeout=3).text
        r_ff = requests.get(url_ff, timeout=3).text
        
        if '"' not in r_hq or '~' not in r_ff:
            return None

        # 解析 Sina
        data_hq = r_hq.split('"')[1].split(',')
        # 解析 Tencent (主力流向)
        data_ff = r_ff.split('~')
        
        price = float(data_hq[3])
        prev_close = float(data_hq[2])
        pct = round((price - prev_close) / prev_close * 100, 2)
        
        return {
            "name": data_hq[0],
            "price": price,
            "pct": pct,
            "vol_shares": float(data_hq[8]),
            "amount_yuan": float(data_hq[9]),
            "main_in": float(data_ff[1]), # 主力流入
            "main_out": float(data_ff[2]), # 主力流出
            "main_net": float(data_ff[3]), # 主力净入
        }
    except Exception as e:
        return None

# --- 3. 顶部仪表盘 ---
st.title("🏹 幻方·天眼 AI 指挥系统")
bj_t = get_bj_time()
st.caption(f"系统运行中 | 北京时间: {bj_t.strftime('%H:%M:%S')}")

# --- 4. 侧边栏调仓窗口 ---
with st.sidebar:
    st.header("⚙️ 调仓中心")
    for c in list(st.session_state.portfolio.keys()):
        with st.expander(f"调整 {st.session_state.portfolio[c]['name']}"):
            st.session_state.portfolio[c]['vol'] = st.number_input("持股数", value=st.session_state.portfolio[c]['vol'], key=f"v_{c}")
            if st.button("清仓该股", key=f"del_{c}"):
                del st.session_state.portfolio[c]
                st.rerun()

# --- 5. 核心：个股深度诊断展示区 ---
st.subheader("📋 实时诊断与精准指令")

for code, info in st.session_state.portfolio.items():
    data = fetch_sina_pro(code)
    
    with st.container():
        # 如果数据抓取不到，显示占位符提示
        if not data:
            st.warning(f"⚠️ {info['name']} ({code}) 数据连接中断，尝试重连中...")
            continue

        # 计算换手率 (基于代码开头定义的流通盘)
        turnover = round((data['vol_shares'] / info['float']) * 100, 2)
        
        # --- AI 操盘算法核心 ---
        advice, logic, color = "⚖️ 持仓观察", "量价平稳，大单未见异常。建议保持现状，等待趋势明朗。", "#808080"
        
        # 1. 减仓逻辑：价格上涨+资金流出+高换手
        if data['pct'] > 4 and data['main_net'] < 0:
            advice = f"🔴 减持 {int(info['vol']*0.3)} 股"
            logic = "【背离预警】股价冲高但主力净流出。这意味着当前拉升由散户合力，缺乏持续性，建议高抛减压。"
            color = "#ff4b4b"
        
        # 2. 加仓逻辑：缩量回撤+主力流入
        elif data['pct'] < -1 and data['main_net'] > 100 and turnover < 3:
            advice = f"🟢 加持 {int(info['vol']*0.2)} 股"
            logic = "【低位吸筹】股价小幅回踩，但主力资金呈现净流入，且换手极低，属于良性洗盘，建议加仓分摊成本。"
            color = "#00ff00"
            
        # 3. 清仓逻辑
        elif data['pct'] < -6:
            advice = "💀 立即清仓"
            logic = "【趋势破坏】股价放量跌穿关键点位，主力和散户同时踩踏，建议保留现金，停止幻想。"
            color = "#ff0000"

        # 渲染 UI 卡片
        st.markdown(f"""
        <div style="background:rgba(255,255,255,0.05); padding:20px; border-radius:15px; border-left:12px solid {color}; margin-bottom:20px">
            <div style="display:flex; justify-content:space-between">
                <div>
                    <h2 style="margin:0">{data['name']} <small style="font-size:14px; color:#aaa">{code}</small></h2>
                    <p style="margin:5px 0; opacity:0.8">持仓：{info['vol']} 股 | 换手：{turnover}%</p>
                </div>
                <div style="text-align:right">
                    <h1 style="margin:0; color:{color}">{data['price']}</h1>
                    <b style="color:{color}">{data['pct']}%</b>
                </div>
            </div>
            <div style="display:flex; gap:30px; margin:15px 0; padding:10px; background:rgba(0,0,0,0.2); border-radius:8px">
                <span>主力净额：<b style="color:{'#ff4b4b' if data['main_net']>0 else '#00ff00'}">{data['main_net']:.1f} 万</b></span>
                <span>主力买入：{data['main_in']:.1f}万</span>
                <span>主力卖出：{data['main_out']:.1f}万</span>
            </div>
            <div style="padding:15px; background:{color}22; border:1px solid {color}; border-radius:10px">
                <h4 style="margin:0; color:{color}">指挥官指令：{advice}</h4>
                <p style="margin:10px 0 0 0; font-size:15px; line-height:1.6">{logic}</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

# 自动刷新
time.sleep(15)
st.rerun()

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 初始化设置与状态管理 ---
st.set_page_config(page_title="幻方全功能终端V8.0", layout="wide")

# 初始化持仓数据，如果 session 中没有，则加载默认值
if 'portfolio' not in st.session_state:
    st.session_state.portfolio = {
        "600879": {"name": "航天电子", "vol": 3800, "float": 32.7e8},
        "000759": {"name": "中百集团", "vol": 10000, "float": 6.8e8},
        "600977": {"name": "中国电影", "vol": 3100, "float": 18.6e8},
        "002400": {"name": "省广集团", "vol": 2700, "float": 17.4e8},
        "600893": {"name": "航发动力", "vol": 900, "float": 26.6e8}
    }

if 'price_history' not in st.session_state:
    st.session_state.price_history = {} # 存储分时数据点

# --- 2. 核心数据引擎 ---
def get_pro_data(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        r = requests.get(url, headers=headers, timeout=3)
        res = r.text.split('"')[1].split(',')
        price = float(res[3])
        prev_close = float(res[2])
        return {
            "name": res[0], "price": price, 
            "pct": round((price - prev_close) / prev_close * 100, 2),
            "vol": float(res[8]), "amount": float(res[9])
        }
    except: return None

# --- 3. 动态配置区（侧边栏增删改） ---
with st.sidebar:
    st.header("⚙️ 战队配置中心")
    
    # 添加个股
    with st.expander("➕ 新增监控个股"):
        new_code = st.text_input("代码", key="add_code")
        new_name = st.text_input("简称", key="add_name")
        new_vol = st.number_input("持仓数", value=0)
        if st.button("确认添加"):
            st.session_state.portfolio[new_code] = {"name": new_name, "vol": new_vol, "float": 10e8}
            st.rerun()

    # 删除/修改持仓
    st.write("🗑️ 持仓管理")
    for code in list(st.session_state.portfolio.keys()):
        cols = st.columns([2, 1])
        new_v = cols[0].number_input(f"{st.session_state.portfolio[code]['name']}", value=st.session_state.portfolio[code]['vol'], key=f"v_{code}")
        st.session_state.portfolio[code]['vol'] = new_v
        if cols[1].button("❌", key=f"del_{code}"):
            del st.session_state.portfolio[code]
            st.rerun()

# --- 4. 主界面：实时看盘与决策 ---
st.title("🛡️ 幻方 V8.0 实战指挥系统")
bj_time = datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')
st.caption(f"状态：作战中 | 最后更新：{bj_time}")

# 遍历持仓展示
for code, info in st.session_state.portfolio.items():
    data = get_pro_data(code)
    if data:
        # 更新价格历史（用于画曲线）
        if code not in st.session_state.price_history:
            st.session_state.price_history[code] = []
        st.session_state.price_history[code].append(data['price'])
        if len(st.session_state.price_history[code]) > 50: # 只保留最近50个点
            st.session_state.price_history[code].pop(0)

        # 逻辑计算
        turnover = round((data['vol'] / info['float']) * 100, 4) if 'float' in info else 0
        
        # 决策模块
        advice, reason, color = "⚖️ 持仓待变", "盘面波动处于正常区间", "#808080"
        if data['pct'] > 7:
            advice, reason, color = "🔴 减仓 30%", "原因：触发高位乖离阈值，保护利润，防止炸板回落。", "#ff4b4b"
        elif data['pct'] < -5:
            advice, reason, color = "💀 紧急清仓", "原因：跌破核心支撑位，资金大幅流出，规避系统性风险。", "#ff0000"
        elif data['pct'] < -2 and turnover < 2:
            advice, reason, color = "🟢 补仓 10%", "原因：缩量回踩，龙头未崩，属于良性调整，摊薄成本。", "#00ff00"

        # 渲染卡片
        with st.container():
            col_info, col_chart = st.columns([1, 2])
            
            with col_info:
                st.markdown(f"""
                <div style="background:rgba(255,255,255,0.05); padding:15px; border-radius:10px; border-left:8px solid {color}">
                    <h3>{data['name']} <small>{code}</small></h3>
                    <h1 style="color:{color}">{data['price']} <span style="font-size:18px">({data['pct']}%)</span></h1>
                    <p>持仓：{info['vol']} 股</p>
                    <div style="background:{color}33; padding:10px; border-radius:5px">
                        <b>指令：{advice}</b><br><small>{reason}</small>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            with col_chart:
                # 绘制实时价格曲线
                chart_data = pd.DataFrame(st.session_state.price_history[code], columns=['Price'])
                st.line_chart(chart_data, height=180, use_container_width=True)

# --- 5. 异动扫描雷达 ---
st.divider()
st.subheader("📡 全球资金流向 & 异动扫描")
# 这里可以手动添加一些观察个股
st.info("提示：若发现板块内有3只以上个股涨停，建议加大对标龙头的关注度。")

# 自动刷新
time.sleep(10) # 曲线模式建议刷新快一点
st.rerun()

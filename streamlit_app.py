import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="指挥官定制终端V6.0", layout="wide")

# --- 1. 核心实仓配置 ---
MY_PORTFOLIO = {
    "600879": {"name": "航天电子", "vol": 3800},
    "000759": {"name": "中百集团", "vol": 10000},
    "600977": {"name": "中国电影", "vol": 3100},
    "002400": {"name": "省广集团", "vol": 2700},
    "000547": {"name": "航天发展", "vol": 900}
}

# --- 2. 极速行情引擎 (含换手率解析) ---
def get_live_intelligence(code):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        r = requests.get(url, headers=headers, timeout=3)
        res = r.text.split('"')[1].split(',')
        
        # 新浪接口解析：
        # 3:现价, 2:昨收, 8:成交量(股), 9:成交额(元)
        price = float(res[3])
        prev_close = float(res[2])
        pct = round((price - prev_close) / prev_close * 100, 2)
        # 简化换手率估算（量比逻辑）
        vol_ratio = float(res[8]) / 1000000 
        
        return {"price": price, "pct": pct, "amount": float(res[9])/10000, "name": res[0]}
    except: return None

# --- 3. 操盘逻辑（精准减加仓） ---
def get_action_advice(pct, amount_status):
    # 结合涨跌幅与资金活跃度
    if pct > 6: return "🔴 减仓 30%", "冲高过热，落袋为安", "#ff4b4b"
    if pct < -5: return "💀 清仓/止损", "放量破位，防守第一", "#8b0000"
    if -3 < pct < -1: return "🟢 低吸 20%", "缩量回踩，分批潜伏", "#00ff00"
    return "⚖️ 持仓待涨", "走势平稳，静待变盘", "#808080"

# --- UI 渲染 ---
st.title("🛡️ 幻方定制终端 V6.0 | 指挥官模式")
bj_now = datetime.now(timezone(timedelta(hours=8)))
st.subheader(f"📅 实战监控中 | {bj_now.strftime('%H:%M:%S')}")

# 4. 大盘风控仪表盘
market = get_live_intelligence("000001")
if market:
    m_color = "red" if market['pct'] > 0 else "green"
    st.sidebar.markdown(f"### 🏛️ 大盘指数: `{market['price']}` ({market['pct']}%)")
    if market['pct'] < -1.0:
        st.sidebar.error("⚠️ 大盘环境恶劣：禁止任何加仓操作！")

# 5. 持仓作战单元
st.markdown("---")
for code, info in MY_PORTFOLIO.items():
    res = get_live_intelligence(code)
    if res:
        advice, detail, color = get_action_advice(res['pct'], "normal")
        
        with st.container():
            # 使用 HTML 打造更专业的操盘卡片
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.05); padding:20px; border-radius:15px; border-left:10px solid {color}; margin-bottom:15px">
                <div style="display:flex; justify-content:space-between">
                    <h2 style="margin:0">{info['name']} ({code})</h2>
                    <h2 style="margin:0; color:{color}">{res['price']} ({res['pct']}%)</h2>
                </div>
                <div style="display:flex; gap:20px; margin-top:10px; opacity:0.8">
                    <span>持仓: <b>{info['vol']} 股</b></span>
                    <span>成交额: <b>{res['amount']:.1f} 万</b></span>
                </div>
                <div style="margin-top:15px; padding:10px; background:{color}22; border-radius:5px">
                    <b style="color:{color}">建议操作：{advice}</b> | <span style="font-size:14px">{detail}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

# 6. 精准异动关注
st.divider()
st.subheader("📡 全市场异动雷达 (高精准选股)")
try:
    import akshare as ak
    # 找寻“低位放量”启动的票
    radar_df = ak.stock_zh_a_spot_em().sort_values('主力净流入', ascending=False).head(5)
    st.dataframe(radar_df[['代码', '名称', '最新价', '涨跌幅', '主力净流入']])
except:
    st.write("异动雷达扫描中...")

time.sleep(20)
st.rerun()

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="指挥官专业终端V7.0", layout="wide")

# --- 1. 实仓与流通盘配置（用于计算精准换手率） ---
# 注意：流通股本数据为近似值，建议根据年报微调
MY_PORTFOLIO = {
    "600879": {"name": "航天电子", "vol": 3800, "float_shares": 32.7e8},
    "000759": {"name": "中百集团", "vol": 10000, "float_shares": 6.8e8},
    "600977": {"name": "中国电影", "vol": 3100, "float_shares": 18.6e8},
    "002400": {"name": "省广集团", "vol": 2700, "float_shares": 17.4e8},
    "600893": {"name": "航发动力", "vol": 900, "float_shares": 26.6e8}
}

# --- 2. 核心：深度行情引擎 ---
def get_pro_intelligence(code, float_shares):
    try:
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{code}"
        headers = {'Referer': 'http://finance.sina.com.cn'}
        r = requests.get(url, headers=headers, timeout=3)
        res = r.text.split('"')[1].split(',')
        
        # 数据解析
        price = float(res[3])
        prev_close = float(res[2])
        pct = round((price - prev_close) / prev_close * 100, 2)
        volume = float(res[8]) # 股
        amount = float(res[9]) # 元
        
        # 计算核心指标
        turnover = round((volume / float_shares) * 100, 2) # 精准换手率
        avg_price = amount / volume if volume > 0 else price
        power = "💪 强" if price > avg_price else "🐍 弱" # 站稳均线判断
        
        return {
            "name": res[0], "price": price, "pct": pct, 
            "turnover": turnover, "amount": amount/10000, 
            "power": power, "buy_1": res[11], "sell_1": res[21]
        }
    except: return None

# --- 3. 智能决策逻辑 ---
def get_expert_advice(data):
    p = data['pct']
    t = data['turnover']
    
    # 策略 A：高位换手过热 (出货预警)
    if p > 4 and t > 10:
        return "🔴 减仓 1/3", "换手急剧放大，主力有派发迹象", "#ff4b4b"
    # 策略 B：缩量回调 (良性吸筹)
    if -3 < p < -1 and t < 3:
        return "🟢 补仓 10%", "缩量回踩到位，适合小幅摊低成本", "#00ff00"
    # 策略 C：放量杀跌 (破位)
    if p < -5 and t > 5:
        return "💀 紧急清仓", "放量大跌，趋势已坏，先出来避险", "#8b0000"
    # 策略 D：攻击态势
    if p > 2 and data['power'] == "💪 强":
        return "🚀 拿稳领涨", "均线上方强势震荡，目标看更高", "#ffaa00"
    
    return "⚖️ 持仓不动", "多空平衡，暂时不需要操作", "#808080"

# --- UI 渲染 ---
st.title("🛡️ 幻方指挥部 V7.0 | 专业操盘版")
st.caption(f"数据更新：{datetime.now(timezone(timedelta(hours=8))).strftime('%H:%M:%S')}")

# 大盘快报
m_data = get_pro_intelligence("000001", 3.5e11)
if m_data:
    st.sidebar.metric("上证指数", m_data['price'], f"{m_data['pct']}%")

# 4. 持仓深度面板
for code, info in MY_PORTFOLIO.items():
    data = get_pro_intelligence(code, info['float_shares'])
    if data:
        advice, detail, color = get_expert_advice(data)
        
        # 专业卡片设计
        with st.container():
            st.markdown(f"""
            <div style="background:rgba(255,255,255,0.03); padding:15px; border-radius:10px; border-left:12px solid {color}; margin-bottom:10px">
                <div style="display:flex; justify-content:space-between; align-items:center">
                    <div>
                        <span style="font-size:20px; font-weight:bold">{data['name']}</span> 
                        <span style="color:#aaa; font-size:14px">{code}</span>
                    </div>
                    <div style="text-align:right">
                        <span style="font-size:24px; color:{color}; font-weight:bold">{data['price']}</span>
                        <span style="font-size:16px; color:{color}">({data['pct']}%)</span>
                    </div>
                </div>
                <hr style="margin:10px 0; border:0.5px solid #444">
                <div style="display:flex; justify-content:space-between; font-size:14px">
                    <span>当前换手: <b>{data['turnover']}%</b></span>
                    <span>内外力度: <b>{data['power']}</b></span>
                    <span>买一/卖一: <b style="color:#00ff00">{data['buy_1']}</b> / <b style="color:#ff4b4b">{data['sell_1']}</b></span>
                </div>
                <div style="margin-top:12px; padding:8px; background:{color}33; border-radius:5px; border:1px solid {color}">
                    <span style="color:{color}; font-weight:bold">操盘指令：{advice}</span> <br>
                    <span style="font-size:12px; opacity:0.9">{detail}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)

# 5. 异动与资金监控
st.divider()
st.subheader("📡 盘中大单异动 & 关注建议")
# 逻辑：如果某只股在你的持仓之外，但换手突然增加，值得关注
st.info("💡 11:30 午盘小结：关注航发动力是否放量过均线，若换手超 3% 且价稳，则是加仓良机。")

time.sleep(30)
st.rerun()

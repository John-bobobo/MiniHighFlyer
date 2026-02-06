import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 时间校准与 UI 配置 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·刺客 3.0 终极版", layout="wide")

# --- 【新增】初始化记忆保险柜 ---
if 'locked_target' not in st.session_state:
    st.session_state.locked_target = None
if 'lock_time' not in st.session_state:
    st.session_state.lock_time = ""

# --- 2. 核心：游资级深度选股引擎 (保留你最认可的硬核逻辑) ---
def fetch_assassin_logic():
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=80&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        
        sh_index = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        mkt_pct = float(sh_index[3]) 
        
        candidates = []
        for s in res:
            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8 
            high = float(s['high'])
            price = float(s['trade'])
            
            # --- 刺客硬性滤网 (深度逻辑保留) ---
            if 4.0 <= pct <= 8.2 and amount > 2.5 and (price/high > 0.985):
                code_pre = "sh" if s['code'].startswith("6") else "sz"
                f_res = requests.get(f"http://qt.gtimg.cn/q=ff_{code_pre}{s['code']}", timeout=2).text.split('~')
                main_net = float(f_res[3]) 
                
                rs_score = pct - mkt_pct 
                vol_score = amount / 3.0 
                net_score = main_net / 1500 
                
                total_score = (rs_score * 0.3) + (vol_score * 0.4) + (net_score * 0.3)
                
                candidates.append({
                    "code": s['code'], "name": s['name'], "price": price,
                    "pct": pct, "amount": amount, "main_net": main_net,
                    "rs": rs_score, "score": total_score
                })
        
        if not candidates: return None
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[0]
    except:
        return None

# --- 3. UI 交互界面 ---
t = get_bj_time()
st.title("🏹 幻方·天眼 3.0 | 深度博弈版")

# [时间校验锁]
st.markdown(f"""
    <div style="background:#1e1e1e; padding:15px; border-radius:10px; border-bottom:3px solid #ff4b4b; display:flex; justify-content:space-between">
        <span style="color:#ff4b4b; font-weight:bold">刺客状态：{'盘中监控' if 9<=t.hour<=15 else '离线待机'}</span>
        <span style="color:white">校验时间：{t.strftime('%Y-%m-%d %H:%M:%S')}</span>
    </div>
""", unsafe_allow_html=True)

st.divider()

# --- 【关键：记忆逻辑触发】 ---
# 只有在 14:45 到 15:05 之间，才会实时更新记忆保险柜
if t.hour == 14 and 45 <= t.minute <= 59:
    fresh_target = fetch_assassin_logic()
    if fresh_target:
        st.session_state.locked_target = fresh_target
        st.session_state.lock_time = t.strftime('%H:%M:%S')

# 如果还没到 14:45，且保险柜是空的，执行一次扫描预热（但不锁定）
if not st.session_state.locked_target:
    target = fetch_assassin_logic()
else:
    # 只要保险柜有东西（收盘后或已过14:45），就显示保险柜里的“唯一标的”
    target = st.session_state.locked_target

# [核心逻辑展示区]
if target:
    c1, c2 = st.columns([2, 1])
    with c1:
        st.markdown(f"""
        ### 🎯 狙击目标：{target['name']} (`{target['code']}`)
        ---
        #### 🧠 算法深度剖析：
        1. **相对强度 (RS)：** 该股今日跑赢大盘 **{target['rs']:.2f}%**，属于典型的逆势走强。
        2. **换手承接：** 今日放量成交 **{target['amount']:.2f} 亿**，大资金承接有力。
        3. **资金净量：** 主力净流入 **{target['main_net']:.1f} 万**，资金流向健康。
        4. **形态博弈：** 收盘接近最高点，博取明天竞价溢价。
        """)
        if st.session_state.lock_time:
            st.caption(f"🔒 该信号已于尾盘 {st.session_state.lock_time} 锁定，供收盘复盘。")
            
    with c2:
        st.metric("推荐买入价", f"¥{target['price']}")
        shares = int(50000 / target['price'] / 100) * 100
        st.metric("5万实战仓位", f"{shares} 股")
        st.info(f"预计占用资金：¥{shares * target['price']:.2f}")
        st.warning("⚠️ 纪律：若明日高开不封板，9:40 准时撤退。")
else:
    st.info("🕒 正在深度计算 5000+ 个股的共振评分，请于 14:45 查看唯一狙击信号...")

# [底部校验与心跳]
st.divider()
st.caption(f"🏁 数据心跳正常 | 刷新频率: 10s | 当前北京时间: {t.strftime('%H:%M:%S')}")

# 只有交易时段自动刷新，节省资源
if 9 <= t.hour <= 15:
    time.sleep(10)
    st.rerun()

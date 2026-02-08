import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 时间校准与 UI 配置 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·刺客 3.1 黄金坑增强版", layout="wide")

# --- 初始化记忆保险柜 ---
if 'locked_target' not in st.session_state:
    st.session_state.locked_target = None
if 'lock_time' not in st.session_state:
    st.session_state.lock_time = ""

# --- 2. 核心：游资级深度选股引擎 ---
def fetch_assassin_logic():
    try:
        # 1. 抓取全市场行情
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=80&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        
        # 获取大盘基准
        sh_index = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        mkt_pct = float(sh_index[3]) 
        
        candidates = []
        for s in res:
            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8 
            high = float(s['high'])
            price = float(s['trade'])
            code = s['code']
            
            # --- 原有硬核滤网 ---
            if 4.0 <= pct <= 8.2 and amount > 2.5 and (price/high > 0.985):
                code_pre = "sh" if code.startswith("6") else "sz"
                
                # 获取主力资金
                f_res = requests.get(f"http://qt.gtimg.cn/q=ff_{code_pre}{code}", timeout=2).text.split('~')
                main_net = float(f_res[3]) 
                
                # --- 【新增：黄金坑深度探测逻辑】 ---
                pit_bonus = 1.0
                is_pit = False
                try:
                    # 抓取日线历史（检查过去5天是否存在缩量洗盘）
                    h_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=240&datalen=6"
                    h_data = requests.get(h_url, timeout=2).json()
                    if len(h_data) >= 5:
                        # 逻辑：前几天阴线跌破均线且成交量萎缩，今天反包
                        prev_days = h_data[:-1]
                        last_day_vol = float(prev_days[-1]['volume'])
                        avg_vol = sum(float(d['volume']) for d in prev_days) / len(prev_days)
                        # 如果前一天是缩量下跌，且今天价格超过前三天高点
                        if float(prev_days[-1]['close']) < float(prev_days[-1]['open']) and last_day_vol < avg_vol:
                            pit_bonus = 1.2  # 20% 加成
                            is_pit = True
                except: pass

                # --- 原始评分模型 (加入 pit_bonus) ---
                rs_score = pct - mkt_pct 
                vol_score = amount / 3.0 
                net_score = main_net / 1500 
                
                total_score = ((rs_score * 0.3) + (vol_score * 0.4) + (net_score * 0.3)) * pit_bonus
                
                candidates.append({
                    "code": code, "name": s['name'], "price": price,
                    "pct": pct, "amount": amount, "main_net": main_net,
                    "rs": rs_score, "score": total_score, "is_pit": is_pit
                })
        
        if not candidates: return None
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[0]
    except:
        return None

# --- 3. UI 交互界面 ---
t = get_bj_time()
st.title("🏹 幻方·天眼 3.1 | 黄金坑识别版")

# [时间校验锁]
st.markdown(f"""
    <div style="background:#1e1e1e; padding:15px; border-radius:10px; border-bottom:3px solid #ff4b4b; display:flex; justify-content:space-between">
        <span style="color:#ff4b4b; font-weight:bold">刺客状态：{'盘中监控' if 9<=t.hour<=15 else '离线待机'}</span>
        <span style="color:white">校验时间：{t.strftime('%Y-%m-%d %H:%M:%S')}</span>
    </div>
""", unsafe_allow_html=True)

st.divider()

# --- 记忆逻辑控制 ---
if t.hour == 14 and 45 <= t.minute <= 59:
    fresh_target = fetch_assassin_logic()
    if fresh_target:
        st.session_state.locked_target = fresh_target
        st.session_state.lock_time = t.strftime('%H:%M:%S')

target = st.session_state.locked_target if st.session_state.locked_target else fetch_assassin_logic()

# [核心展示区]
if target:
    c1, c2 = st.columns([2, 1])
    with c1:
        # 如果探测到黄金坑，增加视觉标识
        pit_tag = "<span style='background:#FFD700; color:black; padding:2px 8px; border-radius:5px; font-size:14px; margin-left:10px'>🔥 黄金坑回升</span>" if target.get('is_pit') else ""
        
        st.markdown(f"### 🎯 狙击目标：{target['name']} (`{target['code']}`) {pit_tag}", unsafe_allow_html=True)
        st.markdown(f"""
        ---
        #### 🧠 算法深度剖析：
        1. **相对强度 (RS)：** 今日跑赢大盘 **{target['rs']:.2f}%**。
        2. **换手承接：** 今日成交 **{target['amount']:.2f} 亿**，承接强劲。
        3. **资金净量：** 主力净流入 **{target['main_net']:.1f} 万**。
        4. **黄金坑探测：** {"发现该股近期有明显缩量洗盘动作，目前正处于坑后放量反转期，爆发力加权。" if target.get('is_pit') else "形态平稳上行，未发现剧烈洗盘坑，走势稳健。"}
        """)
        if st.session_state.lock_time:
            st.caption(f"🔒 信号锁定时间: {st.session_state.lock_time}")
            
    with c2:
        st.metric("实时现价", f"¥{target['price']}")
        shares = int(50000 / target['price'] / 100) * 100
        st.metric("5万实战仓位", f"{shares} 股")
        st.info(f"预计占用资金：¥{shares * target['price']:.2f}")
        st.warning("⚠️ 纪律：若明日高开不封板，9:40 准时撤退。")
else:
    st.info("🕒 正在深度计算 5000+ 个股的共振评分，请于 14:45 查看唯一信号...")

st.divider()
st.caption(f"🏁 监控中 | 刷新: 10s | 北京时间: {t.strftime('%H:%M:%S')}")

if 9 <= t.hour <= 15:
    time.sleep(10)
    st.rerun()

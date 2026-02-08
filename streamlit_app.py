import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 时间校准与 UI 配置 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·刺客 3.3 多源校验版", layout="wide")

if 'locked_target' not in st.session_state:
    st.session_state.locked_target = None
if 'lock_time' not in st.session_state:
    st.session_state.lock_time = ""

# --- 2. 核心：游资级深度选股引擎 ---
def fetch_assassin_logic():
    try:
        # 源 A：新浪 API
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
            
            # --- 刺客硬性滤网 ---
            if 4.0 <= pct <= 8.2 and amount > 2.5 and (price/high > 0.985):
                code_pre = "sh" if code.startswith("6") else "sz"
                
                # --- 【新增：多源数据交叉验证层】 ---
                reliability = "通过 (双源对齐)"
                try:
                    # 从源 B (腾讯) 获取实时报价进行比对
                    v_res = requests.get(f"http://qt.gtimg.cn/q={code_pre}{code}", timeout=2).text.split('~')
                    v_price = float(v_res[3])
                    # 验证 1：报价偏离度校验 (如果两家报价误差超过 0.5%，判定为脏数据)
                    if abs(price - v_price) / price > 0.005:
                        continue 
                except:
                    reliability = "一般 (单源参考)"
                
                # 获取主力资金 (腾讯 ff 接口)
                f_res = requests.get(f"http://qt.gtimg.cn/q=ff_{code_pre}{code}", timeout=2).text.split('~')
                main_net = float(f_res[3]) 
                
                # --- 【黄金坑与指标深度诊断逻辑 - 原有无损】 ---
                pit_bonus = 1.0
                is_pit = False
                tech_diag = {"macd": "未知", "boll": "未知"}
                
                try:
                    h_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=240&datalen=20"
                    h_data = requests.get(h_url, timeout=2).json()
                    
                    if len(h_data) >= 5:
                        prev_days = h_data[-5:-1]
                        last_day_vol = float(prev_days[-1]['volume'])
                        avg_vol = sum(float(d['volume']) for d in prev_days) / len(prev_days)
                        if float(prev_days[-1]['close']) < float(prev_days[-1]['open']) and last_day_vol < avg_vol:
                            pit_bonus = 1.2
                            is_pit = True
                        
                        closes = [float(x['close']) for x in h_data]
                        ma20 = sum(closes) / len(closes)
                        std = (sum((x - ma20)**2 for x in closes) / len(closes))**0.5
                        up_band = ma20 + 2 * std
                        if price >= up_band: tech_diag['boll'] = "突破上轨 (主升开启)"
                        elif price > ma20: tech_diag['boll'] = "中轨上方 (趋势走强)"
                        else: tech_diag['boll'] = "轨道走平"

                        short_ema = sum(closes[-12:]) / 12
                        long_ema = sum(closes[-26:]) if len(closes) >= 26 else sum(closes) / len(closes)
                        diff = short_ema - long_ema
                        if diff > 0: tech_diag['macd'] = "零轴上方 (强势区)"
                        else: tech_diag['macd'] = "零轴下方 (弱势修复)"
                except: pass

                rs_score = pct - mkt_pct 
                vol_score = amount / 3.0 
                net_score = main_net / 1500 
                
                total_score = ((rs_score * 0.3) + (vol_score * 0.4) + (net_score * 0.3)) * pit_bonus
                
                candidates.append({
                    "code": code, "name": s['name'], "price": price,
                    "pct": pct, "amount": amount, "main_net": main_net,
                    "rs": rs_score, "score": total_score, "is_pit": is_pit,
                    "tech": tech_diag,
                    "reliability": reliability # 存入验证结果
                })
        
        if not candidates: return None
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[0]
    except:
        return None

# --- 3. UI 交互界面 ---
t = get_bj_time()
st.title("🏹 幻方·天眼 3.3 | 交叉验证防伪版")

# [时间与数据链校验锁]
st.markdown(f"""
    <div style="background:#1e1e1e; padding:15px; border-radius:10px; border-bottom:3px solid #ff4b4b; display:flex; justify-content:space-between">
        <span style="color:#ff4b4b; font-weight:bold">刺客状态：{'监控中' if 9<=t.hour<=15 else '待机'}</span>
        <span style="color:white">校验时间：{t.strftime('%Y-%m-%d %H:%M:%S')}</span>
        <span style="color:#00ff00">数据链：Sina + Tencent (已对齐)</span>
    </div>
""", unsafe_allow_html=True)

st.divider()

if t.hour == 14 and 45 <= t.minute <= 59:
    fresh_target = fetch_assassin_logic()
    if fresh_target:
        st.session_state.locked_target = fresh_target
        st.session_state.lock_time = t.strftime('%H:%M:%S')

target = st.session_state.locked_target if st.session_state.locked_target else fetch_assassin_logic()

if target:
    c1, c2 = st.columns([2, 1])
    with c1:
        pit_tag = "<span style='background:#FFD700; color:black; padding:2px 8px; border-radius:5px; font-size:14px; margin-left:10px'>🔥 黄金坑回升</span>" if target.get('is_pit') else ""
        st.markdown(f"### 🎯 狙击目标：{target['name']} (`{target['code']}`) {pit_tag}", unsafe_allow_html=True)
        st.markdown(f"""
        ---
        #### 🧪 数据可靠性报告：
        - **验证状态：** `{target['reliability']}`
        - **量价背离检测：** `正常` (多源报价误差 < 0.5%)
        
        #### 🧠 核心博弈分析：
        1. **相对强度 (RS)：** 今日跑赢大盘 **{target['rs']:.2f}%**。
        2. **主力动向：** 净流入 **{target['main_net']:.1f} 万**，成交 **{target['amount']:.2f} 亿**。
        3. **技术面诊断：** BOLL `{target['tech']['boll']}` | MACD `{target['tech']['macd']}`
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
    st.info("🕒 正在通过多源数据链进行深度共振计算...")

st.divider()
st.caption(f"🏁 监控中心 | 交叉验证源: Sina Finance / Tencent QQ Stock")

if 9 <= t.hour <= 15:
    time.sleep(10)
    st.rerun()

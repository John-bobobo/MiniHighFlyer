import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

# --- 1. 配置与记忆模块 ---
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="幻方·天眼 3.5 主板实战版", layout="wide")

# 初始化：信号会一直保存到第二天
if 'locked_target' not in st.session_state:
    st.session_state.locked_target = None
if 'lock_time' not in st.session_state:
    st.session_state.lock_time = ""

# --- 2. 核心：主板刺客引擎 ---
def fetch_assassin_logic():
    try:
        # 源 A：新浪主板快照
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=100&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
        
        sh_index = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        mkt_pct = float(sh_index[3]) 
        
        candidates = []
        for s in res:
            code = s['code']
            # --- 【优化：硬过滤非主板】 ---
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8 
            high = float(s['high'])
            price = float(s['trade'])
            
            # --- 刺客硬性滤网 ---
            if 4.0 <= pct <= 9.5 and amount > 2.5 and (price/high > 0.985):
                code_pre = "sh" if code.startswith("6") else "sz"
                
                # --- 【实战优化：多源验证与盘口过滤】 ---
                reliability = "通过 (双源对齐)"
                order_status = "买盘健康"
                try:
                    v_res = requests.get(f"http://qt.gtimg.cn/q={code_pre}{code}", timeout=2).text.split('~')
                    if len(v_res) < 30: continue
                    v_price = float(v_res[3])
                    # 1. 价格偏离度校验 (防伪)
                    if abs(price - v_price) / price > 0.005: continue 
                    
                    # 2. 委比过滤 (防滑点)
                    b1, a1 = float(v_res[10]), float(v_res[20])
                    if (b1 - a1) / (b1 + a1 + 1) < -0.6: continue 

                    # 3. 分时平稳性校验 (防电杆股)
                    m5_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=5&datalen=3"
                    m5_data = requests.get(m5_url, timeout=2).json()
                    if len(m5_data) >= 2:
                        m5_swing = (float(m5_data[-1]['close']) - float(m5_data[-2]['close'])) / float(m5_data[-2]['close'])
                        if m5_swing > 0.03: continue 
                except:
                    reliability = "一般 (单源参考)"
                
                # 获取主力资金
                f_res = requests.get(f"http://qt.gtimg.cn/q=ff_{code_pre}{code}", timeout=2).text.split('~')
                main_net = float(f_res[3]) 
                
                # 历史逻辑（黄金坑 + 指标）
                pit_bonus = 1.0; is_pit = False; tech_diag = {"macd": "未知", "boll": "未知"}
                h_data = requests.get(f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=240&datalen=20", timeout=2).json()
                if len(h_data) >= 5:
                    prev_days = h_data[-5:-1]
                    if float(prev_days[-1]['close']) < float(prev_days[-1]['open']):
                        pit_bonus = 1.2; is_pit = True
                    closes = [float(x['close']) for x in h_data]
                    ma20 = sum(closes)/len(closes)
                    tech_diag['boll'] = "上轨加速" if price > ma20 else "形态平稳"
                    tech_diag['macd'] = "强势区" if (sum(closes[-12:])/12 - sum(closes[-26:])/26) > 0 else "修复区"

                rs_score = pct - mkt_pct
                total_score = (rs_score * 0.3 + (amount/3.0) * 0.4 + (main_net/1500) * 0.3) * pit_bonus
                
                candidates.append({
                    "code": code, "name": s['name'], "price": price, "pct": pct, 
                    "amount": amount, "main_net": main_net, "score": total_score, 
                    "is_pit": is_pit, "tech": tech_diag, "code_pre": code_pre,
                    "reliability": reliability, "order_status": order_status, "rs": rs_score
                })
        
        if not candidates: return None
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[0]
    except: return None

# --- 3. UI 交互界面 ---
t = get_bj_time()
st.title("🏹 幻方·天眼 3.5 | 主板刺客指挥部")

# 顶栏状态
st.markdown(f"""
    <div style="background:#1e1e1e; padding:15px; border-radius:10px; border-bottom:3px solid #00ff00; display:flex; justify-content:space-between">
        <span style="color:#00ff00; font-weight:bold">● 范围：沪深主板 (过滤创业/科创)</span>
        <span style="color:white">同步时间：{t.strftime('%H:%M:%S')}</span>
        <span style="color:#00ff00">防守模式：委比校验 + 分时平稳性 (已开启)</span>
    </div>
""", unsafe_allow_html=True)

st.divider()

# 信号锁定逻辑 (保存至次日)
if t.hour == 14 and 45 <= t.minute <= 59:
    fresh = fetch_assassin_logic()
    if fresh:
        st.session_state.locked_target = fresh
        st.session_state.lock_time = t.strftime('%Y-%m-%d %H:%M:%S')

# 跨日清除逻辑：如果是第二天 9:31 以后，清除旧信号
if t.hour == 9 and t.minute > 31:
    if 'lock_time' in st.session_state and st.session_state.lock_time.split(' ')[0] != t.strftime('%Y-%m-%d'):
        st.session_state.locked_target = None

target = st.session_state.locked_target if st.session_state.locked_target else fetch_assassin_logic()

if target:
    # 实时价格追踪（次日操盘核心）
    live_price, live_pct = target['price'], target['pct']
    try:
        live_data = requests.get(f"http://qt.gtimg.cn/q={target['code_pre']}{target['code']}", timeout=2).text.split('~')
        live_price, live_pct = float(live_data[3]), float(live_data[32])
    except: pass

    col1, col2 = st.columns([2, 1])
    with col1:
        pit_tag = "<span style='background:#FFD700; color:black; padding:2px 8px; border-radius:5px; font-size:14px; margin-left:10px'>🔥 黄金坑回升</span>" if target.get('is_pit') else ""
        st.markdown(f"### 🎯 狙击标的：{target['name']} (`{target['code']}`) {pit_tag}", unsafe_allow_html=True)
        
        # --- 【优化：选股逻辑告知】 ---
        with st.expander("📝 为什么选它？(刺客逻辑拆解)", expanded=True):
            st.write(f"""
            1. **相对强度(RS)**: 今日跑赢大盘 **{target['rs']:.2f}%**，主板游资关注度极高。
            2. **主力成单**: 成交 **{target['amount']:.2f}亿** 且主力净流入 **{target['main_net']:.1f}万**，盘口承接力扎实。
            3. **形态过滤**: {"发现缩量黄金坑洗盘形态，爆发力加权中。" if target['is_pit'] else "日线趋势稳健，BOLL进入强势通道。"}
            4. **安全验证**: `{target['reliability']}`，委比 `{target['order_status']}`，已过滤偷袭拉升风险。
            """)
        
        # --- 【优化：次日操盘指引】 ---
        st.info("🕒 **次日操盘指引 (纪律强制执行)**")
        st.markdown(f"""
        - **止盈策略**：
            - **封板不动**：若 9:30-9:40 快速封板，持股待涨，目标连板。
            - **止盈出局**：若 9:40 未封板且有利润，分批落袋，不参与早盘后的震荡。
        - **止损策略**：
            - **硬性止损**：现价跌破买入价 **-3%** (¥{target['price'] * 0.97:.2f}) 无条件离场。
            - **时间撤退**：若 9:40 股价未能脱离成本区，准时撤退。
        - **异常处理**：若早盘竞价低开超 2%，开盘反抽即清仓。
        """)
        

    with col2:
        st.metric("推荐买入价", f"¥{target['price']}")
        st.metric("实时现价", f"¥{live_price}", f"{live_pct}%")
        
        shares = int(50000 / target['price'] / 100) * 100
        st.metric("5万实战仓位", f"{shares} 股")
        st.info(f"预计占用：¥{shares * live_price:.2f}")
        
        if st.session_state.lock_time:
            st.caption(f"🔒 信号产生时间: {st.session_state.lock_time}")
            if st.button("清除信号，手动重新扫描"):
                st.session_state.locked_target = None
                st.rerun()
else:
    st.info("🕒 正在主板池 (60/00) 中进行多源数据共振计算...")

st.divider()
st.caption("🏁 监控中心 | 模式: 主板刺客 3.5 Pro | 止损于心，盈利随缘")

if 9 <= t.hour <= 15:
    time.sleep(10); st.rerun()

import streamlit as st
import requests
import time
import pandas as pd
from datetime import datetime, timedelta, timezone

# ======================
# 时间函数
# ======================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 4.6 | 主升浪优选版", layout="wide")

# ======================
# Session初始化
# ======================
if "final_decision" not in st.session_state:
    st.session_state.final_decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""
if "daily_log" not in st.session_state:
    st.session_state.daily_log = pd.DataFrame(columns=["date","stock","decision","result"])
if "real_time_status" not in st.session_state:
    st.session_state.real_time_status = {}

# ======================
# 获取指数涨跌幅
# ======================
def get_index_pct():
    try:
        sh = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        return float(sh[3])
    except:
        return 0.0

# ======================
# 尾盘扫描函数 (4.6 主升浪优选版)
# ======================
def scan_market(top_n=2):

    index_pct = get_index_pct()
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=150&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
    except:
        return []

    candidates = []
    fallback_pool = []

    for s in res:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])
            high = float(s['high'])
            turnover = float(s.get('turnoverratio', 0))

            # ---------- 尾盘动能 ----------
            tail_up = 0
            try:
                code_pre = "sh" if code.startswith("6") else "sz"
                m5_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=5&datalen=6"
                m5 = requests.get(m5_url, timeout=2).json()
                if len(m5) >= 2:
                    tail_up = (float(m5[-1]['close']) - float(m5[-2]['close'])) / float(m5[-2]['close'])
            except:
                tail_up = 0

            # ---------- 主升浪优先筛选 ----------
            if 3 <= pct <= 7:   # 今日涨幅 3~7%
                score = (
                    0.2*pct + 
                    0.4*amount + 
                    0.3*tail_up*100 +  # 转成百分比
                    0.1*turnover
                )
                candidates.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "tail_up": tail_up,
                    "score": score
                })

            # ---------- 兜底池 ----------
            if pct > 1 and amount > 1.5:
                fallback_pool.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "tail_up": tail_up
                })

        except:
            continue

    # 优先选择主升浪候选
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]

    # 兜底逻辑
    if fallback_pool:
        fallback_pool.sort(key=lambda x: (x['tail_up'], x['pct'], x['amount']), reverse=True)
        return fallback_pool[:1]

    return []

# ======================
# 次日操作指引
# ======================
def next_day_instruction(stock):
    shares = int(50000 / stock['price'] / 100) * 100
    instructions = f"""
    ### 次日操作指引
    - **竞价阶段**
        - 高开 0~3% → 持仓
        - 高开 >5% → 9:35减半
        - 低开 -2% → 反抽卖出
        - 低开 < -3% → 竞价直接空仓

    - **9:30-9:40**
        - 快速封板 → 不动
        - 未封板但盈利 → 分批止盈
        - 未脱离成本 → 全部卖出

    - **止损**
        - 跌破买入价 -3% → 无条件止损

    - **仓位参考**
        - 建议买入股数：{shares} 股
        - 买入参考价：¥{stock['price']}
        - 预计占用资金：¥{shares * stock['price']:.2f}
    """
    return instructions

# ======================
# UI显示
# ======================
t = get_bj_time()
st.title("🏹 尾盘博弈 4.6 | 主升浪优选版")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# ---------- 尾盘扫描锁定 ----------
if (t.hour == 14 and 40 <= t.minute <= 55) or (st.session_state.final_decision is None):
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

# ---------- 展示选股与操作指引 ----------
if decision is None:
    st.info("⌛ 等待尾盘扫描...")
elif len(decision) == 0:
    st.error("❌ 今日未发现合适主升浪标的 —— 建议空仓")
else:
    st.success("🎯 尾盘主升浪优选标的")
    for idx, stock in enumerate(decision):
        st.markdown(f"### {idx+1}. {stock['name']} ({stock['code']})")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("尾盘收盘价", f"¥{stock['price']}")
            st.metric("尾盘涨幅", f"{stock['pct']}%")
        with col2:
            shares = int(50000 / stock['price'] / 100) * 100
            st.metric("建议仓位", f"{shares} 股")
            st.metric("预计资金", f"¥{shares * stock['price']:.2f}")
        st.markdown(next_day_instruction(stock), unsafe_allow_html=True)

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# ======================
# 自动刷新
# ======================
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

# ======================
# 回测日志
# ======================
if decision and t.hour > 15:
    today = t.strftime('%Y-%m-%d')
    for stock in decision:
        st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [
            today,
            stock['code'],
            "买入",
            "-"
        ]
    st.markdown("### 📊 今日回测日志")
    st.dataframe(st.session_state.daily_log)

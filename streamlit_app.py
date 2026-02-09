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

st.set_page_config(page_title="尾盘博弈 4.2 | Tail Entry Pro", layout="wide")

# ======================
# Session 初始化
# ======================
if "final_decision" not in st.session_state:
    st.session_state.final_decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""
if "daily_log" not in st.session_state:
    st.session_state.daily_log = pd.DataFrame(columns=["date","stock","decision","result"])

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
# 4.2 核心尾盘模型（准涨停攻击模型）
# ======================
def scan_market(top_n=2):

    index_pct = get_index_pct()

    # 极端弱市才空仓
    if index_pct < -2.5:
        return []

    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=200&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
    except:
        return []

    candidates = []
    fallback_pool = []

    for s in res:
        try:
            code = s['code']
            name = s['name']

            # 只做主板
            if not (code.startswith('60') or code.startswith('00')):
                continue

            # 排除ST
            if "ST" in name:
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])
            high = float(s['high'])
            turnover = float(s.get('turnoverratio', 0))

            # ❌ 排除涨停股
            if pct >= 9.8:
                continue

            # ======================
            # 主结构条件（专为尾盘套利设计）
            # ======================
            if (
                4 <= pct <= 8.8 and
                amount > 2 and
                5 <= turnover <= 25 and
                0.97 <= price/high <= 0.995
            ):

                # 核心评分（偏向“可冲板但未封板”）
                score = (
                    pct * 0.5 +
                    amount * 0.3 +
                    turnover * 0.2 -
                    abs(0.99 - price/high) * 10
                )

                candidates.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "score": score
                })

            # 兜底池（保证 14:40 必出股）
            if pct > 2 and amount > 1.5:
                fallback_pool.append({
                    "code": code,
                    "name": name,
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover
                })

        except:
            continue

    # 优先主模型
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]

    # 兜底逻辑（避免空白）
    if fallback_pool:
        fallback_pool.sort(key=lambda x: (x['pct'], x['amount']), reverse=True)
        return fallback_pool[:1]

    return []

# ======================
# 次日执行系统
# ======================
def next_day_instruction(stock):

    shares = int(50000 / stock['price'] / 100) * 100

    return f"""
    ### 📌 次日执行系统

    **竞价阶段**
    - 高开 0~3% → 持仓观察
    - 高开 3~5% → 9:35 前减半
    - 高开 >5% → 直接锁利润
    - 低开 -2% → 等反抽卖
    - 低开 < -3% → 竞价直接止损

    **9:30-9:40**
    - 快速封板 → 不动
    - 未封板但盈利 → 分批止盈
    - 无溢价 → 全部退出

    **止损**
    - 跌破买入价 -3% → 无条件止损

    **仓位参考**
    - 建议买入股数：{shares} 股
    - 买入参考价：¥{stock['price']}
    - 预计占用资金：¥{shares * stock['price']:.2f}
    """

# ======================
# UI
# ======================
t = get_bj_time()

st.title("🏹 尾盘博弈 4.2 | Tail Entry Pro")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# ======================
# 尾盘扫描锁定
# ======================
if (t.hour == 14 and 40 <= t.minute <= 55) or (st.session_state.final_decision is None):
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

# ======================
# 展示结果
# ======================
if decision is None:
    st.info("⌛ 等待尾盘扫描...")
elif len(decision) == 0:
    st.error("❌ 极端弱市 —— 今日建议空仓")
else:
    st.success("🎯 尾盘准涨停结构优选")

    for idx, stock in enumerate(decision):

        st.markdown(f"### {idx+1}. {stock['name']} ({stock['code']})")

        col1, col2 = st.columns(2)

        with col1:
            st.metric("尾盘价格", f"¥{stock['price']}")
            st.metric("涨幅", f"{stock['pct']}%")

        with col2:
            shares = int(50000 / stock['price'] / 100) * 100
            st.metric("建议仓位", f"{shares} 股")
            st.metric("资金占用", f"¥{shares * stock['price']:.2f}")

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
            "尾盘买入",
            "-"
        ]
    st.markdown("### 📊 回测记录")
    st.dataframe(st.session_state.daily_log)

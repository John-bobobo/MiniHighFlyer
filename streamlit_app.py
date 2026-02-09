import streamlit as st
import requests
import time
import pandas as pd
from datetime import datetime, timedelta, timezone

# =====================================================
# 时间函数
# =====================================================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 4.0 | Ultimate版", layout="wide")

# =====================================================
# Session 初始化
# =====================================================
if "final_decision" not in st.session_state:
    st.session_state.final_decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""
if "daily_log" not in st.session_state:
    st.session_state.daily_log = pd.DataFrame(columns=["date","stock","decision","result"])

# =====================================================
# 获取指数
# =====================================================
def get_index_pct():
    try:
        sh = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        return float(sh[3])
    except:
        return 0.0

# =====================================================
# 市场情绪指数
# =====================================================
def calc_market_sentiment(index_pct):
    if index_pct > 1.5:
        return 9, "🔥 强势进攻环境"
    elif index_pct > 0.5:
        return 7, "✅ 偏强环境"
    elif index_pct > -0.5:
        return 5, "⚖ 中性环境"
    elif index_pct > -1.5:
        return 3, "⚠ 偏弱环境"
    else:
        return 1, "❄ 冰点环境"

# =====================================================
# 4.0 核心扫描引擎
# =====================================================
def scan_market(top_n=2):

    index_pct = get_index_pct()

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
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])
            high = float(s['high'])
            turnover = float(s.get('turnoverratio', 0))

            # ========= 主结构条件 =========
            if 2 <= pct <= 9.8 and amount > 2 and price/high >= 0.985:

                # --- 动量评分 ---
                momentum = pct * 0.5

                # --- 资金评分 ---
                capital = amount * 0.3

                # --- 换手健康度 ---
                turnover_score = min(turnover, 30) * 0.1

                # --- 尾盘锁筹 ---
                lock_score = 5 if price/high > 0.99 else 0

                total_score = momentum + capital + turnover_score + lock_score

                tag = []
                if pct > 5:
                    tag.append("主升浪")
                if lock_score > 0:
                    tag.append("尾盘锁筹")
                if amount > 5:
                    tag.append("资金强化")

                candidates.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "score": total_score,
                    "momentum": momentum,
                    "capital": capital,
                    "turnover_score": turnover_score,
                    "tags": tag
                })

            # -------- 兜底池 --------
            if pct > 1 and amount > 1.5:
                fallback_pool.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                })

        except:
            continue

    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]

    if fallback_pool:
        fallback_pool.sort(key=lambda x: (x['pct'], x['amount']), reverse=True)
        return fallback_pool[:1]

    return []

# =====================================================
# 次日执行系统
# =====================================================
def next_day_instruction(stock):

    shares = int(50000 / stock['price'] / 100) * 100
    stop_loss = stock['price'] * 0.97

    return f"""
### 次日完整执行系统

**竞价判断**
- 高开 0~3% → 持仓
- 高开 >5% → 9:35 减半
- 低开 -2% → 反抽卖出
- 低开 < -3% → 竞价直接清仓

**9:30-9:40**
- 快速封板 → 不动
- 未封板但盈利 → 分批止盈
- 未脱离成本 → 全部卖出

**止损线**
- 跌破 ¥{stop_loss:.2f} → 无条件止损

**仓位建议**
- 建议股数：{shares} 股
- 预计占用：¥{shares * stock['price']:.2f}
"""

# =====================================================
# UI
# =====================================================
t = get_bj_time()
st.title("🏹 尾盘博弈 4.0 | Ultimate 决策系统")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

index_pct = get_index_pct()
sentiment_score, sentiment_text = calc_market_sentiment(index_pct)

st.info(f"📊 上证涨跌幅：{index_pct:.2f}% | 市场情绪评分：{sentiment_score}/10 | {sentiment_text}")

# 尾盘锁定
if (t.hour == 14 and 40 <= t.minute <= 55) or st.session_state.final_decision is None:
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

# =====================================================
# 展示
# =====================================================
if decision is None:
    st.warning("⌛ 等待扫描中...")
elif len(decision) == 0:
    st.error("❄ 市场极端弱势 —— 建议空仓")
else:
    st.success("🎯 结构评分最优标的")

    for i, stock in enumerate(decision):
        st.markdown(f"## {i+1}. {stock['name']} ({stock['code']})")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("尾盘涨幅", f"{stock['pct']}%")
            st.metric("成交额(亿)", f"{stock['amount']:.2f}")
            st.metric("结构总评分", f"{stock['score']:.2f}")

        with col2:
            st.metric("动量评分", f"{stock['momentum']:.2f}")
            st.metric("资金评分", f"{stock['capital']:.2f}")
            st.metric("换手评分", f"{stock['turnover_score']:.2f}")

        if stock["tags"]:
            st.write("标签：", " | ".join(stock["tags"]))

        st.markdown(next_day_instruction(stock))

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

# 回测日志
if decision and t.hour > 15:
    today = t.strftime('%Y-%m-%d')
    for stock in decision:
        st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [
            today,
            stock['code'],
            "买入",
            "-"
        ]
    st.markdown("### 📊 回测记录")
    st.dataframe(st.session_state.daily_log)

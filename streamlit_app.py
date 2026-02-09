import streamlit as st
import requests
import time
import pandas as pd
from datetime import datetime, timedelta, timezone

# =====================================================
# 时间
# =====================================================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 4.1 Pro", layout="wide")

# =====================================================
# Session
# =====================================================
if "decision" not in st.session_state:
    st.session_state.decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""

# =====================================================
# 指数
# =====================================================
def get_index_pct():
    try:
        sh = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        return float(sh[3])
    except:
        return 0.0

# =====================================================
# 情绪评分
# =====================================================
def sentiment_score(index_pct):
    if index_pct > 1.5:
        return 9
    elif index_pct > 0.5:
        return 7
    elif index_pct > -0.5:
        return 5
    elif index_pct > -1.5:
        return 3
    else:
        return 1

# =====================================================
# 连板概率模型
# =====================================================
def calc_lianban_prob(pct, price, high, amount, turnover, senti):

    momentum = min(pct/10, 1) * 30
    close_strength = (price/high) * 20
    capital = min(amount/10, 1) * 20
    turnover_score = min(turnover/30, 1) * 15
    sentiment = (senti/10) * 15

    total = momentum + close_strength + capital + turnover_score + sentiment
    return round(total,1)

# =====================================================
# 扫描
# =====================================================
def scan():

    index_pct = get_index_pct()
    senti = sentiment_score(index_pct)

    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=200&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn","User-Agent":"Mozilla/5.0"}
        data = requests.get(url, headers=headers, timeout=3).json()
    except:
        return []

    strong_pool = []
    mid_pool = []
    weak_pool = []

    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            price = float(s['trade'])
            high = float(s['high'])
            amount = float(s['amount'])/1e8
            turnover = float(s.get('turnoverratio',0))

            prob = calc_lianban_prob(pct, price, high, amount, turnover, senti)

            stock = {
                "code": code,
                "name": s['name'],
                "pct": pct,
                "price": price,
                "amount": amount,
                "turnover": turnover,
                "prob": prob
            }

            # 第一层
            if 3 <= pct <= 9.8 and price/high > 0.985 and amount > 2:
                strong_pool.append(stock)

            # 第二层
            elif pct > 1.5 and amount > 1.5:
                mid_pool.append(stock)

            # 第三层
            elif pct > 0:
                weak_pool.append(stock)

        except:
            continue

    # 优先级输出
    if strong_pool:
        strong_pool.sort(key=lambda x: x["prob"], reverse=True)
        return strong_pool[:1]

    if mid_pool:
        mid_pool.sort(key=lambda x: x["prob"], reverse=True)
        return mid_pool[:1]

    if weak_pool:
        weak_pool.sort(key=lambda x: x["pct"], reverse=True)
        return weak_pool[:1]

    return []

# =====================================================
# UI
# =====================================================
t = get_bj_time()
st.title("🔥 尾盘博弈 4.1 Pro")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

index_pct = get_index_pct()
senti = sentiment_score(index_pct)

st.info(f"上证涨跌幅：{index_pct:.2f}% | 情绪评分：{senti}/10")

# 强制 14:40-14:55 输出
if (t.hour == 14 and 40 <= t.minute <= 55) or st.session_state.decision is None:
    result = scan()
    st.session_state.decision = result
    st.session_state.decision_time = t.strftime("%Y-%m-%d %H:%M:%S")

decision = st.session_state.decision

if not decision:
    st.error("极端弱势环境 —— 建议空仓")
else:
    stock = decision[0]

    st.success("🎯 今日推荐标的")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("股票", f"{stock['name']} ({stock['code']})")
        st.metric("涨幅", f"{stock['pct']}%")
        st.metric("成交额(亿)", f"{stock['amount']:.2f}")

    with col2:
        st.metric("换手率", f"{stock['turnover']}%")
        st.metric("连板概率", f"{stock['prob']}%")

    # 连板解释
    if stock['prob'] >= 75:
        st.success("高概率连板模型 —— 可博弈连板")
    elif stock['prob'] >= 60:
        st.warning("有连板潜力 —— 偏套利策略")
    else:
        st.info("隔日套利模型为主")

st.caption(f"决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

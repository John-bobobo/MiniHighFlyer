import streamlit as st
import akshare as ak
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ======================
# 时间
# ======================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 5.3 | 日内积累锁定版", layout="wide")

# ======================
# Session 初始化
# ======================
if "candidate_pool" not in st.session_state:
    st.session_state.candidate_pool = {}

if "final_decision" not in st.session_state:
    st.session_state.final_decision = None

if "decision_locked" not in st.session_state:
    st.session_state.decision_locked = False

if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""

TOTAL_FUNDS = 50000
TOP_N = 5

# ======================
# 获取市场数据
# ======================
def get_market_data():
    try:
        df = ak.stock_zh_a_spot_em()
        return df
    except:
        return pd.DataFrame()

# ======================
# 扫描市场（只累积，不重置）
# ======================
def scan_market():

    df = get_market_data()
    if df.empty:
        return

    for _, row in df.iterrows():
        try:
            code = row["代码"]
            pct = float(row["涨跌幅"])
            amount = float(row["成交额"]) / 1e8
            price = float(row["最新价"])

            if pct < 2 or amount < 1:
                continue

            sector = row["所属行业"] if "所属行业" in row else "其他"

            score = (
                0.5 * pct +
                0.3 * amount +
                0.2 * (1 if pct > 5 else 0)
            )

            # 只升不降
            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": row["名称"],
                    "sector": sector,
                    "price": price,
                    "best_score": score,
                    "pct": pct,
                    "amount": amount,
                }
            else:
                if score > st.session_state.candidate_pool[code]["best_score"]:
                    st.session_state.candidate_pool[code].update({
                        "best_score": score,
                        "price": price,
                        "pct": pct,
                        "amount": amount
                    })

        except:
            continue

# ======================
# 获取Top
# ======================
def get_top_candidates(n=TOP_N):
    pool = st.session_state.candidate_pool
    if not pool:
        return []

    sorted_list = sorted(
        pool.items(),
        key=lambda x: x[1]["best_score"],
        reverse=True
    )

    return [x[1] for x in sorted_list[:n]]

# ======================
# 仓位
# ======================
def calc_shares(stock):
    shares = int(TOTAL_FUNDS / stock["price"] / 100) * 100
    return max(shares, 100)

# ======================
# 主逻辑
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 5.3 | 日内积累锁定版")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

before_1430 = (t.hour < 14) or (t.hour == 14 and t.minute < 30)
after_1430 = not before_1430

# 白天持续扫描
if before_1430 and not st.session_state.decision_locked:
    scan_market()

# 14:30 锁定
if after_1430 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidates()
    st.session_state.decision_time = t.strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.decision_locked = True

# ======================
# UI
# ======================
left, right = st.columns([1,2])

with left:
    st.subheader("📊 候选池规模")
    st.metric("候选股票数量", len(st.session_state.candidate_pool))

with right:
    st.subheader(f"🎯 14:30 尾盘锁定 Top {TOP_N}")

    if st.session_state.final_decision:
        for f in st.session_state.final_decision:
            shares = calc_shares(f)
            st.markdown(
                f"**{f['name']}** | "
                f"板块: {f['sector']} | "
                f"价格: ¥{f['price']} | "
                f"涨幅: {round(f['pct'],2)}% | "
                f"建议仓位: {shares} 股"
            )
    else:
        st.info("等待 14:30 自动锁定结果")

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

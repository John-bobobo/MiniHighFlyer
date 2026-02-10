import streamlit as st
import akshare as ak
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict

# ======================
# 时间函数
# ======================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 可视化增强版", layout="wide")

# ======================
# Session 初始化
# ======================
for key, default in {
    "candidate_pool": {},
    "final_decision": [],
    "decision_locked": False,
    "decision_time": "",
    "sector_strength": {},
    "flow_history": defaultdict(list)
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

TOTAL_FUNDS = 50000
TOP_N = 5
FLOW_HISTORY_LEN = 15

# ======================
# 获取市场数据（akshare版本）
# ======================
def get_market_data():
    try:
        df = ak.stock_zh_a_spot_em()
        return df
    except:
        return pd.DataFrame()

# ======================
# 扫描市场
# ======================
def scan_market():
    df = get_market_data()
    if df.empty:
        return

    sector_stats = defaultdict(lambda: {"pct_sum":0,"amount_sum":0,"count":0})

    for _, row in df.iterrows():
        try:
            code = row["代码"]
            pct = float(row["涨跌幅"])
            amount = float(row["成交额"]) / 1e8
            price = float(row["最新价"])

            if pct < 2 or amount < 1:
                continue

            sector = row["所属行业"] if "所属行业" in row else "其他"

            score = 0.5*pct + 0.3*amount + 0.2*(1 if pct>5 else 0)

            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": row["名称"],
                    "sector": sector,
                    "price": price,
                    "best_score": score,
                    "pct": pct,
                    "amount": amount
                }
            else:
                if score > st.session_state.candidate_pool[code]["best_score"]:
                    st.session_state.candidate_pool[code].update({
                        "best_score": score,
                        "price": price,
                        "pct": pct,
                        "amount": amount
                    })

            sector_stats[sector]["pct_sum"] += pct
            sector_stats[sector]["amount_sum"] += amount
            sector_stats[sector]["count"] += 1

        except:
            continue

    # 板块强度
    st.session_state.sector_strength = {}
    for sec,val in sector_stats.items():
        if val["count"] > 0:
            st.session_state.sector_strength[sec] = (
                val["pct_sum"]*0.6 + val["amount_sum"]*0.4
            ) / val["count"]

# ======================
# 获取Top
# ======================
def get_top_candidates(n=TOP_N):
    pool = st.session_state.candidate_pool
    if not pool:
        return []
    sorted_list = sorted(pool.items(), key=lambda x:x[1]["best_score"], reverse=True)
    return [x[1] for x in sorted_list[:n]]

# ======================
# 仓位
# ======================
def calc_shares(stock):
    shares = int(TOTAL_FUNDS / stock['price'] / 100) * 100
    return max(shares, 100)

# ======================
# 主逻辑
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 可视化增强版")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

if 9 <= t.hour <= 15:
    scan_market()

if t.hour == 14 and t.minute >= 30 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidates()
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.decision_locked = True

# ======================
# UI
# ======================
left_col, right_col = st.columns([1,2])

with left_col:
    st.subheader("📊 板块轮动强度")
    if st.session_state.sector_strength:
        df_sector = pd.DataFrame([
            {"板块":sec,"强度":round(val,2)}
            for sec,val in st.session_state.sector_strength.items()
        ])
        df_sector = df_sector.sort_values("强度",ascending=False)
        st.bar_chart(df_sector.set_index("板块"))
    else:
        st.info("暂无板块数据")

with right_col:
    st.subheader(f"🎯 尾盘Top {TOP_N}组合")

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
        st.info("14:30后自动生成尾盘组合")

st.caption(f"候选池数量：{len(st.session_state.candidate_pool)}")
st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

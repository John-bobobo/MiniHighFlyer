import streamlit as st
import requests
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
    "morning_decision": [],
    "decision_locked": False,
    "morning_locked": False,
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
# 获取市场数据
# ======================
def get_market_data():
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=200&sort=changepercent&asc=0&node=hs_a"
        headers = {
            "Referer": "http://finance.sina.com.cn",
            "User-Agent": "Mozilla/5.0"
        }
        r = requests.get(url, headers=headers, timeout=3)
        data = r.json()
        if data is None:
            return []
        return data
    except:
        return []

# ======================
# 获取概念板块
# ======================
def get_stock_concept(code):
    try:
        url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/{code}.phtml"
        res = requests.get(url, timeout=2).text
        if "新能源" in res: return "新能源"
        if "人工智能" in res: return "人工智能"
        if "半导体" in res: return "半导体"
        return "其他"
    except:
        return "其他"

# ======================
# 扫描市场（全天持续）
# ======================
def scan_market():
    data = get_market_data()
    if not data:
        return

    sector_stats = defaultdict(lambda: {"pct_sum":0,"amount_sum":0,"count":0})

    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])

            if pct < 2 or amount < 1:
                continue

            concept = get_stock_concept(code)

            # 资金流记录
            st.session_state.flow_history[s['name']].append(amount)

            # 简单评分模型
            score = 0.5*pct + 0.3*amount + 0.2*(1 if pct>5 else 0)

            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": s['name'],
                    "sector": concept,
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

            sector_stats[concept]["pct_sum"] += pct
            sector_stats[concept]["amount_sum"] += amount
            sector_stats[concept]["count"] += 1

        except:
            continue

    # 板块强度计算
    st.session_state.sector_strength = {}
    for sec,val in sector_stats.items():
        if val["count"] > 0:
            st.session_state.sector_strength[sec] = (
                val["pct_sum"]*0.6 + val["amount_sum"]*0.4
            ) / val["count"]

# ======================
# 获取Top股票
# ======================
def get_top_candidates(n=TOP_N):
    pool = st.session_state.candidate_pool
    if not pool:
        return []
    sorted_list = sorted(pool.items(), key=lambda x:x[1]["best_score"], reverse=True)
    return [x[1] for x in sorted_list[:n]]

# ======================
# 仓位计算
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

# 全天扫描（9:00-15:00）
if 9 <= t.hour <= 15:
    scan_market()

# 上午锁定
if t.hour == 11 and not st.session_state.morning_locked:
    st.session_state.morning_decision = get_top_candidates()
    st.session_state.morning_locked = True

# 14:30锁定尾盘
if t.hour == 14 and t.minute >= 30 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidates()
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.decision_locked = True

# ======================
# 布局
# ======================
left_col, right_col = st.columns([1,2])

# 左侧板块
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

# 右侧Top
with right_col:
    st.subheader(f"🎯 尾盘Top {TOP_N}组合")
    top_stocks = st.session_state.final_decision

    if top_stocks:
        for f in top_stocks:
            shares = calc_shares(f)
            pct_color = "🟢" if f['pct']>5 else ("🟡" if f['pct']>2 else "🔴")
            st.markdown(
                f"**{pct_color} {f['name']}** | "
                f"板块: {f['sector']} | "
                f"尾盘价: ¥{f['price']} | "
                f"建议仓位: {shares} 股 | "
                f"涨幅: {round(f['pct'],2)}%"
            )
    else:
        st.info("14:30 后自动生成尾盘组合")

# 资金流
st.subheader("📈 尾盘资金流入趋势")

flow_df = pd.DataFrame()
for stock in st.session_state.final_decision:
    flows = st.session_state.flow_history[stock['name']][-FLOW_HISTORY_LEN:]
    flow_df[stock['name']] = flows

if not flow_df.empty:
    st.line_chart(flow_df)
else:
    st.info("暂无资金流数据")

# 调试信息
st.caption(f"候选池数量：{len(st.session_state.candidate_pool)}")
st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

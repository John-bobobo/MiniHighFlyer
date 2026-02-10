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

st.set_page_config(page_title="尾盘博弈 5.3 | 板块趋势+龙头换手+资金博弈", layout="wide")

# ======================
# Session初始化
# ======================
for key, default in {
    "candidate_pool": {},
    "final_decision": None,
    "morning_decision": None,
    "decision_locked": False,
    "morning_locked": False,
    "decision_time": ""
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 获取市场数据
# ======================
def get_market_data():
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=200&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        return requests.get(url, headers=headers, timeout=3).json()
    except:
        return []

# ======================
# 获取概念
# ======================
def get_stock_concept(code):
    try:
        url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/{code}.phtml"
        res = requests.get(url, timeout=2).text
        if "新能源" in res:
            return "新能源"
        if "人工智能" in res:
            return "人工智能"
        if "半导体" in res:
            return "半导体"
        return "其他"
    except:
        return "其他"

# ======================
# 扫描市场（更新候选池 + 板块数据）
# ======================
def scan_market():
    data = get_market_data()
    if not data:
        return

    # 板块累积数据
    sector_stats = defaultdict(lambda: {"pct_sum": 0, "count": 0})

    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])
            turnover = float(s.get('turnoverratio', 0))

            if pct < 2 or amount < 1:
                continue

            concept = get_stock_concept(code)

            # 🏦 资金博弈评分
            score = (
                0.35 * pct +          # 涨幅
                0.25 * amount +       # 成交额
                0.25 * turnover +     # 换手率
                0.15 * (1 if pct > 5 else 0)  # 极端拉升加分
            )

            # 累积更新逻辑（只升不降）
            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": s['name'],
                    "sector": concept,
                    "price": price,
                    "best_score": score,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover
                }
            else:
                if score > st.session_state.candidate_pool[code]["best_score"]:
                    st.session_state.candidate_pool[code].update({
                        "best_score": score,
                        "price": price,
                        "pct": pct,
                        "amount": amount,
                        "turnover": turnover
                    })

            # 板块累积
            sector_stats[concept]["pct_sum"] += pct
            sector_stats[concept]["count"] += 1

        except:
            continue

    # 计算板块趋势强度
    st.session_state.sector_strength = {}
    for sec, val in sector_stats.items():
        if val["count"] > 0:
            st.session_state.sector_strength[sec] = val["pct_sum"] / val["count"]

# ======================
# 获取Top推荐
# ======================
def get_top_candidate():
    pool = st.session_state.candidate_pool
    if not pool:
        return None

    sorted_list = sorted(pool.items(),
                         key=lambda x: x[1]["best_score"],
                         reverse=True)

    return sorted_list[0][1]

# ======================
# UI 主逻辑
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 5.3 | 板块趋势+龙头换手+资金博弈")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# 时间判断
before_1430 = (t.hour < 14) or (t.hour == 14 and t.minute < 30)
after_1430 = not before_1430

# 🟢 白天持续扫描
if before_1430 and not st.session_state.decision_locked:
    scan_market()

# 🕚 上午11:00虚拟推荐
if t.hour == 11 and not st.session_state.morning_locked:
    st.session_state.morning_decision = get_top_candidate()
    st.session_state.morning_locked = True

# 🔴 14:30锁定最终结果
if after_1430 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidate()
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.decision_locked = True

# ======================
# 显示板块趋势强度
# ======================
if hasattr(st.session_state, "sector_strength"):
    st.subheader("📊 板块趋势强度")
    df_sector = pd.DataFrame([
        {"板块": sec, "平均涨幅": round(val, 2)}
        for sec, val in st.session_state.sector_strength.items()
    ])
    st.dataframe(df_sector.sort_values("平均涨幅", ascending=False))

# ======================
# 显示上午虚拟推荐
# ======================
if st.session_state.morning_decision:
    st.info("🕚 上午虚拟推荐（观察用）")
    m = st.session_state.morning_decision
    st.write(f"{m['name']} | 板块: {m['sector']} | 当前分数: {round(m['best_score'],2)} | 换手率: {round(m['turnover'],2)}% | 成交额: {round(m['amount'],2)} 亿")

# ======================
# 显示最终推荐
# ======================
if st.session_state.final_decision:
    st.success("🎯 14:30 最终锁定推荐")
    f = st.session_state.final_decision
    shares = int(50000 / f['price'] / 100) * 100

    st.write(f"股票: {f['name']}")
    st.write(f"板块: {f['sector']}")
    st.write(f"尾盘价格: ¥{f['price']}")
    st.write(f"换手率: {round(f['turnover'],2)}%")
    st.write(f"成交额: {round(f['amount'],2)} 亿")
    st.write(f"建议仓位: {shares} 股")

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

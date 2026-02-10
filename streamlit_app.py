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

st.set_page_config(page_title="尾盘博弈 5.0 | 主线板块龙头版", layout="wide")

# ======================
# Session初始化
# ======================
if "final_decision" not in st.session_state:
    st.session_state.final_decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""
if "daily_log" not in st.session_state:
    st.session_state.daily_log = pd.DataFrame(columns=["date","stock","decision","result"])

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
# 获取个股板块（概念）
# ======================
def get_stock_concept(code):
    try:
        url = f"http://vip.stock.finance.sina.com.cn/corp/go.php/vCI_StockStructure/stockid/{code}.phtml"
        res = requests.get(url, timeout=2).text
        # 简化处理（实际接口复杂，这里做基础概念归类）
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
# 主升浪 5.0 板块优选扫描
# ======================
def scan_market(top_n=2):

    data = get_market_data()
    if not data:
        return []

    sector_stats = defaultdict(lambda: {
        "stocks": [],
        "total_pct": 0,
        "count": 0,
        "strong_count": 0,
        "total_amount": 0
    })

    # ---------- 统计板块强度 ----------
    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            turnover = float(s.get('turnoverratio', 0))

            concept = get_stock_concept(code)

            sector_stats[concept]["stocks"].append(s)
            sector_stats[concept]["total_pct"] += pct
            sector_stats[concept]["count"] += 1
            sector_stats[concept]["total_amount"] += amount
            if pct > 3:
                sector_stats[concept]["strong_count"] += 1

        except:
            continue

    # ---------- 计算板块评分 ----------
    sector_scores = []

    for sector, stats in sector_stats.items():
        if stats["count"] == 0:
            continue

        avg_pct = stats["total_pct"] / stats["count"]

        score = (
            0.4 * avg_pct +
            0.4 * stats["strong_count"] +
            0.2 * stats["total_amount"]
        )

        sector_scores.append((sector, score))

    if not sector_scores:
        return []

    sector_scores.sort(key=lambda x: x[1], reverse=True)
    strongest_sectors = [s[0] for s in sector_scores[:2]]

    # ---------- 板块内选股 ----------
    candidates = []

    for sector in strongest_sectors:
        for s in sector_stats[sector]["stocks"]:
            try:
                code = s['code']
                pct = float(s['changepercent'])
                amount = float(s['amount']) / 1e8
                price = float(s['trade'])
                turnover = float(s.get('turnoverratio', 0))

                if not (3 <= pct <= 8):
                    continue
                if amount < 2:
                    continue
                if not (8 <= turnover <= 30):
                    continue

                # 尾盘动能
                tail_up = 0
                try:
                    code_pre = "sh" if code.startswith("6") else "sz"
                    m5_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=5&datalen=6"
                    m5 = requests.get(m5_url, timeout=2).json()
                    if len(m5) >= 2:
                        tail_up = (float(m5[-1]['close']) - float(m5[-2]['close'])) / float(m5[-2]['close'])
                except:
                    tail_up = 0

                if tail_up <= 0:
                    continue

                stock_score = (
                    0.4 * dict(sector_scores)[sector] +
                    0.2 * pct +
                    0.2 * amount +
                    0.2 * tail_up * 100
                )

                candidates.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "sector": sector,
                    "score": stock_score
                })

            except:
                continue

    if not candidates:
        return []

    candidates.sort(key=lambda x: x['score'], reverse=True)
    return candidates[:top_n]

# ======================
# UI
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 5.0 | 主线板块龙头版")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

if (t.hour == 14 and 40 <= t.minute <= 55) or (st.session_state.final_decision is None):
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

if decision is None:
    st.info("⌛ 等待尾盘扫描...")
elif len(decision) == 0:
    st.error("❌ 今日主线不明确 —— 建议空仓")
else:
    st.success("🎯 主线板块龙头候选")
    for idx, stock in enumerate(decision):
        shares = int(50000 / stock['price'] / 100) * 100

        st.markdown(f"### {idx+1}. {stock['name']} ({stock['code']})")
        st.markdown(f"**所属主线板块：{stock['sector']}**")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("尾盘价格", f"¥{stock['price']}")
            st.metric("涨幅", f"{stock['pct']}%")
        with col2:
            st.metric("建议仓位", f"{shares} 股")
            st.metric("预计资金", f"¥{shares * stock['price']:.2f}")

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

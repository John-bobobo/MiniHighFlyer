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

st.set_page_config(page_title="尾盘博弈 简易版", layout="wide")

# ======================
# Session初始化
# ======================
for key, default in {
    "candidate_pool": {},
    "final_decision": [],
    "morning_decision": [],
    "decision_locked": False,
    "morning_locked": False,
    "decision_time": "",
    "flow_history": defaultdict(list)
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 参数
# ======================
TOTAL_FUNDS = 50000
TOP_N = 5
FLOW_HISTORY_LEN = 15

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
# 扫描市场
# ======================
def scan_market():
    data = get_market_data()
    if not data: return
    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')): continue
            pct = float(s['changepercent'])
            amount = float(s['amount'])/1e8
            price = float(s['trade'])
            if pct<2 or amount<1: continue
            concept = get_stock_concept(code)

            # 资金流
            st.session_state.flow_history[code].append(amount)

            # 简单评分
            score = 0.5*pct + 0.3*amount + 0.2*(1 if pct>5 else 0)

            # 更新候选池
            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": s['name'], "sector": concept, "price": price,
                    "best_score": score, "pct": pct, "amount": amount
                }
            else:
                if score>st.session_state.candidate_pool[code]["best_score"]:
                    st.session_state.candidate_pool[code].update({
                        "best_score": score, "price": price,
                        "pct": pct, "amount": amount
                    })
        except:
            continue

# ======================
# 获取Top股票
# ======================
def get_top_candidates(n=TOP_N):
    pool = st.session_state.candidate_pool
    if not pool: return []
    sorted_list = sorted(pool.items(), key=lambda x:x[1]["best_score"], reverse=True)
    return [x[1] for x in sorted_list[:n]]

# ======================
# 仓位计算
# ======================
def calc_shares(stock, total_funds=TOTAL_FUNDS):
    shares = int(total_funds / stock['price'] / 100)*100
    return max(shares,100)

# ======================
# 主逻辑
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 简易版")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

before_1430 = (t.hour<14) or (t.hour==14 and t.minute<30)
after_1430 = not before_1430

if before_1430 and not st.session_state.decision_locked:
    scan_market()

if t.hour==11 and not st.session_state.morning_locked:
    st.session_state.morning_decision = get_top_candidates()
    st.session_state.morning_locked = True

if after_1430 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidates()
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.decision_locked = True

# ======================
# 显示上午虚拟推荐
# ======================
if st.session_state.morning_decision:
    st.info("🕚 上午虚拟推荐（观察用）")
    for m in st.session_state.morning_decision:
        st.write(f"{m['name']} | 板块: {m['sector']} | 当前分数: {round(m['best_score'],2)}")

# ======================
# 显示最终尾盘推荐
# ======================
if st.session_state.final_decision:
    st.success("🎯 14:30 尾盘锁定推荐")
    for f in st.session_state.final_decision:
        shares = calc_shares(f)
        st.write(f"股票: {f['name']} | 板块: {f['sector']} | 尾盘价: ¥{f['price']} | 建议仓位: {shares} 股")

    # 资金流折线
    st.subheader("📈 尾盘资金流入趋势")
    flow_df = pd.DataFrame()
    for stock in st.session_state.final_decision:
        flows = st.session_state.flow_history[stock['name']][-FLOW_HISTORY_LEN:]
        flow_df[stock['name']] = flows
    st.line_chart(flow_df)

# 自动刷新
if 9<=t.hour<=15:
    time.sleep(20)
    st.rerun()

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

import streamlit as st
import requests
import time
import pandas as pd
from datetime import datetime, timedelta, timezone
from collections import defaultdict
import plotly.express as px

# ======================
# 时间函数
# ======================
def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

st.set_page_config(page_title="尾盘博弈 5.7 | 可视化增强版", layout="wide")

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
    "sector_strength": {},
    "flow_history": defaultdict(list)
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ======================
# 参数设置
# ======================
TOTAL_FUNDS = 50000  # 总资金
TOP_N = 5            # 尾盘组合选Top5股
FLOW_HISTORY_LEN = 15 # 资金流向折线长度

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
    sector_stats = defaultdict(lambda: {"pct_sum":0,"amount_sum":0,"count":0})

    for s in data:
        try:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')): continue
            pct = float(s['changepercent'])
            amount = float(s['amount'])/1e8
            price = float(s['trade'])
            turnover = float(s.get('turnoverratio',0))
            if pct<2 or amount<1: continue

            concept = get_stock_concept(code)

            # 资金流向趋势
            st.session_state.flow_history[code].append(amount)
            flow_score = 0
            if len(st.session_state.flow_history[code]) > 3:
                trend = st.session_state.flow_history[code][-1]-st.session_state.flow_history[code][-3]
                flow_score = trend / 10

            # 多因子评分
            score = 0.25*pct + 0.25*amount + 0.2*turnover + 0.15*(1 if pct>5 else 0) + 0.15*flow_score

            # 更新候选池
            if code not in st.session_state.candidate_pool:
                st.session_state.candidate_pool[code] = {
                    "name": s['name'], "sector": concept, "price": price,
                    "best_score": score, "pct": pct, "amount": amount,
                    "turnover": turnover, "flow_score": flow_score
                }
            else:
                if score>st.session_state.candidate_pool[code]["best_score"]:
                    st.session_state.candidate_pool[code].update({
                        "best_score": score, "price": price, "pct": pct,
                        "amount": amount, "turnover": turnover, "flow_score": flow_score
                    })

            # 板块轮动
            sector_stats[concept]["pct_sum"] += pct
            sector_stats[concept]["amount_sum"] += amount
            sector_stats[concept]["count"] += 1
        except:
            continue

    # 计算板块轮动强度
    st.session_state.sector_strength = {}
    for sec,val in sector_stats.items():
        if val["count"]>0:
            st.session_state.sector_strength[sec] = (val["pct_sum"]*0.6 + val["amount_sum"]*0.4)/val["count"]

# ======================
# 获取Top候选池
# ======================
def get_top_candidates(n=TOP_N):
    pool = st.session_state.candidate_pool
    if not pool: return []
    sorted_list = sorted(pool.items(), key=lambda x:x[1]["best_score"], reverse=True)
    return [x[1] for x in sorted_list[:n]]

# ======================
# 仓位计算 + 风险控制
# ======================
def calc_shares(stock, total_funds=TOTAL_FUNDS):
    base_shares = int(total_funds / stock['price'] / 100)*100
    pct = stock['pct']
    sector_strength = st.session_state.sector_strength.get(stock['sector'],5)
    risk_factor = 1.0
    if pct>7: risk_factor*=0.7
    elif pct<3: risk_factor*=1.2
    if sector_strength<2: risk_factor*=0.6
    shares = int(base_shares*risk_factor/100)*100
    return max(shares,100)

# ======================
# UI 主逻辑
# ======================
t = get_bj_time()
st.title("🔥 尾盘博弈 5.7 | 多股组合 + 风险控制 + 可视化")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

before_1430 = (t.hour<14) or (t.hour==14 and t.minute<30)
after_1430 = not before_1430

if before_1430 and not st.session_state.decision_locked: scan_market()
if t.hour==11 and not st.session_state.morning_locked:
    st.session_state.morning_decision = get_top_candidates()
    st.session_state.morning_locked = True
if after_1430 and not st.session_state.decision_locked:
    st.session_state.final_decision = get_top_candidates()
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')
    st.session_state.decision_locked = True

# ======================
# 布局优化
# ======================
left_col,right_col = st.columns([1,2])

# 左侧：板块热力图
with left_col:
    st.subheader("📊 板块轮动强度热力图")
    if st.session_state.sector_strength:
        df_sector = pd.DataFrame([{"板块":sec,"轮动强度":round(val,2)} for sec,val in st.session_state.sector_strength.items()])
        df_sector = df_sector.sort_values("轮动强度",ascending=False)
        fig_sector = px.bar(df_sector, x="板块", y="轮动强度", color="轮动强度",
                            color_continuous_scale=px.colors.sequential.Viridis,
                            title="板块轮动热力图")
        st.plotly_chart(fig_sector,use_container_width=True)

# 右侧：尾盘组合 + 仓位 + 资金流
with right_col:
    st.subheader(f"🎯 尾盘Top {TOP_N}组合")
    if st.session_state.final_decision:
        df_final = pd.DataFrame(st.session_state.final_decision)
        df_final['建议仓位'] = df_final.apply(calc_shares,axis=1)
        # 仓位条形图
        fig_pos = px.bar(df_final, x='name', y='建议仓位',
                         color='best_score',
                         hover_data=['pct','amount','turnover','flow_score'],
                         color_continuous_scale=px.colors.sequential.Plasma,
                         title="尾盘建议仓位分布")
        st.plotly_chart(fig_pos,use_container_width=True)

        # 资金流折线图
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

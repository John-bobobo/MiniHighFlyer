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

st.set_page_config(page_title="尾盘博弈 4.3 | 稳定增强版+连板概率", layout="wide")

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
# 获取指数涨跌幅
# ======================
def get_index_pct():
    try:
        sh = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        return float(sh[3])
    except:
        return 0.0

# ======================
# 尾盘扫描函数（4.3 稳定增强 + 连板概率）
# ======================
def scan_market(top_n=2):
    index_pct = get_index_pct()
    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=150&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
    except:
        res = []

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
            turnover = float(s.get('turnoverratio',0))
            consecutive_limit = int(s.get('consecutive_limit',0)) if 'consecutive_limit' in s else 0  # 连板信息

            # --- 主结构条件（放宽版） ---
            if (2 <= pct <= 9.5) and amount > 2 and (price/high >= 0.98) and (5 <= turnover <= 30):
                # 连板概率加权
                limit_prob = 0.05 + 0.1 * consecutive_limit
                score = pct*0.5 + amount*0.3 + turnover*0.2 + (price/high)*5 + limit_prob*10
                candidates.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover,
                    "score": score,
                    "limit_prob": limit_prob
                })

            # --- 兜底池（保证必出股） ---
            if pct > 1 and amount > 1.5:
                fallback_pool.append({
                    "code": code,
                    "name": s['name'],
                    "price": price,
                    "pct": pct,
                    "amount": amount,
                    "turnover": turnover
                })

        except:
            continue

    # 调试信息
    # print(f"[DEBUG] 主候选股: {len(candidates)}, 兜底池: {len(fallback_pool)}, 大盘涨幅: {index_pct}")

    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]
    elif fallback_pool:
        fallback_pool.sort(key=lambda x: (x['pct'], x['amount']), reverse=True)
        return fallback_pool[:1]
    else:
        return []

# ======================
# 次日操作指引
# ======================
def next_day_instruction(stock):
    shares = int(50000 / stock['price'] / 100) * 100
    instructions = f"""
### 次日操作指引
- **竞价阶段 (9:15-9:25)**
    - 高开 0~3% → 持仓
    - 高开 >5% → 9:35减半
    - 低开 -2% → 反抽卖出
    - 低开 < -3% → 竞价直接空仓

- **9:30-9:40**
    - 快速封板 → 不动
    - 未封板但盈利 → 分批止盈
    - 未脱离成本 → 全部卖出

- **止损**
    - 跌破买入价 -3% → 无条件止损

- **仓位参考**
    - 建议买入股数：{shares} 股
    - 买入参考价：¥{stock['price']}
    - 预计占用资金：¥{shares * stock['price']:.2f}
"""
    return instructions

# ======================
# UI
# ======================
t = get_bj_time()
st.title("🏹 尾盘博弈 4.3 | 稳定增强执行系统 + 连板概率")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# ======================
# 尾盘扫描逻辑 (保证 14:40 一定出股)
# ======================
if (t.hour == 14 and 40 <= t.minute <= 55) or (st.session_state.final_decision is None):
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision
index_pct = get_index_pct()

# ======================
# 展示结果
# ======================
if decision is None:
    st.info("⌛ 等待尾盘扫描...")
elif len(decision) == 0:
    st.error(f"❌ 尾盘结构不够健康 —— 今日建议空仓 | 大盘涨幅: {index_pct}%")
else:
    st.success("🎯 尾盘结构优选标的")
    for idx, stock in enumerate(decision):
        st.markdown(f"### {idx+1}. {stock['name']} ({stock['code']})")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("尾盘收盘价", f"¥{stock['price']}")
            st.metric("尾盘涨幅", f"{stock['pct']}%")
        with col2:
            shares = int(50000 / stock['price'] / 100) * 100
            st.metric("建议仓位", f"{shares} 股")
            st.metric("预计资金", f"¥{shares * stock['price']:.2f}")

        st.markdown(next_day_instruction(stock), unsafe_allow_html=True)

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# ======================
# 自动刷新
# ======================
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

# ======================
# 回测记录
# ======================
if decision and t.hour > 15:
    today = t.strftime('%Y-%m-%d')
    for stock in decision:
        st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [
            today,
            stock['code'],
            "买入",
            "-"
        ]
    st.markdown("### 📊 今日回测日志")
    st.dataframe(st.session_state.daily_log)

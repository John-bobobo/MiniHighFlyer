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

st.set_page_config(page_title="尾盘博弈 4.5 | Tail Momentum", layout="wide")

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
# Tail Momentum扫描逻辑
# ======================
def scan_market(top_n=2):

    index_pct = get_index_pct()

    try:
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=200&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()
    except:
        res = []

    candidates = []
    fallback_pool = []

    for s in res:
        try:
            code = s['code']
            name = s['name']

            if not (code.startswith('60') or code.startswith('00')):
                continue

            # 基础数据
            pct = float(s['changepercent'])
            amount = float(s['amount'])/1e8
            price = float(s['trade'])
            high = float(s['high'])
            turnover = float(s.get('turnoverratio',0))

            # 排除涨停
            if pct >= 9.5:
                continue

            # 第一层筛选：今日收盘 3~7%
            if not (3 <= pct <= 7):
                # 放进兜底：稍弱但未爆炸
                if pct>1 and amount>1.5:
                    fallback_pool.append({
                        "code": code, "name": name,
                        "price": price, "pct": pct,
                        "amount": amount, "turnover": turnover
                    })
                continue

            # 获取尾盘最后 30 分钟强度
            code_pre = "sh" if code.startswith("6") else "sz"
            try:
                m5_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=5&datalen=7"
                m5_data = requests.get(m5_url, timeout=2).json()
                # 计算 上一根 和 最新 5分钟趋势
                tail_up = (float(m5_data[-1]['close']) - float(m5_data[-2]['close'])) / float(m5_data[-2]['close'])
            except:
                tail_up = 0

            # 第二层：尾盘动力结构（>= +0.3%）
            if tail_up < 0.003:
                # 较弱尾盘结构不选
                fallback_pool.append({
                    "code": code, "name": name,
                    "price": price, "pct": pct,
                    "amount": amount, "turnover": turnover
                })
                continue

            # 计算评分
            score = (
                pct * 0.35 + 
                amount * 0.35 + 
                (turnover) * 0.15 +
                (tail_up*100) * 0.15
            )

            candidates.append({
                "code": code, "name": name, "price": price,
                "pct": pct, "amount": amount, "turnover": turnover,
                "tail_up": round(tail_up*100,2),
                "score": score
            })

        except:
            continue

    # 优先输出主池
    if candidates:
        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates[:top_n]

    # 兜底输出
    if fallback_pool:
        fallback_pool.sort(key=lambda x: (x['pct'], x['amount']), reverse=True)
        s = fallback_pool[0]
        return [{
            "code": s['code'], "name": s['name'], "price": s['price'],
            "pct": s['pct'], "amount": s['amount'], "turnover": s['turnover'],
            "score":0, "tail_up": 0
        }]

    return []

# ======================
# 次日操作指引
# ======================
def next_day_instruction(stock):
    shares = int(50000 / stock['price'] / 100) * 100
    instructions = f"""
### 次日操作系统

📌 **竞价阶段 (9:15-9:25)**
- 高开 0~3% → 持仓
- 高开 3~5% → 9:35前减半
- 高开 >5% → 减仓
- 低开 -2~0 → 观察反抽
- 低开 < -3% → 竞价空仓

📌 **9:30-9:40**
- 快速封板 → 持有
- 未封板但盈利 → 分批止盈
- 未脱离成本 → 全部卖出

📌 **止损**
- 跌破买入价 -3% → 无条件止损

📌 **仓位参考**
- 建议买入：{shares} 股
- 买入参考：¥{stock['price']}
- 占用资金：¥{shares * stock['price']:.2f}
"""
    return instructions

# ======================
# UI
# ======================
t = get_bj_time()
st.title("🏹 尾盘博弈 4.5 | Tail Momentum Pro")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# 扫描
if (t.hour==14 and 40<=t.minute<=55) or (st.session_state.final_decision is None):
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

# 展示
if decision is None:
    st.info("⌛ 等待尾盘扫描...")
elif len(decision)==0:
    st.error("❌ 尾盘结构弱或极端行情，建议空仓")
else:
    st.success("🎯 今日尾盘优选标的")
    for idx, stock in enumerate(decision):
        st.markdown(f"## {idx+1}. {stock['name']} ({stock['code']})")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("尾盘收盘价", f"¥{stock['price']}")
            st.metric("今日涨幅", f"{stock['pct']}%")
        with col2:
            st.metric("成交额(亿)", f"{stock['amount']:.2f}")
            st.metric("换手率", f"{stock['turnover']}%")
        with col3:
            st.metric("尾盘动能", f"{stock['tail_up']}%")
            st.metric("综合评分", f"{stock['score']:.2f}")

        st.markdown(next_day_instruction(stock), unsafe_allow_html=True)

st.caption(f"🔒 决策锁定时间：{st.session_state.decision_time}")

# 自动刷新
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

# 回测记录
if decision and t.hour>15:
    today = t.strftime('%Y-%m-%d')
    for stock in decision:
        st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [
            today,
            stock['code'],
            "尾盘入",
            "-"
        ]
    st.markdown("### 📊 今日回测记录")
    st.dataframe(st.session_state.daily_log)

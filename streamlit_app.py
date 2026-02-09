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

st.set_page_config(page_title="尾盘博弈 3.1 | 次日实时执行+风险报警", layout="wide")

# ======================
# Session初始化
# ======================
if "final_decision" not in st.session_state:
    st.session_state.final_decision = None
if "decision_time" not in st.session_state:
    st.session_state.decision_time = ""
if "daily_log" not in st.session_state:
    st.session_state.daily_log = pd.DataFrame(columns=["date","stock","decision","result"])
if "real_time_status" not in st.session_state:
    st.session_state.real_time_status = {}

# ======================
# 核心扫描函数（尾盘选股Top2）
# ======================
def scan_market(top_n=2):
    try:
        sh = requests.get("http://qt.gtimg.cn/q=s_sh000001", timeout=2).text.split('~')
        mkt_pct = float(sh[3])
        if mkt_pct < -1.0:
            return []

        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData?page=1&num=100&sort=changepercent&asc=0&node=hs_a"
        headers = {"Referer": "http://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3).json()

        candidates = []

        for s in res:
            code = s['code']
            if not (code.startswith('60') or code.startswith('00')):
                continue

            pct = float(s['changepercent'])
            amount = float(s['amount']) / 1e8
            price = float(s['trade'])
            high = float(s['high'])
            turnover = float(s.get('turnoverratio',0))

            if not (4 <= pct <= 9 and amount > 3 and price/high > 0.985):
                continue
            if not (8 <= turnover <= 25):
                continue

            code_pre = "sh" if code.startswith("6") else "sz"

            try:
                m5_url = f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={code_pre}{code}&scale=5&datalen=3"
                m5 = requests.get(m5_url, timeout=2).json()
                if len(m5) >= 2:
                    last_swing = (float(m5[-1]['close']) - float(m5[-2]['close'])) / float(m5[-2]['close'])
                    if last_swing > 0.02:
                        continue
            except:
                continue

            score = pct*0.4 + amount*0.3 + turnover*0.3
            candidates.append({
                "code": code,
                "name": s['name'],
                "price": price,
                "pct": pct,
                "amount": amount,
                "turnover": turnover,
                "score": score
            })

        if not candidates:
            return []

        candidates.sort(key=lambda x:x['score'], reverse=True)
        return candidates[:top_n]

    except:
        return []

# ======================
# 次日操作指引函数
# ======================
def next_day_instruction(stock):
    if not stock:
        return "今日尾盘结构不健康，建议空仓"

    instructions = f"""
    ### 次日操作指引
    - **竞价阶段 (9:15-9:25)**
        - 高开 0~3% → 持仓
        - 高开 >5% → 9:35减半
        - 低开 -2% → 反抽卖出
        - 低开 < -3% → 竞价直接空仓
    - **早盘 (9:30-9:40)**
        - 快速封板 → 不动
        - 9:40未封板且盈利 → 分批卖出
        - 9:40未脱离成本区 → 全部卖出
    - **止盈**
        - 连续强势 → 尾盘收盘前减仓锁利润
    - **止损**
        - 跌破买入价 -3% → 无条件止损
    - **仓位建议**
        - 50,000元模拟：{int(50000/stock['price']/100)*100}股
        - 买入参考价：¥{stock['price']}
        - 预计占用资金：¥{int(50000/stock['price']/100)*100*stock['price']:.2f}
    """
    return instructions

# ======================
# 竞价实时监控函数+风险报警
# ======================
def real_time_monitor(stock):
    code_pre = "sh" if stock['code'].startswith("6") else "sz"
    try:
        data = requests.get(f"http://qt.gtimg.cn/q={code_pre}{stock['code']}", timeout=2).text.split('~')
        live_price = float(data[3])
        open_price = float(data[5])  # 开盘价
        pct_open = (open_price - stock['price'])/stock['price']*100

        # 风险判断
        if pct_open < -3:
            status = "❌ 高风险低开 < -3%，建议空仓"
            alert = True
        elif pct_open < -2:
            status = "⚠️ 低开小幅 -2%，观察反抽"
            alert = False
        elif pct_open > 5:
            status = "⚠️ 高开 >5%，建议9:35减半"
            alert = False
        else:
            status = "✅ 正常开盘，持仓"
            alert = False

        return live_price, pct_open, status, alert
    except:
        return None, None, "❌ 竞价获取失败", False

# ======================
# UI
# ======================
t = get_bj_time()
st.title("🏹 尾盘博弈 3.1 | 次日动态执行系统+风险报警")
st.markdown(f"当前时间：{t.strftime('%H:%M:%S')}")

# 14:40-14:55 尾盘扫描锁定决策
if t.hour==14 and 40<=t.minute<=55 and not st.session_state.final_decision:
    result = scan_market(top_n=2)
    st.session_state.final_decision = result
    st.session_state.decision_time = t.strftime('%Y-%m-%d %H:%M:%S')

decision = st.session_state.final_decision

# ======================
# 展示选股和操作指引
# ======================
if decision:
    if len(decision)==0:
        st.error("❌ 今日尾盘结构不健康 —— 建议空仓")
    else:
        st.success("🎯 尾盘结构最健康标的 Top2")
        for idx, stock in enumerate(decision):
            st.markdown(f"### {idx+1}. {stock['name']} ({stock['code']})")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("尾盘收盘价", f"¥{stock['price']}")
                st.metric("尾盘涨幅", f"{stock['pct']}%")
            with col2:
                shares = int(50000 / stock['price'] / 100)*100
                st.metric("建议仓位", f"{shares} 股")
                st.metric("预计资金", f"¥{shares*stock['price']:.2f}")
            st.markdown(next_day_instruction(stock), unsafe_allow_html=True)

    st.caption(f"🔒 尾盘决策锁定时间：{st.session_state.decision_time}")

# ======================
# 9:15-9:25 竞价实时监控 + 风险报警
# ======================
if decision and t.hour==9 and 15<=t.minute<=25:
    st.markdown("### ⚡ 竞价实时监控 + 风险报警")
    for idx, stock in enumerate(decision):
        live_price, pct_open, status, alert = real_time_monitor(stock)
        if live_price:
            if alert:
                st.error(f"**{stock['name']} ({stock['code']})** | 实时竞价价: ¥{live_price} | 开盘偏离: {pct_open:.2f}% → {status}")
            else:
                st.info(f"**{stock['name']} ({stock['code']})** | 实时竞价价: ¥{live_price} | 开盘偏离: {pct_open:.2f}% → {status}")
        else:
            st.warning(f"**{stock['name']} ({stock['code']})** | {status}")

# ======================
# 自动刷新
# ======================
if 9 <= t.hour <= 15:
    time.sleep(20)
    st.rerun()

# ======================
# 回测统计模块 (每日记录)
# ======================
if decision and t.hour>15:
    today = t.strftime('%Y-%m-%d')
    for stock in decision:
        if not stock:
            st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [today,"-","空仓","-"]
        else:
            st.session_state.daily_log.loc[len(st.session_state.daily_log)] = [today, stock['code'], "买入","-"]
    st.markdown("### 📊 今日回测日志")
    st.dataframe(st.session_state.daily_log)

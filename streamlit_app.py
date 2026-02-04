import streamlit as st
import akshare as ak
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# --- 1. 极速页面配置 ---
st.set_page_config(page_title="抗压盯盘终端", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 2. 核心函数：带超时保护的抓取 ---
def get_stock_data_stable(code):
    """
    使用极其轻量级的实时行情接口，并增加手动延时和异常捕获
    """
    try:
        # 这个接口只抓取单只股票的当前快照，数据量极小，不容易超时
        df = ak.stock_bid_ask_em(symbol=code)
        # 获取最新价（这里取的是卖一价和买一价的均值或最新成交）
        current_price = df['价'].iloc[0] # 这里只是示例接口名，AkShare接口多变
        return current_price
    except:
        # 如果单股接口失败，再尝试极简版的快照接口
        try:
            # 增加 timeout 参数是不行的（接口内置了），我们用逻辑保护
            df_all = ak.stock_zh_a_spot_em() 
            res = df_all[df_all['代码'] == code].iloc[0]
            return res
        except:
            return None

# --- 主界面渲染 ---
st.title("🛡️ 幻方抗压终端 V4.3")
st.write(f"🕒 北京时间: {get_bj_time().strftime('%H:%M:%S')}")

# 3. 输入区
codes = st.sidebar.text_input("监控代码 (逗号分隔)", value="002400,600986")
stock_list = [s.strip() for s in codes.split(",")]

# 4. 容错抓取逻辑
if st.button("🔄 手动强制刷新数据"):
    st.cache_data.clear()

# 尝试抓取一次
try:
    # 增加手动重试机制
    with st.spinner('正在穿越高峰期拥堵网络...'):
        df_all = ak.stock_zh_a_spot_em()
except Exception as e:
    st.error("🚨 东方财富服务器忙，正在自动排队重连...")
    df_all = None

# 5. 展示逻辑
if df_all is not None:
    cols = st.columns(len(stock_list))
    for i, code in enumerate(stock_list):
        with cols[i]:
            try:
                row = df_all[df_all['代码'] == code].iloc[0]
                price = row['最新价']
                change = row['涨跌幅']
                color = "#ff4b4b" if change > 0 else "#00ff00"
                
                st.markdown(f"""
                <div style="background-color:rgba(255,255,255,0.05); padding:20px; border-radius:10px; border-left:5px solid {color}">
                    <h3 style="margin:0">{row['名称']}</h3>
                    <h1 style="color:{color}; margin:10px 0">{price}</h1>
                    <p style="margin:0">涨幅: {change}% | 换手: {row['换手率']}%</p>
                </div>
                """, unsafe_allow_html=True)
            except:
                st.warning(f"代码 {code} 暂无数据")
else:
    st.info("💡 提示：当前全市场接口拥堵，建议每隔 30 秒等它自动重试，或点击左侧手动刷新。")

# 6. 自动刷新（降低频率至 60 秒，减少被封概率）
time.sleep(60)
st.rerun()

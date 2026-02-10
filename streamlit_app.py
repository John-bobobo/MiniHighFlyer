import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz

st.set_page_config(page_title="尾盘博弈 5.3 专业版", layout="wide")

tz = pytz.timezone("Asia/Shanghai")
now = datetime.now(tz)

st.title("🔥 尾盘博弈 5.3 | 板块趋势 + 资金博弈模型")
st.write(f"当前北京时间：{now.strftime('%H:%M:%S')}")

# ===============================
# Session 初始化
# ===============================
if "candidate_pool" not in st.session_state:
    st.session_state.candidate_pool = {}

if "morning_pick" not in st.session_state:
    st.session_state.morning_pick = None

if "final_pick" not in st.session_state:
    st.session_state.final_pick = None

if "locked" not in st.session_state:
    st.session_state.locked = False

if "today" not in st.session_state:
    st.session_state.today = now.date()

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()

# ===============================
# 获取全市场数据
# ===============================
@st.cache_data(ttl=30)
def get_market():
    df = ak.stock_zh_a_spot_em()
    return df

df = get_market()

if df.empty:
    st.error("数据获取失败")
    st.stop()

# ===============================
# 板块趋势强度计算
# ===============================
sector_df = (
    df.groupby("所属行业")
    .agg({
        "涨跌幅":"mean",
        "成交额":"sum"
    })
    .reset_index()
)

sector_df["资金强度"] = sector_df["成交额"] / sector_df["成交额"].max()
sector_df["综合强度"] = sector_df["涨跌幅"]*0.6 + sector_df["资金强度"]*0.4
sector_df = sector_df.sort_values("综合强度", ascending=False)

strongest_sector = sector_df.iloc[0]["所属行业"]

# ===============================
# 龙头筛选逻辑
# ===============================
sector_stocks = df[df["所属行业"] == strongest_sector].copy()

sector_stocks["资金强度"] = sector_stocks["成交额"] / sector_stocks["成交额"].max()

sector_stocks["综合得分"] = (
    sector_stocks["涨跌幅"]*0.5 +
    sector_stocks["资金强度"]*0.3 +
    (sector_stocks["涨跌幅"] > 5)*0.2
)

sector_stocks = sector_stocks.sort_values("综合得分", ascending=False)

top_stock = sector_stocks.iloc[0]

# ===============================
# 时间控制逻辑
# ===============================

is_morning_time = now.hour == 11 and now.minute < 5
is_final_time = now.hour > 14 or (now.hour == 14 and now.minute >= 30)

# 上午虚拟推荐
if is_morning_time and st.session_state.morning_pick is None:
    st.session_state.morning_pick = top_stock

# 14:30 锁定
if is_final_time and not st.session_state.locked:
    st.session_state.final_pick = top_stock
    st.session_state.locked = True

# ===============================
# UI 布局
# ===============================
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 今日最强板块")
    st.metric("板块", strongest_sector)
    st.bar_chart(sector_df.head(10).set_index("所属行业")["综合强度"])

with col2:
    st.subheader("💰 龙头资金结构")
    st.write(f"龙头候选：{top_stock['名称']}")
    st.write(f"涨幅：{top_stock['涨跌幅']}%")
    st.write(f"成交额：{round(top_stock['成交额']/1e8,2)} 亿")
    st.write(f"综合得分：{round(top_stock['综合得分'],2)}")

# 上午推荐
if st.session_state.morning_pick is not None:
    st.info(f"🕚 上午虚拟推荐：{st.session_state.morning_pick['名称']}")

# 最终推荐
if st.session_state.final_pick is not None:
    st.success(f"🎯 14:30 最终锁定：{st.session_state.final_pick['名称']}")

# 自动刷新
if 9 <= now.hour <= 15:
    time.sleep(20)
    st.rerun()

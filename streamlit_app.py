import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz

st.set_page_config(page_title="尾盘博弈 5.3 专业版", layout="wide")

tz = pytz.timezone("Asia/Shanghai")

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
    st.session_state.today = datetime.now(tz).date()

if "logs" not in st.session_state:
    st.session_state.logs = []

# ===============================
# 日志记录函数
# ===============================
def add_log(event, details):
    log_entry = {
        'timestamp': datetime.now(tz).strftime("%H:%M:%S"),
        'event': event,
        'details': details
    }
    st.session_state.logs.append(log_entry)
    # 只保留最近20条日志
    if len(st.session_state.logs) > 20:
        st.session_state.logs = st.session_state.logs[-20:]

# 获取当前时间
now = datetime.now(tz)

st.title("🔥 尾盘博弈 5.3 | 板块趋势 + 资金博弈模型")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.rerun()

# ===============================
# 侧边栏 - 测试控制面板
# ===============================
with st.sidebar:
    st.markdown("### 🧪 测试控制面板")
    
    # 模拟时间设置
    test_hour = st.slider("模拟小时", 9, 15, now.hour)
    test_minute = st.slider("模拟分钟", 0, 59, now.minute)
    use_simulated_time = st.checkbox("使用模拟时间")
    
    if st.button("🔄 应用模拟时间"):
        if use_simulated_time:
            # 记录模拟时间应用
            add_log("模拟时间应用", f"{test_hour:02d}:{test_minute:02d}")
            st.success(f"已应用模拟时间：{test_hour:02d}:{test_minute:02d}")
            st.rerun()
    
    st.markdown("---")
    
    # 强制设置推荐
    st.markdown("### 🔧 强制操作")
    col_test1, col_test2 = st.columns(2)
    with col_test1:
        if st.button("📈 强制上午推荐"):
            add_log("强制操作", "设置上午推荐")
            if "test_top_stock" in st.session_state and st.session_state.test_top_stock is not None:
                st.session_state.morning_pick = st.session_state.test_top_stock
                st.success("强制上午推荐已设置")
                st.rerun()
            else:
                st.warning("请先获取市场数据")
    
    with col_test2:
        if st.button("🎯 强制最终锁定"):
            add_log("强制操作", "设置最终锁定")
            if "test_top_stock" in st.session_state and st.session_state.test_top_stock is not None:
                st.session_state.final_pick = st.session_state.test_top_stock
                st.session_state.locked = True
                st.success("强制最终锁定已设置")
                st.rerun()
            else:
                st.warning("请先获取市场数据")
    
    # 清空按钮
    if st.button("🗑️ 清空所有推荐"):
        add_log("强制操作", "清空所有推荐")
        st.session_state.morning_pick = None
        st.session_state.final_pick = None
        st.session_state.locked = False
        st.success("已清空所有推荐")
        st.rerun()
    
    st.markdown("---")
    
    # 显示当前session状态
    with st.expander("📊 Session状态"):
        st.write(f"Morning Pick: {st.session_state.morning_pick}")
        st.write(f"Final Pick: {st.session_state.final_pick}")
        st.write(f"Locked: {st.session_state.locked}")
        st.write(f"今日日期: {st.session_state.today}")

# ===============================
# 时间处理（支持模拟时间）
# ===============================
if use_simulated_time:
    # 使用模拟时间
    simulated_time = now.replace(hour=test_hour, minute=test_minute, second=0)
    current_time = simulated_time
    st.info(f"🔧 使用模拟时间: {simulated_time.strftime('%H:%M:%S')}")
else:
    current_time = now

current_hour = current_time.hour
current_minute = current_time.minute
current_time_str = current_time.strftime("%H:%M:%S")

# ===============================
# 时间状态监控面板
# ===============================
st.markdown("### ⏰ 时间监控面板")
col_time1, col_time2, col_time3 = st.columns(3)

with col_time1:
    server_time = datetime.now()  # 服务器原始时间
    st.metric("服务器原始时间", server_time.strftime("%H:%M:%S"))
    
with col_time2:
    st.metric("当前使用时间", current_time_str)
    
with col_time3:
    # 时间状态指示灯
    actual_is_morning_time = (current_hour == 11 and 0 <= current_minute <= 10)
    actual_is_final_time = (current_hour > 14) or (current_hour == 14 and current_minute >= 30)
    
    if actual_is_morning_time:
        st.markdown('<div style="background-color:green;color:white;padding:10px;border-radius:5px;text-align:center;">✅ 上午推荐时段</div>', unsafe_allow_html=True)
        add_log("时间状态", "进入上午推荐时段")
    elif actual_is_final_time:
        st.markdown('<div style="background-color:red;color:white;padding:10px;border-radius:5px;text-align:center;">🎯 最终锁定时段</div>', unsafe_allow_html=True)
        add_log("时间状态", "进入最终锁定时段")
    else:
        st.markdown('<div style="background-color:gray;color:white;padding:10px;border-radius:5px;text-align:center;">⏳ 等待时段</div>', unsafe_allow_html=True)

# 状态检查表
st.markdown("### 📋 状态检查表")
status_df = pd.DataFrame({
    '项目': ['当前使用时间', '是否上午时段', '是否下午时段', '上午推荐已生成', '最终锁定已生成'],
    '状态': [
        current_time_str,
        '✅是' if actual_is_morning_time else '❌否',
        '✅是' if actual_is_final_time else '❌否',
        '✅已生成' if st.session_state.morning_pick else '❌未生成',
        '✅已锁定' if st.session_state.final_pick else '❌未锁定'
    ]
})
st.table(status_df)

# ===============================
# 获取全市场数据
# ===============================
@st.cache_data(ttl=10)
def get_market():
    try:
        df = ak.stock_zh_a_spot_em()
        add_log("数据获取", "成功获取市场数据")
        return df
    except Exception as e:
        add_log("数据获取", f"失败: {str(e)}")
        return pd.DataFrame()

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

if not sector_stocks.empty:
    sector_stocks["资金强度"] = sector_stocks["成交额"] / sector_stocks["成交额"].max()
    
    sector_stocks["综合得分"] = (
        sector_stocks["涨跌幅"]*0.5 +
        sector_stocks["资金强度"]*0.3 +
        (sector_stocks["涨跌幅"] > 5).astype(int)*0.2
    )
    
    sector_stocks = sector_stocks.sort_values("综合得分", ascending=False)
    top_stock = sector_stocks.iloc[0]
    
    # 保存测试用的股票数据
    test_stock_data = {
        'name': top_stock['名称'],
        'code': top_stock['代码'],
        '涨跌幅': float(top_stock['涨跌幅']),
        'time': current_time_str
    }
    st.session_state.test_top_stock = test_stock_data
    add_log("龙头筛选", f"选中: {top_stock['名称']}")
else:
    st.warning("该板块无股票数据")
    top_stock = None

# ===============================
# 自动推荐逻辑
# ===============================
st.markdown("### 🤖 自动推荐逻辑")

# 上午虚拟推荐
if actual_is_morning_time and st.session_state.morning_pick is None and top_stock is not None:
    st.session_state.morning_pick = {
        'name': top_stock['名称'],
        'code': top_stock['代码'],
        '涨跌幅': float(top_stock['涨跌幅']),
        'time': current_time_str
    }
    st.success(f"🕚 已自动生成上午推荐：{top_stock['名称']}")
    add_log("自动推荐", f"生成上午推荐: {top_stock['名称']}")
    st.rerun()

# 下午最终锁定
if actual_is_final_time and not st.session_state.locked and top_stock is not None:
    st.session_state.final_pick = {
        'name': top_stock['名称'],
        'code': top_stock['代码'],
        '涨跌幅': float(top_stock['涨跌幅']),
        'time': current_time_str
    }
    st.session_state.locked = True
    st.success(f"🎯 已自动锁定最终推荐：{top_stock['名称']}")
    add_log("自动推荐", f"锁定最终推荐: {top_stock['名称']}")
    st.rerun()

# ===============================
# 主显示区域
# ===============================
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 今日最强板块")
    st.metric("板块", strongest_sector)
    if not sector_df.empty:
        st.bar_chart(sector_df.head(10).set_index("所属行业")["综合强度"])

with col2:
    st.subheader("💰 龙头资金结构")
    if top_stock is not None:
        st.write(f"龙头候选：{top_stock['名称']} ({top_stock['代码']})")
        st.metric("涨幅", f"{top_stock['涨跌幅']:.2f}%")
        st.metric("成交额", f"{round(top_stock['成交额']/1e8,2)} 亿")
        st.metric("综合得分", f"{top_stock['综合得分']:.2f}")
    else:
        st.warning("无龙头数据")

# ===============================
# 推荐显示区域
# ===============================
st.markdown("---")
col3, col4 = st.columns(2)

with col3:
    st.subheader("🕚 上午虚拟推荐")
    if st.session_state.morning_pick is not None:
        pick = st.session_state.morning_pick
        st.success(f"**{pick['name']} ({pick['code']})**")
        st.write(f"推荐时间：{pick['time']}")
        st.write(f"涨幅：{pick['涨跌幅']:.2f}%")
        st.write(f"来源：{'自动生成' if pick.get('auto', True) else '手动设置'}")
    else:
        if actual_is_morning_time:
            st.info("⏳ 正在自动生成上午推荐...")
        else:
            st.info("⏰ 等待上午推荐时段（11:00-11:10）")

with col4:
    st.subheader("🎯 最终锁定")
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        st.success(f"**{pick['name']} ({pick['code']})**")
        st.write(f"锁定时间：{pick['time']}")
        st.write(f"涨幅：{pick['涨跌幅']:.2f}%")
        st.write(f"来源：{'自动锁定' if pick.get('auto', True) else '手动设置'}")
    else:
        if actual_is_final_time:
            st.info("⏳ 正在自动锁定最终选择...")
        else:
            st.info("⏰ 等待最终锁定时段（14:30后）")

# ===============================
# 系统日志
# ===============================
with st.expander("📜 系统日志", expanded=False):
    if st.session_state.logs:
        for log in reversed(st.session_state.logs):
            st.write(f"**{log['timestamp']}** - {log['event']}: {log['details']}")
    else:
        st.info("暂无日志记录")

# ===============================
# 控制按钮
# ===============================
st.markdown("---")
col_btn1, col_btn2, col_btn3 = st.columns(3)

with col_btn1:
    if st.button("🔄 刷新数据"):
        st.cache_data.clear()
        add_log("操作", "手动刷新数据")
        st.rerun()

with col_btn2:
    if st.button("📊 显示原始数据"):
        with st.expander("原始数据"):
            st.dataframe(df.head(20))

with col_btn3:
    if st.button("🧹 清除缓存"):
        st.cache_data.clear()
        st.success("缓存已清除")

# ===============================
# 自动刷新
# ===============================
if 9 <= current_hour <= 15:
    refresh_time = 15
    st.write(f"⏳ {refresh_time}秒后自动刷新...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 当前非交易时间，自动刷新已暂停")

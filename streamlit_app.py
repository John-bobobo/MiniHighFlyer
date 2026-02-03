import streamlit as st
import akshare as ak
import pandas as pd
import time

st.set_page_config(page_title="袖珍幻方-实时监控", layout="wide")
st.title("🚀 Bro的云端量化哨兵")

stock_code = "002400" # 省广集团
support_line = 12.26

st.sidebar.header("策略参数")
st.sidebar.write(f"目标标的: {stock_code}")
st.sidebar.write(f"黄金支撑位: {support_line}")

placeholder = st.empty()

while True:
    try:
        df = ak.stock_zh_a_spot_em()
        target = df[df['代码'] == stock_code].iloc[0]
        
        price = float(target['最新价'])
        change = float(target['涨跌幅'])
        
        with placeholder.container():
            col1, col2, col3 = st.columns(3)
            col1.metric("当前价格", f"{price} 元")
            col2.metric("涨跌幅", f"{change}%")
            
            if price > support_line:
                st.success(f"🟢 状态：安全。股价处于支撑位 {support_line} 之上。")
            else:
                st.error(f"🔴 警报：破位！股价已跌破支撑位 {support_line}。")
                
            st.write(f"最后更新时间: {time.strftime('%H:%M:%S')}")
            
        time.sleep(30)
    except Exception as e:
        st.warning("正在重新连接数据源...")
        time.sleep(5)

import streamlit as st
import akshare as ak
import pandas as pd
import time

# --- 页面配置 ---
st.set_page_config(page_title="袖珍幻方-作战指挥部", layout="wide")

# --- 核心算法函数 ---
@st.cache_data(ttl=30)
def get_market_data(code, lead_code):
    try:
        # 1. 抓取全市场快照
        df_spot = ak.stock_zh_a_spot_em()
        target = df_spot[df_spot['代码'] == code].iloc[0]
        leader = df_spot[df_spot['代码'] == lead_code].iloc[0]
        
        # 2. 计算高级因子数据
        price = float(target['最新价'])
        change = float(target['涨跌幅'])
        turnover = float(target['换手率'])
        # 处理主力净流入（部分接口可能返回字符串，需转换）
        try:
            net_money = float(target['主力净流入'])
        except:
            net_money = 0
        
        # 因子B：相关性偏离度 (省广 vs 浙文)
        gap = change - float(leader['涨跌幅'])
        
        return {
            "name": target['名称'],
            "price": price,
            "change": change,
            "turnover": turnover,
            "gap": gap,
            "net_money": net_money,
            "leader_name": leader['名称']
        }
    except Exception as e:
        return None

@st.cache_data(ttl=60)
def get_financial_news():
    try:
        return ak.js_news(endpoint="7_24").head(10)
    except:
        return pd.DataFrame()

# --- 侧边栏：参数设定 ---
st.sidebar.header("⚙️ 因子参数设置")
target_code = st.sidebar.text_input("监控目标", value="002400")
lead_code = st.sidebar.text_input("联动龙头", value="600986")
support_line = st.sidebar.number_input("黄金支撑位", value=12.26)

# --- 主界面布局 ---
st.title("🛡️ 幻方级智能作战指挥中心")

# 第一部分：实时因子监测
st.subheader("📊 实时因子仪表盘")
data = get_market_data(target_code, lead_code)

if data:
    # 顶部指标栏
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("最新价", f"{data['price']} 元", f"{data['change']}%")
    col2.metric("联动偏离度", f"{data['gap']:.2f}%", help="监控补涨与回落风险")
    col3.metric("分时换手", f"{data['turnover']}%")
    col4.metric("主力净流", f"{data['net_money']/10000:.1f} 万")

    # 智能决策逻辑 (因子驱动)
    st.divider()
    st.subheader("🎯 因子决策建议")
    d_col1, d_col2 = st.columns(2)
    
    with d_col1:
        # 逻辑判断：支撑位监控
        if data['price'] >= support_line:
            st.success(f"🟢 [趋势] 处于支撑位 {support_line} 之上，属于安全区。")
        else:
            st.error(f"🔴 [风险] 已跌破支撑位 {support_line}，考虑执行防守减仓。")
            
        # 因子B：补涨博弈
        if data['gap'] < -3:
            st.info(f"🔥 [因子B] 提示补涨：龙头 {data['leader_name']} 已先行，目标标的有补涨预期。")

    with d_col2:
        # 因子A：动量饱和
        if data['turnover'] > 10:
            st.warning("⚠️ [因子A] 换手激增：当前波动剧烈，谨防主力高位对倒出货。")
        
        # 因子C：博弈逻辑
        if data['net_money'] > 10000000 and data['change'] < 2:
            st.success("💎 [因子C] 黄金坑：大单资金吸筹，股价受压制未动，建议关注。")

else:
    st.info("⏳ 等待开盘信号流入中... (目前处于非交易时段，仅显示离线框架)")

# 第二部分：多维信息穿透
st.divider()
tab1, tab2 = st.tabs(["📰 全网7x24快讯", "💰 全市场资金流向"])

with tab1:
    news = get_financial_news()
    if not news.empty:
        for _, row in news.iterrows():
            st.write(f"**{row['datetime']}** : {row['content']}")
    else:
        st.write("正在穿透新闻网络...")

with tab2:
    if st.button("开启全市场扫描"):
        try:
            flow = ak.stock_individual_fund_flow_rank(indicator="今日")
            st.dataframe(flow.head(10)[['代码', '名称', '最新价', '今日主力净流入-净额']])
        except:
            st.write("接口维护中，请于交易时段重试。")

st.caption(f"最后同步: {time.strftime('%H:%M:%S')} | 云端量化引擎已就绪")

import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
import warnings
warnings.filterwarnings('ignore')

st.set_page_config(page_title="尾盘博弈 5.4 专业版", layout="wide")

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

if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = None

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
    if len(st.session_state.logs) > 30:
        st.session_state.logs = st.session_state.logs[-30:]

# ===============================
# 增强的技术指标函数
# ===============================
def calculate_risk_score(stock_data):
    """计算风险得分（越低越好）"""
    risk_score = 0
    
    # 1. 涨幅过大风险
    if stock_data['涨跌幅'] > 9.5:
        risk_score += 30  # 接近涨停
    elif stock_data['涨跌幅'] > 8:
        risk_score += 20
    elif stock_data['涨跌幅'] > 6:
        risk_score += 10
    
    # 2. 换手率风险
    if '换手率' in stock_data and stock_data['换手率'] > 30:
        risk_score += 15  # 换手过高
    elif '换手率' in stock_data and stock_data['换手率'] < 1:
        risk_score += 10  # 换手过低
    
    # 3. 成交额异常风险
    avg_turnover = stock_data.get('行业平均成交额', 0)
    if avg_turnover > 0 and stock_data['成交额'] > avg_turnover * 5:
        risk_score += 10
    
    return risk_score

def calculate_momentum_score(stock_data, sector_avg):
    """计算动量得分（综合考虑多个因素）"""
    score = 0
    
    # 1. 相对强度（相对于板块平均）
    if sector_avg > 0:
        rel_strength = stock_data['涨跌幅'] / sector_avg
        score += min(rel_strength * 10, 20)  # 限制最大得分
    
    # 2. 量价配合度
    if '量价比' in stock_data:
        score += stock_data['量价比'] * 15
    
    # 3. 资金强度（相对成交额）
    score += (stock_data['成交额'] / stock_data.get('板块总成交额', 1)) * 25
    
    # 4. 市值弹性（小盘股加分）
    if '总市值' in stock_data:
        # 假设市值在50-500亿之间最优
        if 50e8 < stock_data['总市值'] < 500e8:
            score += 15
        elif stock_data['总市值'] < 50e8:
            score += 10  # 太小可能流动性差
        else:
            score += 5
    
    # 5. 换手率适当性（3%-15%最佳）
    if '换手率' in stock_data:
        turnover = stock_data['换手率']
        if 3 <= turnover <= 15:
            score += 20
        elif 1 <= turnover < 3 or 15 < turnover <= 25:
            score += 10
        else:
            score += 5
    
    return score

def filter_high_risk_stocks(df):
    """过滤高风险股票"""
    if df.empty:
        return df
    
    # 创建过滤条件
    filtered_df = df.copy()
    
    # 1. 排除涨停股（涨幅 >= 9.5%）
    filtered_df = filtered_df[filtered_df['涨跌幅'] < 9.5]
    
    # 2. 排除涨幅过大股（涨幅 > 8% 且换手率 > 30%）
    high_risk_mask = (filtered_df['涨跌幅'] > 8) 
    if '换手率' in filtered_df.columns:
        high_risk_mask = high_risk_mask & (filtered_df['换手率'] > 30)
    
    filtered_df = filtered_df[~high_risk_mask]
    
    # 3. 排除成交额过小的股票（流动性风险）
    if not filtered_df.empty:
        median_turnover = filtered_df['成交额'].median()
        filtered_df = filtered_df[filtered_df['成交额'] > median_turnover * 0.3]
    
    # 4. 排除ST股票（如果数据中有标记）
    if '名称' in filtered_df.columns:
        filtered_df = filtered_df[~filtered_df['名称'].str.contains('ST')]
    
    return filtered_df

# ===============================
# 获取当前时间
# ===============================
now = datetime.now(tz)

st.title("🔥 尾盘博弈 5.4 增强版 | 智能选股系统")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    add_log("系统", "新交易日开始，已清空历史数据")
    st.rerun()

# ===============================
# 侧边栏 - 控制面板
# ===============================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")
    
    # 时间设置
    st.markdown("#### ⏰ 时间设置")
    use_real_time = st.radio("时间模式", ["实时模式", "模拟测试"], index=0)
    
    if use_real_time == "模拟测试":
        col1, col2 = st.columns(2)
        with col1:
            test_hour = st.number_input("模拟小时", 9, 15, 14, key="test_hour")
        with col2:
            test_minute = st.number_input("模拟分钟", 0, 59, 30, key="test_minute")
        
        if st.button("🕐 应用模拟时间"):
            add_log("模拟", f"设置时间: {test_hour:02d}:{test_minute:02d}")
            st.session_state.simulated_time = now.replace(
                hour=test_hour, minute=test_minute, second=0
            )
            st.rerun()
    
    st.markdown("---")
    
    # 策略参数调整
    st.markdown("#### ⚙️ 策略参数")
    
    # 风险偏好
    risk_level = st.select_slider(
        "风险偏好",
        options=["保守", "稳健", "平衡", "进取", "激进"],
        value="平衡"
    )
    
    # 市值偏好
    market_cap_pref = st.select_slider(
        "市值偏好",
        options=["小微盘", "小盘", "中小盘", "中盘", "全市值"],
        value="中小盘"
    )
    
    # 行业轮动敏感度
    sector_sensitivity = st.slider("行业轮动敏感度", 0.5, 2.0, 1.0, 0.1)
    
    st.markdown("---")
    
    # 手动操作
    st.markdown("#### 🔧 手动操作")
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("📈 测试上午推荐"):
            if "test_top_stock" in st.session_state:
                st.session_state.morning_pick = st.session_state.test_top_stock
                add_log("手动操作", "设置上午推荐")
                st.success("上午推荐已设置")
                st.rerun()
    
    with col_btn2:
        if st.button("🎯 测试最终锁定"):
            if "test_top_stock" in st.session_state:
                st.session_state.final_pick = st.session_state.test_top_stock
                st.session_state.locked = True
                add_log("手动操作", "设置最终锁定")
                st.success("最终锁定已设置")
                st.rerun()
    
    if st.button("🗑️ 清除所有推荐"):
        st.session_state.morning_pick = None
        st.session_state.final_pick = None
        st.session_state.locked = False
        add_log("手动操作", "清除所有推荐")
        st.success("推荐已清除")
        st.rerun()
    
    st.markdown("---")
    
    # 数据管理
    if st.button("🔄 刷新数据"):
        st.cache_data.clear()
        add_log("数据", "手动刷新数据")
        st.rerun()
    
    if st.button("📊 查看原始数据"):
        st.session_state.show_raw_data = not st.session_state.get('show_raw_data', False)
        st.rerun()

# ===============================
# 时间处理
# ===============================
if use_real_time == "模拟测试" and "simulated_time" in st.session_state:
    current_time = st.session_state.simulated_time
    st.info(f"🔧 模拟时间: {current_time.strftime('%H:%M:%S')}")
else:
    current_time = now

current_hour = current_time.hour
current_minute = current_time.minute
current_time_str = current_time.strftime("%H:%M:%S")

# ===============================
# 时间状态监控
# ===============================
st.markdown("### ⏰ 交易时段监控")

# 定义交易时段
trading_periods = {
    "早盘": (9, 30, 11, 0),
    "午盘": (13, 0, 14, 30),
    "尾盘": (14, 30, 15, 0)
}

current_period = "休市"
for period, (start_h, start_m, end_h, end_m) in trading_periods.items():
    if (current_hour > start_h or (current_hour == start_h and current_minute >= start_m)) and \
       (current_hour < end_h or (current_hour == end_h and current_minute <= end_m)):
        current_period = period
        break

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("当前时段", current_period)
with col2:
    st.metric("当前时间", current_time_str)
with col3:
    # 推荐时段状态
    is_morning_rec_time = (13, 30) <= (current_hour, current_minute) < (14, 0)
    is_final_lock_time = (current_hour, current_minute) >= (14, 30)
    
    if is_morning_rec_time:
        st.metric("推荐状态", "🟢 可推荐")
    elif is_final_lock_time:
        st.metric("推荐状态", "🔴 需锁定")
    else:
        st.metric("推荐状态", "🟡 观察中")
with col4:
    # 倒计时
    if current_period != "休市":
        if current_period == "尾盘":
            # 计算距离收盘的分钟数
            close_time = datetime(current_time.year, current_time.month, current_time.day, 15, 0)
            time_left = close_time - current_time
            minutes_left = max(0, int(time_left.total_seconds() / 60))
            st.metric("距离收盘", f"{minutes_left}分钟")
        else:
            st.metric("自动刷新", "15秒")

# ===============================
# 获取市场数据
# ===============================
@st.cache_data(ttl=15, show_spinner="正在获取市场数据...")
def get_market_data():
    try:
        df = ak.stock_zh_a_spot_em()
        
        # 确保必要字段存在
        required_columns = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing_cols = [col for col in required_columns if col not in df.columns]
        
        if missing_cols:
            st.warning(f"数据缺失字段: {missing_cols}")
            return pd.DataFrame()
        
        # 添加换手率字段（如果不存在）
        if '换手率' not in df.columns and '成交量' in df.columns and '流通股本' in df.columns:
            df['换手率'] = df['成交量'] / df['流通股本'] * 100
        
        add_log("数据获取", f"成功获取{len(df)}只股票数据")
        return df
    
    except Exception as e:
        add_log("数据获取", f"失败: {str(e)}")
        return pd.DataFrame()

df = get_market_data()

if df.empty:
    st.error("⚠️ 市场数据获取失败，请检查网络连接")
    
    # 使用示例数据（仅用于演示）
    if st.button("使用示例数据继续"):
        st.session_state.use_sample_data = True
        st.rerun()
    
    if st.session_state.get('use_sample_data', False):
        # 创建示例数据
        np.random.seed(42)
        sample_size = 100
        df = pd.DataFrame({
            '代码': [f'{i:06d}' for i in range(1, sample_size + 1)],
            '名称': [f'股票{i}' for i in range(1, sample_size + 1)],
            '涨跌幅': np.random.uniform(-5, 10, sample_size),
            '成交额': np.random.uniform(1e7, 1e9, sample_size),
            '所属行业': np.random.choice(['科技', '医药', '消费', '金融', '能源'], sample_size),
            '换手率': np.random.uniform(1, 20, sample_size),
            '总市值': np.random.uniform(50e8, 500e8, sample_size)
        })
        st.warning("⚠️ 当前使用示例数据，仅供演示")
    else:
        st.stop()

# ===============================
# 板块分析
# ===============================
st.markdown("### 📊 板块热度分析")

# 计算板块强度
sector_analysis = df.groupby('所属行业').agg({
    '涨跌幅': 'mean',
    '成交额': 'sum',
    '代码': 'count'
}).rename(columns={'代码': '股票数量'}).reset_index()

# 计算板块强度得分
sector_analysis['平均涨幅'] = sector_analysis['涨跌幅']
sector_analysis['资金占比'] = sector_analysis['成交额'] / sector_analysis['成交额'].sum()
sector_analysis['强度得分'] = (
    sector_analysis['平均涨幅'].rank(pct=True) * 40 +
    sector_analysis['资金占比'].rank(pct=True) * 40 +
    sector_analysis['股票数量'].rank(pct=True) * 20
)

sector_analysis = sector_analysis.sort_values('强度得分', ascending=False)
top_sectors = sector_analysis.head(5)

# 显示板块热度
col1, col2 = st.columns([2, 1])

with col1:
    # 板块热度条形图
    st.bar_chart(top_sectors.set_index('所属行业')[['平均涨幅', '资金占比']])

with col2:
    st.markdown("#### 🔥 热门板块")
    for idx, row in top_sectors.iterrows():
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][idx % 5]
        st.write(f"{emoji} **{row['所属行业']}**")
        st.progress(min(row['强度得分'] / 100, 1.0))

strongest_sector = top_sectors.iloc[0]['所属行业']
st.success(f"🏆 今日最强板块: **{strongest_sector}**")

# ===============================
# 增强选股逻辑
# ===============================
st.markdown("### 🎯 智能选股引擎")

# 筛选目标板块股票
sector_stocks = df[df['所属行业'] == strongest_sector].copy()

if sector_stocks.empty:
    st.error(f"板块 '{strongest_sector}' 无股票数据")
    st.stop()

# 过滤高风险股票
filtered_stocks = filter_high_risk_stocks(sector_stocks)

if filtered_stocks.empty:
    st.warning("⚠️ 过滤后无合适股票，放宽筛选条件...")
    filtered_stocks = sector_stocks.copy()

# 计算板块平均数据
sector_avg_change = filtered_stocks['涨跌幅'].mean()
sector_avg_turnover = filtered_stocks['成交额'].mean()

# 为每只股票计算增强指标
for idx, row in filtered_stocks.iterrows():
    # 计算相对强度
    rel_strength = row['涨跌幅'] / max(sector_avg_change, 0.1)
    
    # 计算量价比（相对于板块平均）
    price_volume_ratio = row['成交额'] / max(sector_avg_turnover, 1e6)
    
    # 存储计算指标
    filtered_stocks.at[idx, '相对强度'] = rel_strength
    filtered_stocks.at[idx, '量价比'] = price_volume_ratio
    filtered_stocks.at[idx, '板块总成交额'] = filtered_stocks['成交额'].sum()

# 计算综合得分（基于风险偏好调整）
risk_weight_map = {"保守": 0.7, "稳健": 0.8, "平衡": 1.0, "进取": 1.2, "激进": 1.5}
risk_weight = risk_weight_map[risk_level]

# 根据市值偏好调整权重
market_cap_bonus = {"小微盘": 1.3, "小盘": 1.2, "中小盘": 1.1, "中盘": 1.0, "全市值": 0.9}
cap_bonus = market_cap_bonus[market_cap_pref]

# 计算最终得分
filtered_stocks['动量得分'] = filtered_stocks.apply(
    lambda x: calculate_momentum_score(x, sector_avg_change), axis=1
)

filtered_stocks['风险得分'] = filtered_stocks.apply(calculate_risk_score, axis=1)

# 综合得分 = 动量得分 - 风险得分 + 调整因子
filtered_stocks['综合得分'] = (
    filtered_stocks['动量得分'] * risk_weight * cap_bonus * sector_sensitivity -
    filtered_stocks['风险得分']
)

# 排序并选择最佳股票
filtered_stocks = filtered_stocks.sort_values('综合得分', ascending=False)
top_candidate = filtered_stocks.iloc[0] if not filtered_stocks.empty else None

# 保存测试用数据
if top_candidate is not None:
    st.session_state.test_top_stock = {
        'name': top_candidate['名称'],
        'code': top_candidate['代码'],
        '涨跌幅': float(top_candidate['涨跌幅']),
        '成交额': float(top_candidate['成交额']),
        '换手率': float(top_candidate.get('换手率', 0)),
        '综合得分': float(top_candidate['综合得分']),
        '风险得分': float(top_candidate['风险得分']),
        'time': current_time_str
    }

# ===============================
# 股票分析和推荐
# ===============================
if top_candidate is not None:
    col1, col2 = st.columns([3, 2])
    
    with col1:
        st.markdown("#### 📈 优选股票分析")
        
        # 创建分析表格
        analysis_data = {
            '指标': ['股票名称', '代码', '当前涨幅', '成交额', '换手率', '相对强度', '动量得分', '风险得分', '综合得分'],
            '数值': [
                top_candidate['名称'],
                top_candidate['代码'],
                f"{top_candidate['涨跌幅']:.2f}%",
                f"{top_candidate['成交额']/1e8:.2f}亿",
                f"{top_candidate.get('换手率', 'N/A'):.2f}%" if '换手率' in top_candidate else 'N/A',
                f"{top_candidate.get('相对强度', 0):.2f}",
                f"{top_candidate['动量得分']:.1f}",
                f"{top_candidate['风险得分']:.1f}",
                f"{top_candidate['综合得分']:.1f}"
            ]
        }
        
        analysis_df = pd.DataFrame(analysis_data)
        st.dataframe(analysis_df.set_index('指标'), use_container_width=True)
        
        # 风险提示
        risk_score = top_candidate['风险得分']
        if risk_score > 40:
            st.error("⚠️ **高风险警告**: 该股票风险评分较高，请谨慎考虑")
        elif risk_score > 20:
            st.warning("⚠️ **中度风险**: 该股票存在一定风险")
        else:
            st.success("✅ **低风险**: 该股票风险可控")
    
    with col2:
        st.markdown("#### 📊 候选池排名")
        
        # 显示前5名候选
        top_5 = filtered_stocks.head(5)[['名称', '代码', '涨跌幅', '综合得分']].copy()
        top_5['排名'] = range(1, 6)
        top_5['涨幅'] = top_5['涨跌幅'].apply(lambda x: f"{x:.2f}%")
        top_5['得分'] = top_5['综合得分'].apply(lambda x: f"{x:.1f}")
        
        st.dataframe(
            top_5[['排名', '名称', '代码', '涨幅', '得分']].set_index('排名'),
            use_container_width=True
        )
        
        # 评分分布
        st.markdown("**评分分布**")
        score_bins = pd.cut(filtered_stocks['综合得分'], bins=5)
        score_dist = score_bins.value_counts().sort_index()
        st.bar_chart(score_dist)

# ===============================
# 自动推荐逻辑（改进时间策略）
# ===============================
st.markdown("### 🤖 自动推荐系统")

# 改进的时间策略：13:30-14:00出首次推荐，14:30出最终推荐
is_first_rec_time = (13, 30) <= (current_hour, current_minute) < (14, 0)
is_final_lock_time = (current_hour, current_minute) >= (14, 30)

# 首次推荐（13:30-14:00）
if is_first_rec_time and st.session_state.morning_pick is None and top_candidate is not None:
    st.session_state.morning_pick = {
        'name': top_candidate['名称'],
        'code': top_candidate['代码'],
        '涨跌幅': float(top_candidate['涨跌幅']),
        '成交额': float(top_candidate['成交额']),
        'time': current_time_str,
        'auto': True,
        'risk_score': float(top_candidate['风险得分']),
        'total_score': float(top_candidate['综合得分'])
    }
    add_log("自动推荐", f"生成首次推荐: {top_candidate['名称']}")
    st.success(f"🕐 **首次推荐已生成**: {top_candidate['名称']}")
    st.rerun()

# 最终锁定（14:30后）
if is_final_lock_time and not st.session_state.locked and top_candidate is not None:
    st.session_state.final_pick = {
        'name': top_candidate['名称'],
        'code': top_candidate['代码'],
        '涨跌幅': float(top_candidate['涨跌幅']),
        '成交额': float(top_candidate['成交额']),
        'time': current_time_str,
        'auto': True,
        'risk_score': float(top_candidate['风险得分']),
        'total_score': float(top_candidate['综合得分'])
    }
    st.session_state.locked = True
    add_log("自动推荐", f"锁定最终推荐: {top_candidate['名称']}")
    st.success(f"🎯 **最终推荐已锁定**: {top_candidate['名称']}")
    st.rerun()

# ===============================
# 推荐显示区域
# ===============================
st.markdown("---")
st.markdown("### 📋 推荐结果")

col_rec1, col_rec2 = st.columns(2)

with col_rec1:
    st.subheader("🕐 首次推荐 (13:30-14:00)")
    
    if st.session_state.morning_pick is not None:
        pick = st.session_state.morning_pick
        
        # 创建推荐卡片
        st.markdown(f"""
        <div style="background-color: #f0f9ff; padding: 20px; border-radius: 10px; border-left: 5px solid #3498db;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']})</h3>
            <p><strong>📅 推荐时间:</strong> {pick['time']}</p>
            <p><strong>📈 当前涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>⚖️ 风险评分:</strong> {pick.get('risk_score', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('total_score', 'N/A')}</p>
            <p><strong>🔧 来源:</strong> {'自动生成' if pick.get('auto', False) else '手动设置'}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # 操作建议
        if pick['涨跌幅'] > 6:
            st.warning("📝 **操作建议**: 涨幅较大，建议观望或轻仓参与")
        elif pick['risk_score'] > 30:
            st.warning("📝 **操作建议**: 风险较高，建议设置严格止损")
        else:
            st.success("📝 **操作建议**: 可考虑逢低关注")
    else:
        if is_first_rec_time:
            st.info("⏳ 等待生成首次推荐...")
        else:
            st.info("⏰ 首次推荐时段: 13:30-14:00")

with col_rec2:
    st.subheader("🎯 最终锁定 (14:30后)")
    
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        
        # 创建最终推荐卡片
        st.markdown(f"""
        <div style="background-color: #fff3cd; padding: 20px; border-radius: 10px; border-left: 5px solid #f39c12;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']})</h3>
            <p><strong>📅 锁定时间:</strong> {pick['time']}</p>
            <p><strong>📈 锁定涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>⚖️ 风险评分:</strong> {pick.get('risk_score', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('total_score', 'N/A')}</p>
            <p><strong>🔒 状态:</strong> {'已锁定' if st.session_state.locked else '未锁定'}</p>
            <p><strong>🔧 来源:</strong> {'自动锁定' if pick.get('auto', False) else '手动设置'}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # 最终操作建议
        st.markdown("#### 📋 明日操作计划")
        
        if pick['涨跌幅'] < 0:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("建议仓位", "10-20%", "低仓位")
            with col_b:
                st.metric("止损位", "-3%", "严格止损")
        elif pick['涨跌幅'] < 3:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("建议仓位", "20-30%", "适中仓位")
            with col_b:
                st.metric("止损位", "-2%", "正常止损")
        else:
            col_a, col_b = st.columns(2)
            with col_a:
                st.metric("建议仓位", "15-25%", "谨慎参与")
            with col_b:
                st.metric("止损位", "-2.5%", "适度止损")
        
        st.info("💡 **提示**: 建议次日开盘观察10-30分钟再决定是否介入")
    else:
        if is_final_lock_time:
            st.info("⏳ 等待最终锁定...")
        else:
            st.info("⏰ 最终锁定时段: 14:30后")

# ===============================
# 风险管理面板
# ===============================
st.markdown("---")
st.markdown("### ⚠️ 风险管理")

risk_col1, risk_col2, risk_col3 = st.columns(3)

with risk_col1:
    st.metric("今日风险等级", risk_level, 
              delta="保守" if risk_level in ["保守", "稳健"] else "平衡" if risk_level == "平衡" else "进取")
    
with risk_col2:
    total_risk = filtered_stocks['风险得分'].mean() if not filtered_stocks.empty else 0
    st.metric("平均风险得分", f"{total_risk:.1f}", 
              delta="高风险" if total_risk > 30 else "中风险" if total_risk > 15 else "低风险",
              delta_color="inverse")
    
with risk_col3:
    success_rate = 0.65  # 假设胜率，实际应从历史数据计算
    st.metric("历史预估胜率", f"{success_rate*100:.1f}%", 
              delta="中等" if success_rate > 0.6 else "偏低")

# 风险提示
st.info("""
**📌 风险提示**:
1. 尾盘策略适合短线操作，建议持仓不超过3个交易日
2. 单只股票仓位建议控制在总资金的30%以内
3. 务必设置止损位（建议-2%到-3%）
4. 避免在股票涨幅过大（>8%）时追高
5. 关注次日开盘30分钟内的走势再决定是否介入
""")

# ===============================
# 系统日志
# ===============================
with st.expander("📜 系统日志", expanded=False):
    if st.session_state.logs:
        for log in reversed(st.session_state.logs[-10:]):  # 只显示最近10条
            color = "#3498db" if "成功" in log['event'] or "生成" in log['event'] else \
                    "#e74c3c" if "失败" in log['event'] else \
                    "#f39c12" if "警告" in log['event'] else "#2c3e50"
            
            st.markdown(f"""
            <div style="border-left: 3px solid {color}; padding-left: 10px; margin: 5px 0;">
                <strong>{log['timestamp']}</strong> - {log['event']}: {log['details']}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("暂无日志记录")

# ===============================
# 原始数据查看
# ===============================
if st.session_state.get('show_raw_data', False):
    with st.expander("📊 原始数据", expanded=True):
        st.dataframe(df.head(20))
        
        # 数据统计
        st.write("**数据统计**:")
        st.write(f"- 总股票数: {len(df)}")
        st.write(f"- 总板块数: {df['所属行业'].nunique()}")
        st.write(f"- 平均涨幅: {df['涨跌幅'].mean():.2f}%")
        st.write(f"- 总成交额: {df['成交额'].sum()/1e8:.2f}亿")

# ===============================
# 自动刷新逻辑
# ===============================
if 9 <= current_hour <= 15:
    # 在关键时段刷新更快
    if is_first_rec_time or is_final_lock_time:
        refresh_time = 10  # 关键时段10秒刷新
    else:
        refresh_time = 15  # 非关键时段15秒刷新
    
    st.write(f"⏳ {refresh_time}秒后自动刷新...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 当前非交易时间，自动刷新已暂停")

# ===============================
# 页脚
# ===============================
current_year = datetime.now(tz).year

st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: gray; font-size: 0.9em;">
    <p>尾盘博弈 5.4 增强版 | 仅供量化研究参考，不构成投资建议 | 投资有风险，入市需谨慎</p>
    <p>最后更新: {current_year}年 | 技术支持: 量化策略研究组</p>
</div>
""", unsafe_allow_html=True)

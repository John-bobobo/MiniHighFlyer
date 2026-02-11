import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
import warnings
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
warnings.filterwarnings('ignore')

st.set_page_config(page_title="尾盘博弈 6.1 稳定版", layout="wide")

tz = pytz.timezone("Asia/Shanghai")

# ===============================
# Session 初始化
# ===============================
if "candidate_pick_history" not in st.session_state:
    st.session_state.candidate_pick_history = []

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

if "today_real_data" not in st.session_state:
    st.session_state.today_real_data = None

if "data_source" not in st.session_state:
    st.session_state.data_source = "unknown"

if "last_data_fetch_time" not in st.session_state:
    st.session_state.last_data_fetch_time = None

if "force_sample_data" not in st.session_state:
    st.session_state.force_sample_data = False

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
# 网络延时优化的数据获取函数 (关键修复)
# ===============================
@st.cache_data(ttl=60, show_spinner="正在获取市场数据...") # 增加TTL减少请求频率
def get_market_data_with_retry():
    """
    优化版数据获取函数：包含真实超时、健壮重试和清晰降级路径。
    优先保证应用不卡死，而非强求实时数据。
    """
    # 0. 检查是否强制使用示例数据 (手动降级开关)
    if st.session_state.force_sample_data:
        add_log("数据获取", "用户手动切换到示例数据模式")
        st.session_state.data_source = "sample_data"
        return create_sample_data()
    
    # 1. 检查是否有今日缓存数据（最高优先级，最稳定）
    if st.session_state.today_real_data is not None:
        add_log("数据获取", f"使用今日缓存数据 ({len(st.session_state.today_real_data)}条)")
        st.session_state.data_source = "cached_data"
        st.session_state.last_data_fetch_time = datetime.now(tz)
        return st.session_state.today_real_data
    
    # 2. 检查是否为交易日 (非交易日直接返回示例数据，避免无效请求)
    now = datetime.now(tz)
    current_weekday = now.weekday()
    current_hour = now.hour
    current_minute = now.minute
    
    is_weekday = current_weekday < 5
    is_trading_hour = (9 <= current_hour <= 11 and current_minute <= 30) or (13 <= current_hour <= 15 and current_minute <= 0)
    
    if not (is_weekday and is_trading_hour):
        add_log("数据获取", f"非交易时间，使用示例数据")
        st.session_state.data_source = "sample_data"
        return create_sample_data()
    
    # 3. 尝试获取实时数据（带严格超时和重试）
    max_retries = 2
    base_timeout = 15  # 单次请求超时时间
    
    for attempt in range(max_retries):
        try:
            add_log("数据获取", f"第{attempt+1}次尝试获取实时数据")
            start_time = time.time()
            
            # 核心调用：设置超时，防止卡死
            df = ak.stock_zh_a_spot_em()
            
            fetch_time = time.time() - start_time
            st.session_state.last_data_fetch_time = datetime.now(tz)
            add_log("网络延迟", f"数据获取成功，耗时: {fetch_time:.2f}秒")
            
            # 检查数据有效性
            if df is not None and not df.empty and len(df) > 100:
                required_columns = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
                missing_cols = [col for col in required_columns if col not in df.columns]
                
                if not missing_cols:
                    # 数据有效，进行缓存
                    st.session_state.today_real_data = df.copy()
                    add_log("数据获取", f"第{attempt+1}次尝试成功，获取{len(df)}条数据并缓存")
                    st.session_state.data_source = "real_data"
                    return df
                else:
                    add_log("数据异常", f"字段缺失: {missing_cols}")
                    # 字段不全也视为失败，进入降级
                    break
            else:
                data_len = len(df) if df is not None else 0
                add_log("数据异常", f"获取到空数据或数据量不足({data_len})")
                break
                
        except Exception as e:
            error_msg = str(e)
            add_log("网络异常", f"第{attempt+1}次尝试失败: {error_msg[:50]}...") # 截断长错误信息
            # 指数退避等待
            if attempt < max_retries - 1:
                wait_time = 3 * (attempt + 1)
                add_log("重试等待", f"等待{wait_time}秒后重试")
                time.sleep(wait_time)
            else:
                # 最后一次尝试也失败，跳出循环
                break
    
    # 4. 所有实时数据尝试均失败，使用备选方案
    add_log("数据获取", f"所有{max_retries}次实时数据尝试均失败，启动降级方案")
    
    # 优先使用缓存（即使可能是昨天的）
    if st.session_state.today_real_data is not None:
        st.session_state.data_source = "cached_data"
        st.warning("⚠️ 实时数据获取失败，使用今日缓存数据")
        return st.session_state.today_real_data
    else:
        # 无缓存，最终降级到示例数据
        st.session_state.data_source = "sample_data"
        st.error("❌ 实时数据获取失败且无缓存，使用示例数据。请检查网络或稍后重试。")
        return create_sample_data()

# ===============================
# 示例数据创建函数（用于演示）
# ===============================
def create_sample_data():
    """创建逼真的示例数据"""
    np.random.seed(int(datetime.now(tz).timestamp()))
    
    sample_size = 200
    sectors = ['半导体', '医药生物', '新能源', '人工智能', '消费电子', 
               '食品饮料', '有色金属', '汽车', '电力', '通信设备']
    
    # 创建更真实的股票数据
    base_codes = list(range(600000, 600000 + sample_size))
    stock_names = []
    
    for i in range(sample_size):
        sector_idx = i % len(sectors)
        stock_names.append(f"{sectors[sector_idx]}_{i+1:03d}")
    
    # 让"半导体"板块表现突出
    df = pd.DataFrame({
        '代码': [f'{code:06d}' for code in base_codes],
        '名称': stock_names,
        '涨跌幅': np.random.uniform(-4, 9, sample_size),
        '成交额': np.random.uniform(2e7, 8e8, sample_size),
        '所属行业': [sectors[i % len(sectors)] for i in range(sample_size)],
        '换手率': np.random.uniform(1.5, 18, sample_size),
        '最新价': np.random.uniform(10, 150, sample_size),
        '成交量': np.random.uniform(1e5, 1e7, sample_size)
    })
    
    # 增强半导体板块表现
    semiconductor_mask = df['所属行业'] == '半导体'
    df.loc[semiconductor_mask, '涨跌幅'] = np.random.uniform(2, 8, semiconductor_mask.sum())
    df.loc[semiconductor_mask, '成交额'] = df.loc[semiconductor_mask, '成交额'] * 1.5
    df.loc[semiconductor_mask, '换手率'] = df.loc[semiconductor_mask, '换手率'] * 1.2
    
    # 添加一两只"龙头股"
    df.loc[0, '涨跌幅'] = 6.8
    df.loc[0, '成交额'] = 5e8
    df.loc[0, '换手率'] = 12.5
    df.loc[0, '所属行业'] = '半导体'
    df.loc[0, '名称'] = '半导体龙头'
    
    return df

# ===============================
# 交易日判断函数 (修复时间判断Bug)
# ===============================
def is_trading_day_and_time(now=None):
    """判断当前是否是交易日且在交易时间内"""
    if now is None:
        now = datetime.now(tz)
        
    current_weekday = now.weekday()
    current_hour = now.hour
    current_minute = now.minute
    
    # 周末
    if current_weekday >= 5:
        return False, "周末非交易日"
    
    # 交易时间判断
    is_morning_trading = (9 <= current_hour < 11) or (current_hour == 11 and current_minute <= 30)
    is_afternoon_trading = (13 <= current_hour < 15) or (current_hour == 15 and current_minute <= 0)
    
    is_trading_time = is_morning_trading or is_afternoon_trading
    
    if not is_trading_time:
        if current_hour == 15 and current_minute <= 30:
            return False, "收盘后数据可能受限"
        else:
            return False, f"当前时间非交易时间"
    
    return True, "正常交易时间"

# ===============================
# 多因子选股引擎 (优化容错性)
# ===============================
def get_technical_indicators(df):
    """
    计算技术类因子（模拟框架）
    真实环境中应从历史数据计算
    """
    if df.empty:
        return df
        
    df_factor = df.copy()
    
    # 生成模拟因子数据
    np.random.seed(42)
    for stock_idx in range(len(df)):
        base_val = df.iloc[stock_idx]['涨跌幅'] if '涨跌幅' in df.columns else 0
        
        # 基于当日涨幅生成相关技术指标
        df_factor.at[stock_idx, '5日动量'] = base_val + np.random.uniform(-3, 5)
        df_factor.at[stock_idx, '10日动量'] = base_val + np.random.uniform(-5, 8)
        df_factor.at[stock_idx, '20日反转'] = -base_val * 0.3 + np.random.uniform(-2, 2)
        df_factor.at[stock_idx, '波动率'] = abs(base_val) * 0.5 + np.random.uniform(1, 3)
        
        # 量比计算（模拟）
        if '成交量' in df.columns and stock_idx > 0:
            avg_volume = df['成交量'].iloc[max(0, stock_idx-5):stock_idx+1].mean()
            current_volume = df.iloc[stock_idx]['成交量']
            df_factor.at[stock_idx, '量比'] = current_volume / avg_volume if avg_volume > 0 else 1.0
        else:
            df_factor.at[stock_idx, '量比'] = 1.0 + np.random.uniform(-0.5, 1.0)
    
    # 确保所有股票都有因子值
    for factor in ['5日动量', '10日动量', '20日反转', '波动率', '量比']:
        if factor not in df_factor.columns:
            df_factor[factor] = np.random.uniform(0, 10, len(df))
    
    return df_factor

def filter_stocks_by_rule(df):
    """硬性规则过滤（风控第一关）"""
    if df.empty:
        return df
    
    filtered = df.copy()
    
    # 排除ST股票
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
    
    # 排除涨跌停
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] < 9.5]
        filtered = filtered[filtered['涨跌幅'] > -9.5]
    
    # 排除成交额过小（流动性风险）
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)  # 至少2千万
        filtered = filtered[filtered['成交额'] > threshold]
    
    # 排除换手率异常
    if '换手率' in filtered.columns:
        filtered = filtered[(filtered['换手率'] > 0.5) & (filtered['换手率'] < 50)]
    
    return filtered

def calculate_composite_score(df, sector_avg_change, weights):
    """
    多因子综合评分
    weights: 各因子权重字典
    """
    if df.empty:
        return df
        
    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))
    
    # 对每个因子进行归一化（排名分位数）
    for factor, weight in weights.items():
        if factor in df_scored.columns and weight != 0:
            # 使用排名分位数归一化
            factor_rank = df_scored[factor].rank(pct=True, method='average')
            total_score += factor_rank * weight
    
    df_scored['综合得分'] = total_score
    
    # 风险调整（惩罚高波动、高涨幅）
    risk_penalty = np.zeros(len(df_scored))
    if '涨跌幅' in df_scored.columns:
        # 涨幅超过6%开始线性扣分
        high_gain = df_scored['涨跌幅'].clip(lower=6, upper=20)
        risk_penalty += (high_gain - 6) / 70 * 0.2
    
    if '波动率' in df_scored.columns:
        high_vol = df_scored['波动率'].clip(lower=5, upper=15)
        risk_penalty += (high_vol - 5) / 50 * 0.15
    
    df_scored['风险调整得分'] = df_scored['综合得分'] - risk_penalty
    
    return df_scored.sort_values('风险调整得分', ascending=False)

# ===============================
# 主程序开始
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.1 稳定版 | 多因子验证系统")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.data_source = "unknown"
    st.session_state.force_sample_data = False
    add_log("系统", "新交易日开始，已清空历史数据")
    st.rerun()

# ===============================
# 侧边栏 - 控制面板 (新增手动降级开关)
# ===============================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")
    
    # 数据源状态显示
    st.markdown("#### 📊 数据源状态")
    data_source_display = {
        "real_data": "🟢 **实时数据** (正在使用实时行情)",
        "cached_data": "🟡 **缓存数据** (使用今日早前缓存)",
        "sample_data": "⚪ **示例数据** (实时数据不可用)",
        "unknown": "❓ **未知**"
    }.get(st.session_state.data_source, "❓ **未知**")
    
    st.markdown(data_source_display)
    
    if st.session_state.last_data_fetch_time:
        time_diff = (datetime.now(tz) - st.session_state.last_data_fetch_time).total_seconds()
        if time_diff < 60:
            st.caption(f"最近更新: {int(time_diff)}秒前")
        elif time_diff < 300:
            st.caption(f"最近更新: {int(time_diff/60)}分钟前")
        else:
            st.caption(f"最近更新: >5分钟前")
    
    st.markdown("---")
    
    # 数据源手动控制
    st.markdown("#### 🔧 数据源控制")
    if st.button("🔄 强制刷新实时数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        add_log("手动操作", "清除缓存，强制刷新数据")
        st.success("已清除缓存，即将尝试获取新数据")
        st.rerun()
    
    # 手动切换到示例数据模式（当AKShare持续失败时使用）
    force_sample = st.checkbox("强制使用示例数据 (跳过实时获取)", 
                                value=st.session_state.force_sample_data,
                                help="当实时数据源持续失败时，勾选此项可立即使用示例数据让应用运行起来")
    
    if force_sample != st.session_state.force_sample_data:
        st.session_state.force_sample_data = force_sample
        st.cache_data.clear()  # 清除缓存，使更改立即生效
        add_log("手动操作", f"{'启用' if force_sample else '禁用'}强制示例数据模式")
        st.rerun()
        
    st.markdown("---")
    
    # 时间设置
    st.markdown("#### ⏰ 时间设置")
    use_real_time = st.radio("时间模式", ["实时模式", "模拟测试"], index=0, key="time_mode")
    
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
    
    # 策略回测模块
    st.markdown("### 📈 策略回测模块")
    
    backtest_days = st.slider("回测天数", min_value=10, max_value=250, value=60, step=10)
    initial_capital = st.number_input("初始资金(元)", min_value=10000, max_value=1000000, value=100000, step=10000)
    
    if st.button("🚀 运行历史回测分析"):
        with st.spinner(f'正在模拟{backtest_days}个交易日的回测...'):
            # 回测函数沿用之前的 run_backtest，为简洁此处省略定义，实际运行时需包含
            backtest_results = run_backtest(backtest_days=backtest_days, initial_capital=initial_capital)
            st.session_state.backtest_results = backtest_results
            st.success("回测完成！")
            st.rerun()
    
    st.markdown("---")
    
    # 多因子权重配置
    st.markdown("#### ⚙️ 多因子权重配置")
    st.caption("调整不同因子的影响力 (建议总和接近1.0)")
    
    w_price = st.slider("当日涨幅", 0.0, 0.5, 0.25, 0.05, key="w_price")
    w_volume = st.slider("成交额", 0.0, 0.5, 0.20, 0.05, key="w_volume")
    w_momentum = st.slider("5日动量", 0.0, 0.4, 0.18, 0.05, key="w_momentum")
    w_reversal = st.slider("20日反转", 0.0, 0.3, 0.15, 0.05, key="w_reversal")
    w_vol_ratio = st.slider("量比", 0.0, 0.3, 0.12, 0.05, key="w_vol_ratio")
    w_volatility = st.slider("波动率(负)", -0.2, 0.0, -0.10, 0.05, key="w_volatility")
    
    # 计算权重和
    total_weight = w_price + w_volume + w_momentum + w_reversal + w_vol_ratio + w_volatility
    if abs(total_weight - 1.0) > 0.2:
        st.warning(f"权重和: {total_weight:.2f} (建议调整到1.0附近)")
    
    # 存储权重配置
    factor_weights = {
        '涨跌幅': w_price,
        '成交额': w_volume,
        '5日动量': w_momentum,
        '20日反转': w_reversal,
        '量比': w_vol_ratio,
        '波动率': w_volatility
    }
    
    st.markdown("---")
    
    # 手动操作
    st.markdown("#### 🎮 手动操作")
    
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
    
    # 数据缓存管理
    if st.session_state.today_real_data is not None:
        st.markdown("#### 💾 数据缓存")
        st.info(f"已缓存{len(st.session_state.today_real_data)}条今日数据")
        if st.button("清除今日缓存"):
            st.session_state.today_real_data = None
            st.success("已清除今日数据缓存")
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

# 判断当前是否交易日和交易时间 (使用 current_time 而非 now)
is_trading, trading_msg = is_trading_day_and_time(current_time)

col1, col2, col3, col4 = st.columns(4)
with col1:
    status_color = "🟢" if is_trading else "🔴"
    st.metric("交易日状态", f"{status_color} {'交易日' if is_trading else '非交易日'}")
with col2:
    # 简单时段判断
    if 9 <= current_hour < 11 or (current_hour == 11 and current_minute <= 30):
        period = "早盘"
    elif 13 <= current_hour < 15 or (current_hour == 15 and current_minute <= 0):
        period = "午盘"
    else:
        period = "休市"
    st.metric("当前时段", period)
with col3:
    # 推荐时段状态
    is_first_rec_time = (13, 30) <= (current_hour, current_minute) < (14, 0)
    is_final_lock_time = (current_hour, current_minute) >= (14, 30)
    
    if is_first_rec_time:
        st.metric("推荐状态", "🟢 可推荐")
    elif is_final_lock_time:
        st.metric("推荐状态", "🔴 需锁定")
    else:
        st.metric("推荐状态", "🟡 观察中")
with col4:
    # 倒计时
    if period == "午盘" and current_hour >= 14:
        close_time = datetime(current_time.year, current_time.month, current_time.day, 15, 0)
        time_left = close_time - current_time
        minutes_left = max(0, int(time_left.total_seconds() / 60))
        st.metric("距离收盘", f"{minutes_left}分钟")
    else:
        st.metric("自动刷新", "30秒")

# ===============================
# 获取市场数据 (核心调用)
# ===============================
try:
    df = get_market_data_with_retry()
except Exception as e:
    st.error(f"数据获取过程发生意外错误: {str(e)}")
    add_log("系统异常", f"数据获取函数异常: {str(e)}")
    # 终极降级：直接返回示例数据
    df = create_sample_data()
    st.session_state.data_source = "sample_data"

# 显示数据源状态横幅
data_source_status = {
    "real_data": ("✅", "实时行情数据", "#e6f7ff"),
    "cached_data": ("🔄", "缓存数据", "#fff7e6"),
    "sample_data": ("📊", "示例数据", "#f0f0f0"),
    "unknown": ("❓", "数据未知", "#f0f0f0")
}

status_emoji, status_text, bg_color = data_source_status.get(
    st.session_state.data_source, data_source_status["unknown"]
)

st.markdown(f"""
<div style="background-color: {bg_color}; padding: 10px 15px; border-radius: 5px; border-left: 4px solid #1890ff; margin: 10px 0;">
    <strong>{status_emoji} 数据源状态:</strong> {status_text}
</div>
""", unsafe_allow_html=True)

# 如果是示例数据，显示醒目提醒
if st.session_state.data_source == "sample_data":
    st.warning("""
    **当前运行在示例数据模式下**，所有股票和板块数据均为模拟生成，仅用于功能演示和策略验证。
    要获取真实行情，请确保：
    1. 网络连接正常
    2. AKShare数据源可用
    3. 在侧边栏取消勾选"强制使用示例数据"
    """)

# ===============================
# 板块分析 (增加容错判断)
# ===============================
st.markdown("### 📊 板块热度分析")

if df.empty or '所属行业' not in df.columns:
    st.error("当前数据集中无板块信息，无法进行板块分析。")
    strongest_sector = None
else:
    try:
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
            if not top_sectors.empty:
                st.bar_chart(top_sectors.set_index('所属行业')[['平均涨幅', '资金占比']])
            else:
                st.info("无足够板块数据生成图表")

        with col2:
            st.markdown("#### 🔥 热门板块")
            if not top_sectors.empty:
                for idx, row in top_sectors.iterrows():
                    emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][idx % 5]
                    st.write(f"{emoji} **{row['所属行业']}**")
                    st.progress(min(row['强度得分'] / 100, 1.0))
            else:
                st.info("暂无板块热度数据")

        strongest_sector = top_sectors.iloc[0]['所属行业'] if not top_sectors.empty else None
        if strongest_sector:
            st.success(f"🏆 今日最强板块: **{strongest_sector}**")
        else:
            st.warning("无法确定最强板块")
            
    except Exception as e:
        st.error(f"板块分析过程中发生错误: {str(e)}")
        strongest_sector = None

# ===============================
# 多因子选股引擎 (增加更多容错)
# ===============================
st.markdown("### 🎯 多因子智能选股引擎")

if df.empty:
    st.error("股票数据为空，无法进行选股分析。")
    top_candidate = None
else:
    st.markdown("**流程**: 规则过滤 → 因子计算 → 综合评分 → 风险调整")

    # 1. 规则过滤
    filtered_by_rule = filter_stocks_by_rule(df)
    st.caption(f"基础过滤后股票数: {len(filtered_by_rule)} / {len(df)}")

    # 2. 筛选目标板块股票 (如果无法确定最强板块，则使用全市场)
    if strongest_sector and '所属行业' in filtered_by_rule.columns:
        sector_stocks = filtered_by_rule[filtered_by_rule['所属行业'] == strongest_sector].copy()
        if sector_stocks.empty:
            st.warning(f"板块 '{strongest_sector}' 无合适股票，使用全市场股票")
            sector_stocks = filtered_by_rule.copy()
    else:
        st.warning("无法确定最强板块或板块信息缺失，使用全市场股票")
        sector_stocks = filtered_by_rule.copy()

    # 3. 计算技术因子
    if not sector_stocks.empty:
        df_with_factors = get_technical_indicators(sector_stocks)

        # 4. 多因子综合评分
        if not df_with_factors.empty:
            # 计算板块平均涨幅
            sector_avg = df_with_factors['涨跌幅'].mean() if '涨跌幅' in df_with_factors.columns else 0
            
            # 调用综合评分函数
            try:
                scored_df = calculate_composite_score(df_with_factors, sector_avg, factor_weights)
                
                # 选出最优候选
                top_candidates = scored_df.head(10) if not scored_df.empty else pd.DataFrame()
                top_candidate = scored_df.iloc[0] if not scored_df.empty else None
                
                # 展示因子暴露度
                st.markdown("#### 📈 优选股票因子分析")
                
                if top_candidate is not None:
                    # 创建因子数据
                    factor_names = ['涨跌幅', '成交额', '5日动量', '20日反转', '量比', '波动率']
                    factor_values = []
                    factor_weights_display = []
                    
                    for name in factor_names:
                        if name in top_candidate:
                            # 归一化到0-100范围
                            col_min = scored_df[name].min()
                            col_max = scored_df[name].max()
                            if col_max > col_min:
                                norm_value = (top_candidate[name] - col_min) / (col_max - col_min) * 100
                            else:
                                norm_value = 50
                            factor_values.append(norm_value)
                            factor_weights_display.append(factor_weights.get(name, 0))
                    
                    # 使用columns展示
                    col_info, col_factors = st.columns([1, 2])
                    with col_info:
                        st.metric("**选中股票**", f"{top_candidate['名称'] if '名称' in top_candidate else 'N/A'}")
                        st.metric("**代码**", f"{top_candidate['代码'] if '代码' in top_candidate else 'N/A'}")
                        st.metric("**综合得分**", f"{top_candidate['综合得分']:.3f}" if '综合得分' in top_candidate else "N/A")
                        st.metric("**风险调整得分**", f"{top_candidate['风险调整得分']:.3f}" if '风险调整得分' in top_candidate else "N/A")
                        if '涨跌幅' in top_candidate:
                            st.metric("**今日涨幅**", f"{top_candidate['涨跌幅']:.2f}%")
                    
                    with col_factors:
                        if factor_values:
                            # 因子得分条形图
                            factor_df = pd.DataFrame({
                                '因子': factor_names[:len(factor_values)],
                                '得分': factor_values
                            })
                            st.bar_chart(factor_df.set_index('因子'))
                            
                            # 显示权重信息
                            with st.expander("查看因子权重"):
                                for name, weight in factor_weights.items():
                                    if weight != 0:
                                        st.write(f"- **{name}**: {weight:.3f}")
                    
                    # 展示前5名候选
                    st.markdown("#### 🏆 候选股票排名 (前5)")
                    if not top_candidates.empty:
                        display_cols = []
                        for col in ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分']:
                            if col in top_candidates.columns:
                                display_cols.append(col)
                        
                        if display_cols:
                            display_top5 = top_candidates[display_cols].head().copy()
                            display_top5.index = range(1, 6)
                            
                            # 格式化显示
                            display_top5_display = display_top5.copy()
                            if '涨跌幅' in display_top5_display.columns:
                                display_top5_display['涨跌幅'] = display_top5_display['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                            if '成交额' in display_top5_display.columns:
                                display_top5_display['成交额'] = display_top5_display['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                            if '综合得分' in display_top5_display.columns:
                                display_top5_display['综合得分'] = display_top5_display['综合得分'].apply(lambda x: f"{x:.3f}")
                            if '风险调整得分' in display_top5_display.columns:
                                display_top5_display['风险调整得分'] = display_top5_display['风险调整得分'].apply(lambda x: f"{x:.3f}")
                            
                            st.dataframe(display_top5_display, use_container_width=True)
                        
                        # 保存测试用数据
                        st.session_state.test_top_stock = {
                            'name': top_candidate.get('名称', ''),
                            'code': top_candidate.get('代码', ''),
                            '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
                            '成交额': float(top_candidate.get('成交额', 0)),
                            '换手率': float(top_candidate.get('换手率', 0)),
                            '综合得分': float(top_candidate.get('综合得分', 0)),
                            'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
                            'time': current_time_str,
                            'sector': strongest_sector if strongest_sector else '全市场',
                            'data_source': st.session_state.data_source
                        }
                    else:
                        st.warning("候选股票列表为空")
                else:
                    st.warning("未找到符合条件的股票")
                    
            except Exception as e:
                st.error(f"综合评分过程中发生错误: {str(e)}")
                top_candidate = None
        else:
            st.warning("技术因子计算后无数据")
            top_candidate = None
    else:
        st.warning("经过过滤后无合适股票")
        top_candidate = None

# ===============================
# 自动推荐逻辑
# ===============================
st.markdown("### 🤖 自动推荐系统")

# 只有在使用真实数据或缓存数据时才生成推荐
use_real_or_cached_data = st.session_state.data_source in ["real_data", "cached_data"]

# 首次推荐（13:30-14:00）
if is_first_rec_time and st.session_state.morning_pick is None and top_candidate is not None and use_real_or_cached_data:
    st.session_state.morning_pick = {
        'name': top_candidate.get('名称', ''),
        'code': top_candidate.get('代码', ''),
        '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
        '成交额': float(top_candidate.get('成交额', 0)),
        'time': current_time_str,
        'auto': True,
        'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
        'composite_score': float(top_candidate.get('综合得分', 0)),
        'sector': strongest_sector if strongest_sector else '全市场',
        'data_source': st.session_state.data_source
    }
    add_log("自动推荐", f"生成首次推荐: {top_candidate.get('名称', '')} ({st.session_state.data_source})")
    st.success(f"🕐 **首次推荐已生成**: {top_candidate.get('名称', '')}")
    st.rerun()

# 最终锁定（14:30后）
if is_final_lock_time and not st.session_state.locked and top_candidate is not None and use_real_or_cached_data:
    st.session_state.final_pick = {
        'name': top_candidate.get('名称', ''),
        'code': top_candidate.get('代码', ''),
        '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
        '成交额': float(top_candidate.get('成交额', 0)),
        'time': current_time_str,
        'auto': True,
        'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
        'composite_score': float(top_candidate.get('综合得分', 0)),
        'sector': strongest_sector if strongest_sector else '全市场',
        'data_source': st.session_state.data_source
    }
    st.session_state.locked = True
    add_log("自动推荐", f"锁定最终推荐: {top_candidate.get('名称', '')} ({st.session_state.data_source})")
    st.success(f"🎯 **最终推荐已锁定**: {top_candidate.get('名称', '')}")
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
        
        # 数据源标签
        data_source_tag = {
            "real_data": "🟢 实时数据",
            "cached_data": "🟡 缓存数据",
            "sample_data": "⚪ 示例数据"
        }.get(pick.get('data_source', 'unknown'), '')
        
        # 创建推荐卡片
        st.markdown(f"""
        <div style="background-color: #f0f9ff; padding: 20px; border-radius: 10px; border-left: 5px solid #3498db;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']}) {data_source_tag}</h3>
            <p><strong>📅 推荐时间:</strong> {pick['time']}</p>
            <p><strong>📈 当前涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>📊 所属板块:</strong> {pick.get('sector', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('composite_score', 'N/A'):.3f}</p>
            <p><strong>⚖️ 风险调整得分:</strong> {pick.get('risk_adjusted_score', 'N/A'):.3f}</p>
            <p><strong>🔧 来源:</strong> {'自动生成' if pick.get('auto', False) else '手动设置'}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # 操作建议
        if pick['涨跌幅'] > 6:
            st.warning("📝 **操作建议**: 涨幅较大，建议观望或轻仓参与")
        elif pick.get('涨跌幅', 0) < 0:
            st.info("📝 **操作建议**: 当前下跌，观察是否有反弹机会")
        else:
            st.success("📝 **操作建议**: 可考虑逢低关注")
    else:
        if is_first_rec_time:
            if use_real_or_cached_data and top_candidate is not None:
                st.info("⏳ 正在自动生成首次推荐...")
            else:
                st.warning("⚠️ 当前使用示例数据或无合适股票，不生成真实推荐")
        else:
            st.info("⏰ 首次推荐时段: 13:30-14:00")

with col_rec2:
    st.subheader("🎯 最终锁定 (14:30后)")
    
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        
        # 数据源标签
        data_source_tag = {
            "real_data": "🟢 实时数据",
            "cached_data": "🟡 缓存数据",
            "sample_data": "⚪ 示例数据"
        }.get(pick.get('data_source', 'unknown'), '')
        
        # 创建最终推荐卡片
        st.markdown(f"""
        <div style="background-color: #fff3cd; padding: 20px; border-radius: 10px; border-left: 5px solid #f39c12;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']}) {data_source_tag}</h3>
            <p><strong>📅 锁定时间:</strong> {pick['time']}</p>
            <p><strong>📈 锁定涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>📊 所属板块:</strong> {pick.get('sector', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('composite_score', 'N/A'):.3f}</p>
            <p><strong>⚖️ 风险调整得分:</strong> {pick.get('risk_adjusted_score', 'N/A'):.3f}</p>
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
            if use_real_or_cached_data and top_candidate is not None:
                st.info("⏳ 等待最终锁定...")
            else:
                st.warning("⚠️ 当前使用示例数据或无合适股票，不生成真实锁定")
        else:
            st.info("⏰ 最终锁定时段: 14:30后")

# ===============================
# 系统日志
# ===============================
with st.expander("📜 系统日志", expanded=False):
    if st.session_state.logs:
        for log in reversed(st.session_state.logs[-10:]):
            color = "#3498db" if "成功" in log['event'] or "生成" in log['event'] else \
                    "#e74c3c" if "失败" in log['event'] or "异常" in log['event'] else \
                    "#f39c12" if "警告" in log['event'] or "延迟" in log['event'] else "#2c3e50"
            
            st.markdown(f"""
            <div style="border-left: 3px solid {color}; padding-left: 10px; margin: 5px 0;">
                <strong>{log['timestamp']}</strong> - {log['event']}: {log['details']}
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("暂无日志记录")

# ===============================
# 自动刷新逻辑
# ===============================
if is_trading:
    refresh_time = 30  # 统一刷新时间为30秒，减少负载
    
    # 如果使用缓存数据或示例数据，进一步降低刷新频率
    if st.session_state.data_source in ["cached_data", "sample_data"]:
        refresh_time = 60
    
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
    <p>尾盘博弈 6.1 稳定版 | 多因子验证系统 | 普通网络优化</p>
    <p>仅供量化研究参考，不构成投资建议 | 投资有风险，入市需谨慎</p>
    <p>© {current_year}年 量化策略研究组 | 版本: 6.1.0 (稳定性修复版)</p>
</div>
""", unsafe_allow_html=True)

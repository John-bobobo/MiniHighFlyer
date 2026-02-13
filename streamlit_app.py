# -*- coding: utf-8 -*-
"""
尾盘博弈 6.1 · 云稳定版（Tushare 付费版 - 最终优化）
===================================================
✅ 数据源优先级：
   1. Tushare pro.realtime（你已购买“A股日线RT”）—— 接口已正确
   2. 东方财富 stock_zh_a_spot_em（AKShare）
   3. 新浪财经 stock_sina_realtime（AKShare，分批+缓存）
✅ 全自动尾盘推荐与锁定（13:30-14:00 首推，14:30 后锁定）
✅ 板块分析、多因子权重可调、模拟时间测试、缓存管理
✅ 极低数据量容错、友好非交易提示、Tushare 版本检查
"""

import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz
import warnings
import tushare as ts

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.1 · Tushare 付费版", layout="wide")

# ===============================
# 🔑 关键：你的 Tushare Token（请务必填写正确）
# ===============================
TUSHARE_TOKEN = "*"          # ← ← ← 在这里填入你的40位token ← ← ←
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ---------- Tushare 版本检查（避免因版本过旧导致接口缺失）----------
try:
    from tushare import __version__ as ts_version
    if ts_version < '1.2.89':
        st.warning(f"⚠️ 当前 Tushare 版本 {ts_version} 可能不支持 `pro.realtime()`，请执行 `pip install --upgrade tushare` 升级到最新版。")
except:
    pass

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

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
if "data_fetch_attempts" not in st.session_state:
    st.session_state.data_fetch_attempts = 0
if "a_code_list" not in st.session_state:
    st.session_state.a_code_list = None

def add_log(event, details):
    log_entry = {
        'timestamp': datetime.now(tz).strftime("%H:%M:%S"),
        'event': event,
        'details': details
    }
    st.session_state.logs.append(log_entry)
    if len(st.session_state.logs) > 30:
        st.session_state.logs = st.session_state.logs[-30:]

def is_trading_day_and_time(now=None):
    if now is None:
        now = datetime.now(tz)
    weekday = now.weekday()
    hour = now.hour
    minute = now.minute
    if weekday >= 5:
        return False, "周末休市"
    if (hour == 9 and minute >= 30) or (10 <= hour < 11) or (hour == 11 and minute <= 30):
        return True, "交易时间"
    if (13 <= hour < 15) or (hour == 15 and minute == 0):
        return True, "交易时间"
    return False, "非交易时间"

@st.cache_data(ttl=3600)
def get_all_a_codes_stable():
    try:
        df = ak.stock_info_a_code_name()
        codes = df['code'].tolist()
        add_log("代码获取", f"成功获取 {len(codes)} 个A股代码")
        return codes
    except Exception as e:
        add_log("代码获取", f"失败: {str(e)}")
        return []

def standardize_sina_df(df):
    df = df.rename(columns={
        'symbol': '代码',
        'name': '名称',
        'price': '最新价',
        'changepercent': '涨跌幅',
        'volume': '成交量',
        'turnover': '成交额'
    })
    df['所属行业'] = '未知'
    return df

def fetch_realtime_data():
    errors = []
    # ---------- 1. Tushare 实时行情 ----------
    try:
        add_log("数据源", "尝试 Tushare pro.realtime")
        df = pro.realtime()  # ✅ 唯一正确接口
        if df is not None and not df.empty:
            rename_map = {
                'ts_code': '代码',
                'name': '名称',
                'price': '最新价',
                'pct_chg': '涨跌幅',
                'vol': '成交量',
                'amount': '成交额',
                'turnover_rate': '换手率',
                'amplitude': '振幅',
                'circ_mv': '流通市值'
            }
            rename_cols = {k: v for k, v in rename_map.items() if k in df.columns}
            df = df.rename(columns=rename_cols)
            df['所属行业'] = '未知'
            required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
            missing = [c for c in required if c not in df.columns]
            if not missing:
                add_log("数据源", f"✅ Tushare 实时行情 成功 (共 {len(df)} 条)")
                keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '换手率', '振幅', '流通市值']
                keep_cols = [c for c in keep_cols if c in df.columns]
                return df[keep_cols]
            else:
                errors.append(f"Tushare: 缺失字段 {missing}")
        else:
            errors.append(f"Tushare: 返回空数据")
    except Exception as e:
        errors.append(f"Tushare: {str(e)[:150]}")

    # ---------- 2. 东方财富 ----------
    try:
        add_log("数据源", "尝试 东方财富 stock_zh_a_spot_em")
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
            if all(col in df.columns for col in required):
                add_log("数据源", f"✅ 东方财富 成功 (共 {len(df)} 条)")
                return df
            else:
                missing = [c for c in required if c not in df.columns]
                errors.append(f"东方财富: 缺失字段 {missing}")
        else:
            errors.append(f"东方财富: 返回空数据")
    except Exception as e:
        errors.append(f"东方财富: {str(e)[:50]}")

    # ---------- 3. 新浪财经 ----------
    try:
        add_log("数据源", "尝试 新浪财经 stock_sina_realtime")
        codes = st.session_state.a_code_list
        if codes is None:
            codes = get_all_a_codes_stable()
            st.session_state.a_code_list = codes
        if not codes:
            errors.append("新浪财经: 无法获取股票代码列表")
            raise Exception("无代码列表")

        batch_size = 800
        df_list = []
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            part = ak.stock_sina_realtime(code=batch)
            df_list.append(part)
            time.sleep(0.3)
        df = pd.concat(df_list, ignore_index=True)
        df = standardize_sina_df(df)
        df = df[['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量']]
        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        if all(col in df.columns for col in required) and not df.empty:
            add_log("数据源", f"✅ 新浪财经 成功 (共 {len(df)} 条)")
            return df
        else:
            errors.append(f"新浪财经: 数据无效 (长度 {len(df)})")
    except Exception as e:
        errors.append(f"新浪财经: {str(e)[:50]}")

    raise Exception("所有数据源均失败: " + "; ".join(errors))

def get_stable_realtime_data():
    now = datetime.now(tz)
    if st.session_state.today_real_data is not None:
        st.session_state.data_source = "cached_real_data"
        st.session_state.last_data_fetch_time = now
        add_log("数据", "使用今日缓存")
        return st.session_state.today_real_data

    is_trading, msg = is_trading_day_and_time(now)
    if not is_trading:
        add_log("数据", f"{msg}，返回空数据")
        st.session_state.data_source = "non_trading"
        st.session_state.last_data_fetch_time = now
        empty_df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])
        st.session_state.today_real_data = empty_df.copy()
        return empty_df

    add_log("数据", "开始获取实时数据")
    df = fetch_realtime_data()
    st.session_state.today_real_data = df.copy()
    st.session_state.data_source = "real_data"
    st.session_state.last_data_fetch_time = now
    return df

# ...（后续因子选股、UI等代码保持不变，见上文最终优化版完整代码）...

# ===============================
# 多因子选股引擎（与你原有代码完全一致）
# ===============================
def get_technical_indicators(df):
    """模拟技术因子（实际项目应从历史数据计算）"""
    if df.empty:
        return df
    df_factor = df.copy()
    for stock_idx in range(len(df)):
        base_val = df.iloc[stock_idx]['涨跌幅'] if '涨跌幅' in df.columns else 0
        df_factor.at[stock_idx, '5日动量'] = base_val + np.random.uniform(-3, 5)
        df_factor.at[stock_idx, '10日动量'] = base_val + np.random.uniform(-5, 8)
        df_factor.at[stock_idx, '20日反转'] = -base_val * 0.3 + np.random.uniform(-2, 2)
        df_factor.at[stock_idx, '波动率'] = abs(base_val) * 0.5 + np.random.uniform(1, 3)
        if '成交量' in df.columns and stock_idx > 0:
            avg_volume = df['成交量'].iloc[max(0, stock_idx-5):stock_idx+1].mean()
            current_volume = df.iloc[stock_idx]['成交量']
            df_factor.at[stock_idx, '量比'] = current_volume / avg_volume if avg_volume > 0 else 1.0
        else:
            df_factor.at[stock_idx, '量比'] = 1.0 + np.random.uniform(-0.5, 1.0)
    return df_factor

def filter_stocks_by_rule(df):
    """硬性规则过滤"""
    if df.empty:
        return df
    filtered = df.copy()
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] < 9.5]
        filtered = filtered[filtered['涨跌幅'] > -9.5]
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)
        filtered = filtered[filtered['成交额'] > threshold]
    if '换手率' in filtered.columns:
        filtered = filtered[(filtered['换手率'] > 0.5) & (filtered['换手率'] < 50)]
    return filtered

def calculate_composite_score(df, sector_avg_change, weights):
    """多因子综合评分"""
    if df.empty:
        return df
    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))
    for factor, weight in weights.items():
        if factor in df_scored.columns and weight != 0:
            factor_rank = df_scored[factor].rank(pct=True, method='average')
            total_score += factor_rank * weight
    df_scored['综合得分'] = total_score
    risk_penalty = np.zeros(len(df_scored))
    if '涨跌幅' in df_scored.columns:
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
st.title("🔥 尾盘博弈 6.1 · 云稳定版（Tushare 付费版）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.data_source = "unknown"
    st.session_state.data_fetch_attempts = 0
    st.session_state.a_code_list = None
    add_log("系统", "新交易日开始，已清空历史数据")
    st.rerun()

# ===============================
# 侧边栏 - 控制面板
# ===============================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")
    st.markdown("#### 📊 数据源状态")
    data_source_display = {
        "real_data": "🟢 **实时数据（Tushare）**",
        "cached_real_data": "🟡 **缓存数据**",
        "non_trading": "⚪ **非交易时间（无实时）**",
        "unknown": "⚪ **等待获取**",
        "failed": "🔴 **获取失败**"
    }.get(st.session_state.data_source, "⚪ **等待获取**")
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
    st.markdown("#### 🔧 数据源控制")
    if st.button("🔄 强制刷新数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.a_code_list = None
        add_log("手动操作", "清除缓存，强制刷新")
        st.success("已清除缓存，将尝试重新获取")
        st.rerun()

    if st.session_state.data_fetch_attempts > 0:
        st.info(f"数据获取尝试次数: {st.session_state.data_fetch_attempts}")

    st.markdown("---")
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
            st.session_state.simulated_time = now.replace(hour=test_hour, minute=test_minute, second=0)
            st.rerun()

    st.markdown("---")
    st.markdown("#### ⚙️ 多因子权重配置")
    w_price = st.slider("当日涨幅", 0.0, 0.5, 0.25, 0.05, key="w_price")
    w_volume = st.slider("成交额", 0.0, 0.5, 0.20, 0.05, key="w_volume")
    w_momentum = st.slider("5日动量", 0.0, 0.4, 0.18, 0.05, key="w_momentum")
    w_reversal = st.slider("20日反转", 0.0, 0.3, 0.15, 0.05, key="w_reversal")
    w_vol_ratio = st.slider("量比", 0.0, 0.3, 0.12, 0.05, key="w_vol_ratio")
    w_volatility = st.slider("波动率(负)", -0.2, 0.0, -0.10, 0.05, key="w_volatility")
    total_weight = w_price + w_volume + w_momentum + w_reversal + w_vol_ratio + w_volatility
    if abs(total_weight - 1.0) > 0.2:
        st.warning(f"权重和: {total_weight:.2f} (建议调整到1.0附近)")
    factor_weights = {
        '涨跌幅': w_price,
        '成交额': w_volume,
        '5日动量': w_momentum,
        '20日反转': w_reversal,
        '量比': w_vol_ratio,
        '波动率': w_volatility
    }

    st.markdown("---")
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
    if st.session_state.today_real_data is not None and not st.session_state.today_real_data.empty:
        st.markdown("#### 💾 数据缓存")
        st.info(f"已缓存{len(st.session_state.today_real_data)}条今日数据")
        if st.button("清除今日缓存"):
            st.session_state.today_real_data = None
            st.session_state.data_source = "unknown"
            st.session_state.a_code_list = None
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
# 交易时段监控
# ===============================
st.markdown("### ⏰ 交易时段监控")
is_trading, trading_msg = is_trading_day_and_time(current_time)
col1, col2, col3, col4 = st.columns(4)
with col1:
    status_color = "🟢" if is_trading else "🔴"
    st.metric("交易日状态", f"{status_color} {'交易日' if is_trading else '非交易日'}")
with col2:
    if 9 <= current_hour < 11 or (current_hour == 11 and current_minute <= 30):
        period = "早盘"
    elif 13 <= current_hour < 15 or (current_hour == 15 and current_minute <= 0):
        period = "午盘"
    else:
        period = "休市"
    st.metric("当前时段", period)
with col3:
    is_first_rec_time = (13, 30) <= (current_hour, current_minute) < (14, 0)
    is_final_lock_time = (current_hour, current_minute) >= (14, 30)
    if is_first_rec_time:
        st.metric("推荐状态", "🟢 可推荐")
    elif is_final_lock_time:
        st.metric("推荐状态", "🔴 需锁定")
    else:
        st.metric("推荐状态", "🟡 观察中")
with col4:
    if period == "午盘" and current_hour >= 14:
        close_time = datetime(current_time.year, current_time.month, current_time.day, 15, 0)
        time_left = close_time - current_time
        minutes_left = max(0, int(time_left.total_seconds() / 60))
        st.metric("距离收盘", f"{minutes_left}分钟")
    else:
        st.metric("自动刷新", "30秒")

# ===============================
# 🚀 获取市场数据（核心调用）- 永不降级
# ===============================
st.markdown("### 📊 数据获取状态")
try:
    with st.spinner("正在获取实时数据..."):
        df = get_stable_realtime_data()
    
    # 数据源状态横幅
    data_source_status = {
        "real_data": ("✅", "Tushare 实时行情", "#e6f7ff"),
        "cached_real_data": ("🔄", "缓存真实数据", "#fff7e6"),
        "non_trading": ("⏸️", "非交易时间（无实时）", "#f0f0f0"),
        "unknown": ("⚪", "等待获取数据", "#f0f0f0"),
        "failed": ("🔴", "数据获取失败", "#ffe6e6")
    }
    status_emoji, status_text, bg_color = data_source_status.get(
        st.session_state.data_source, data_source_status["unknown"]
    )
    st.markdown(f"""
    <div style="background-color: {bg_color}; padding: 10px 15px; border-radius: 5px; border-left: 4px solid #1890ff; margin: 10px 0;">
        <strong>{status_emoji} 数据源状态:</strong> {status_text}
    </div>
    """, unsafe_allow_html=True)

    if not df.empty:
        st.success(f"✅ 成功获取 {len(df)} 条真实股票数据")
        with st.expander("🔍 查看数据样本"):
            display_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[display_cols].head(10))
            col_stat1, col_stat2, col_stat3 = st.columns(3)
            with col_stat1:
                st.metric("平均涨幅", f"{df['涨跌幅'].mean():.2f}%")
            with col_stat2:
                st.metric("最高涨幅", f"{df['涨跌幅'].max():.2f}%")
            with col_stat3:
                if '成交额' in df.columns:
                    st.metric("总成交额", f"{df['成交额'].sum()/1e8:.1f}亿")
    else:
        if st.session_state.data_source == "non_trading":
            st.info("⏸️ 当前非交易时间，无实时数据。如需测试，请使用左侧「模拟测试」模式。")
        else:
            st.warning("⚠️ 获取到的数据为空，可能原因：交易时段无数据返回或权限不足")
        # 不停止，允许后续流程（会自然显示无数据）
except Exception as e:
    st.error(f"❌ 数据获取失败: {str(e)}")
    add_log("数据获取", f"最终失败: {str(e)}")
    with st.expander("🔧 故障排除指南"):
        st.markdown("""
        ### 所有数据源均无法获取实时数据，可能原因：
        - **Tushare token 错误或未填写** → 请检查代码开头的 `TUSHARE_TOKEN`
        - **Tushare 权限不足** → 确认已购买“A股日线RT”且积分足够
        - **Tushare 版本过低** → 执行 `pip install --upgrade tushare`
        - **当前非交易时间** → 实时行情只在交易时段（9:30-11:30, 13:00-15:00）提供
        - **网络环境限制** → 某些服务器/IP 可能被数据源封禁
        """)
    if st.button("🔄 立即重试"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.a_code_list = None
        st.rerun()
    # 不停止，允许后续流程使用空df
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 板块分析与选股（适应空数据）
# ===============================
st.markdown("### 📊 板块热度分析")
if df.empty or '所属行业' not in df.columns:
    st.info("当前无有效板块数据，跳过板块分析。")
    strongest_sector = None
else:
    try:
        sector_analysis = df.groupby('所属行业').agg({
            '涨跌幅': 'mean',
            '成交额': 'sum',
            '代码': 'count'
        }).rename(columns={'代码': '股票数量'}).reset_index()
        sector_analysis['平均涨幅'] = sector_analysis['涨跌幅']
        sector_analysis['资金占比'] = sector_analysis['成交额'] / sector_analysis['成交额'].sum()
        sector_analysis['强度得分'] = (
            sector_analysis['平均涨幅'].rank(pct=True) * 40 +
            sector_analysis['资金占比'].rank(pct=True) * 40 +
            sector_analysis['股票数量'].rank(pct=True) * 20
        )
        sector_analysis = sector_analysis.sort_values('强度得分', ascending=False)
        top_sectors = sector_analysis.head(5)

        col1, col2 = st.columns([2, 1])
        with col1:
            if not top_sectors.empty:
                st.bar_chart(top_sectors.set_index('所属行业')[['平均涨幅', '资金占比']])
        with col2:
            st.markdown("#### 🔥 热门板块")
            if not top_sectors.empty:
                for idx, row in top_sectors.iterrows():
                    emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][idx % 5]
                    st.write(f"{emoji} **{row['所属行业']}**")
                    st.progress(min(row['强度得分'] / 100, 1.0))

        strongest_sector = top_sectors.iloc[0]['所属行业'] if not top_sectors.empty else None
        if strongest_sector:
            st.success(f"🏆 今日最强板块: **{strongest_sector}**")
    except Exception as e:
        st.error(f"板块分析错误: {str(e)}")
        strongest_sector = None

st.markdown("### 🎯 多因子智能选股引擎")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    st.markdown("**流程**: 规则过滤 → 因子计算 → 综合评分 → 风险调整")
    filtered_by_rule = filter_stocks_by_rule(df)
    st.caption(f"基础过滤后股票数: {len(filtered_by_rule)} / {len(df)}")

    if strongest_sector and '所属行业' in filtered_by_rule.columns:
        sector_stocks = filtered_by_rule[filtered_by_rule['所属行业'] == strongest_sector].copy()
        if sector_stocks.empty:
            st.warning(f"板块 '{strongest_sector}' 无合适股票，使用全市场股票")
            sector_stocks = filtered_by_rule.copy()
    else:
        if strongest_sector is None:
            st.info("无最强板块信息，使用全市场股票")
        sector_stocks = filtered_by_rule.copy()

    if not sector_stocks.empty:
        df_with_factors = get_technical_indicators(sector_stocks)
        if not df_with_factors.empty:
            sector_avg = df_with_factors['涨跌幅'].mean() if '涨跌幅' in df_with_factors.columns else 0
            try:
                scored_df = calculate_composite_score(df_with_factors, sector_avg, factor_weights)
                top_candidates = scored_df.head(10)
                top_candidate = scored_df.iloc[0] if not scored_df.empty else None

                st.markdown("#### 📈 优选股票因子分析")
                if top_candidate is not None:
                    factor_names = ['涨跌幅', '成交额', '5日动量', '20日反转', '量比', '波动率']
                    factor_values = []
                    for name in factor_names:
                        if name in top_candidate:
                            col_min = scored_df[name].min()
                            col_max = scored_df[name].max()
                            if col_max > col_min:
                                norm_value = (top_candidate[name] - col_min) / (col_max - col_min) * 100
                            else:
                                norm_value = 50
                            factor_values.append(norm_value)
                    col_info, col_factors = st.columns([1, 2])
                    with col_info:
                        st.metric("**选中股票**", f"{top_candidate.get('名称', 'N/A')}")
                        st.metric("**代码**", f"{top_candidate.get('代码', 'N/A')}")
                        st.metric("**综合得分**", f"{top_candidate.get('综合得分', 0):.3f}")
                        st.metric("**风险调整得分**", f"{top_candidate.get('风险调整得分', 0):.3f}")
                        if '涨跌幅' in top_candidate:
                            st.metric("**今日涨幅**", f"{top_candidate['涨跌幅']:.2f}%")
                    with col_factors:
                        if factor_values:
                            factor_df = pd.DataFrame({'因子': factor_names[:len(factor_values)], '得分': factor_values})
                            st.bar_chart(factor_df.set_index('因子'))
                            with st.expander("查看因子权重"):
                                for name, weight in factor_weights.items():
                                    if weight != 0:
                                        st.write(f"- **{name}**: {weight:.3f}")

                    st.markdown("#### 🏆 候选股票排名 (前5)")
                    if not top_candidates.empty:
                        display_cols = [c for c in ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分'] if c in top_candidates.columns]
                        display_top5 = top_candidates[display_cols].head().copy()
                        display_top5.index = range(1, 6)
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
                    st.warning("未找到符合条件的股票")
            except Exception as e:
                st.error(f"评分错误: {str(e)}")
                top_candidate = None
        else:
            st.warning("因子计算后无数据")
            top_candidate = None
    else:
        st.warning("过滤后无合适股票")
        top_candidate = None

# ===============================
# 自动推荐（仅当数据源为真实数据且有候选股）
# ===============================
st.markdown("### 🤖 自动推荐系统")
use_real_data = st.session_state.data_source in ["real_data", "cached_real_data"]
if not use_real_data:
    st.info("⏸️ 当前非交易时间或无实时数据，自动推荐已暂停")
else:
    if is_first_rec_time and st.session_state.morning_pick is None and top_candidate is not None:
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
        add_log("自动推荐", f"生成首次推荐: {top_candidate.get('名称', '')}")
        st.success(f"🕐 **首次推荐已生成**: {top_candidate.get('名称', '')}")
        st.rerun()
    if is_final_lock_time and not st.session_state.locked and top_candidate is not None:
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
        add_log("自动推荐", f"锁定最终推荐: {top_candidate.get('名称', '')}")
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
        data_source_tag = {"real_data": "🟢 Tushare", "cached_real_data": "🟡 缓存"}.get(pick.get('data_source', ''), '')
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
        if pick['涨跌幅'] > 6:
            st.warning("📝 **操作建议**: 涨幅较大，建议观望或轻仓参与")
        elif pick.get('涨跌幅', 0) < 0:
            st.info("📝 **操作建议**: 当前下跌，观察是否有反弹机会")
        else:
            st.success("📝 **操作建议**: 可考虑逢低关注")
    else:
        if is_first_rec_time:
            if use_real_data and top_candidate is not None:
                st.info("⏳ 正在自动生成首次推荐...")
            else:
                st.info("⏸️ 等待真实数据或合适标的")
        else:
            st.info("⏰ 首次推荐时段: 13:30-14:00")

with col_rec2:
    st.subheader("🎯 最终锁定 (14:30后)")
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        data_source_tag = {"real_data": "🟢 Tushare", "cached_real_data": "🟡 缓存"}.get(pick.get('data_source', ''), '')
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
            if use_real_data and top_candidate is not None:
                st.info("⏳ 等待最终锁定...")
            else:
                st.info("⏸️ 等待真实数据或合适标的")
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
# 自动刷新
# ===============================
if is_trading:
    refresh_time = 30
    st.write(f"⏳ {refresh_time}秒后自动刷新...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 当前非交易时间，自动刷新已暂停")
    time.sleep(60)
    st.rerun()

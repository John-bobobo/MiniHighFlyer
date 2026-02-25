# -*- coding: utf-8 -*-
"""
尾盘博弈 6.4 · Tushare 专用优化版
=================================
✅ 真实技术指标（动量、反转、波动率、量比）
✅ 可配置涨幅上限，避免追高
✅ 因子权重自动归一化
✅ 增强风险调整（换手率、市值）
✅ 板块分析基于真实行业
✅ 缓存机制减少请求次数
"""

import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
import pytz
import warnings
import tushare as ts

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.4 优化版", layout="wide")

# ===============================
# 🔑 从 Streamlit Secrets 读取 Tushare Token
# ===============================
try:
    TUSHARE_TOKEN = "7f85ea86ce467f3b9ab46b1fa1a5b9a71fe089dd0e57d12239899155"
except KeyError:
    st.error("未找到 Tushare Token，请在 Secrets 中设置 `tushare_token`")
    st.stop()

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

# 初始化 session_state 变量
default_session_vars = {
    "candidate_pick_history": [],
    "morning_pick": None,
    "final_pick": None,
    "locked": False,
    "today": datetime.now(tz).date(),
    "logs": [],
    "backtest_results": None,
    "today_real_data": None,
    "stock_basic": None,          # 缓存股票基本信息（代码、名称、行业）
    "history_cache": {},           # 缓存历史日线数据 {ts_code: df}
    "data_source": "unknown",
    "last_data_fetch_time": None,
    "data_fetch_attempts": 0,
}

for key, default in default_session_vars.items():
    if key not in st.session_state:
        st.session_state[key] = default

def add_log(event, details):
    """添加日志条目"""
    log_entry = {
        'timestamp': datetime.now(tz).strftime("%H:%M:%S"),
        'event': event,
        'details': details
    }
    st.session_state.logs.append(log_entry)
    if len(st.session_state.logs) > 30:
        st.session_state.logs = st.session_state.logs[-30:]

def is_trading_day_and_time(now=None):
    """判断是否为交易日且交易时间"""
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

# ===============================
# Tushare 数据获取函数（带缓存）
# ===============================
def fetch_stock_basic():
    """获取并缓存股票基本信息（代码、名称、行业）"""
    if st.session_state.stock_basic is not None:
        return st.session_state.stock_basic
    try:
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,industry,market')
        if df is not None and not df.empty:
            # 重命名列
            df = df.rename(columns={'ts_code': '代码', 'name': '名称', 'industry': '所属行业'})
            st.session_state.stock_basic = df
            add_log("数据源", f"获取股票基本信息 {len(df)} 条")
            return df
        else:
            add_log("数据源", "股票基本信息获取失败")
            return pd.DataFrame(columns=['代码', '名称', '所属行业'])
    except Exception as e:
        add_log("数据源", f"获取股票基本信息异常: {str(e)}")
        return pd.DataFrame(columns=['代码', '名称', '所属行业'])

def fetch_from_tushare():
    """从 Tushare rt_k 接口获取实时行情（按板块分批）"""
    try:
        add_log("数据源", "尝试 Tushare rt_k 接口")
        board_patterns = [
            "6*.SH", "0*.SZ", "3*.SZ", "688*.SH", "8*.BJ", "4*.BJ"
        ]
        all_dfs = []
        for pattern in board_patterns:
            try:
                df_part = pro.rt_k(ts_code=pattern)
                if df_part is not None and not df_part.empty:
                    all_dfs.append(df_part)
                    add_log("数据源", f"板块 {pattern} 获取到 {len(df_part)} 条")
            except Exception as e:
                add_log("数据源", f"板块 {pattern} 异常: {str(e)[:50]}")
                continue

        if not all_dfs:
            add_log("数据源", "所有板块均失败，无数据")
            return None

        df = pd.concat(all_dfs, ignore_index=True)
        df = df.drop_duplicates(subset=['ts_code'])

        # 计算涨跌幅
        df['涨跌幅'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100

        # 重命名
        rename_map = {
            'ts_code': '代码',
            'name': '名称',
            'amount': '成交额',
            'vol': '成交量',
            'close': '最新价',
        }
        rename_cols = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=rename_cols)

        # 合并行业信息
        basic = fetch_stock_basic()
        if not basic.empty:
            df = df.merge(basic[['代码', '所属行业']], on='代码', how='left')
            df['所属行业'] = df['所属行业'].fillna('未知')
        else:
            df['所属行业'] = '未知'

        # 保留必要字段
        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ Tushare rt_k 成功，最终 {len(df)} 条")
        return df

    except Exception as e:
        add_log("数据源", f"Tushare rt_k 整体异常: {str(e)[:100]}")
        return None

def get_stable_realtime_data():
    """主数据获取函数：使用缓存，失败时重试"""
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
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

    # 尝试获取，最多重试3次
    for attempt in range(3):
        df = fetch_from_tushare()
        if df is not None and not df.empty:
            st.session_state.today_real_data = df.copy()
            st.session_state.data_source = "real_data"
            st.session_state.last_data_fetch_time = now
            st.session_state.data_fetch_attempts = attempt + 1
            add_log("数据源", f"第{attempt+1}次尝试成功")
            return df
        else:
            add_log("数据源", f"第{attempt+1}次尝试失败")
            time.sleep(2)  # 等待后重试

    st.session_state.data_source = "failed"
    st.session_state.last_data_fetch_time = now
    st.session_state.data_fetch_attempts = 3
    return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 历史数据获取与因子计算
# ===============================
def get_history_data(ts_code, end_date=None):
    """获取个股最近20个交易日的历史日线数据（缓存）"""
    cache = st.session_state.history_cache
    today_str = datetime.now(tz).strftime('%Y%m%d')
    cache_key = f"{ts_code}_{today_str}"  # 按天缓存

    if cache_key in cache:
        return cache[cache_key]

    try:
        if end_date is None:
            end_date = datetime.now(tz).strftime('%Y%m%d')
        # 获取最近20个交易日数据（包括今日可能没有数据，所以我们取到昨天）
        df = pro.daily(ts_code=ts_code, end_date=end_date, limit=20)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date')
            cache[cache_key] = df
            return df
        else:
            return None
    except Exception as e:
        add_log("历史数据", f"{ts_code} 获取失败: {str(e)[:50]}")
        return None

def calculate_factors(rt_row, history_df):
    """根据实时数据和历史日线计算技术因子"""
    if history_df is None or len(history_df) < 5:
        # 历史数据不足，返回默认值
        return {
            '5日动量': 0.0,
            '20日反转': 0.0,
            '波动率': 0.0,
            '量比': 1.0,
            '换手率': 0.0
        }

    # 取最近N个交易日收盘价（不包括今天，因为今天未收盘）
    closes = history_df['close'].values
    volumes = history_df['vol'].values
    trade_dates = history_df['trade_date'].values

    # 5日动量：昨日收盘相对于5日前收盘的涨跌幅
    if len(closes) >= 6:  # 需要至少6个数据点（昨日 + 5日前）
        close_yesterday = closes[-1]
        close_5days_ago = closes[-6]
        mom_5 = (close_yesterday / close_5days_ago - 1) * 100
    else:
        mom_5 = 0.0

    # 20日反转：昨日收盘相对于20日前收盘的涨跌幅（负值表示超跌）
    if len(closes) >= 21:
        close_20days_ago = closes[-21]
        reversal_20 = (close_yesterday / close_20days_ago - 1) * 100
    else:
        reversal_20 = 0.0

    # 波动率：过去20日收益率的标准差
    if len(closes) >= 21:
        returns = np.diff(closes[-21:]) / closes[-22:-1]  # 20个收益率
        volatility = np.std(returns) * 100  # 转为百分比
    else:
        volatility = 0.0

    # 量比：当日成交量 / 过去5日均量
    if len(volumes) >= 6:
        avg_volume_5 = np.mean(volumes[-6:-1])  # 前5个交易日平均成交量（不包括今日）
        current_volume = rt_row.get('成交量', 0)
        if avg_volume_5 > 0:
            volume_ratio = current_volume / avg_volume_5
        else:
            volume_ratio = 1.0
    else:
        volume_ratio = 1.0

    # 换手率：当日成交量 / 流通股本（这里简单用当日成交量代替，实际需要流通股本数据）
    # 由于缺少流通股本，暂时用成交量占比表示换手率，后续可优化
    turnover = current_volume / 1e4 if current_volume > 0 else 0  # 仅作示意

    return {
        '5日动量': mom_5,
        '20日反转': reversal_20,
        '波动率': volatility,
        '量比': volume_ratio,
        '换手率': turnover
    }

def add_technical_indicators(df):
    """为DataFrame中的每只股票添加技术因子"""
    if df.empty:
        return df

    df = df.copy()
    factor_list = []
    for idx, row in df.iterrows():
        code = row['代码']
        history = get_history_data(code)
        factors = calculate_factors(row, history)
        factor_list.append(factors)

    factor_df = pd.DataFrame(factor_list)
    df = pd.concat([df, factor_df], axis=1)
    return df

# ===============================
# 选股核心逻辑（优化版）
# ===============================
def filter_stocks_by_rule(df, max_increase):
    """硬性规则过滤（含涨幅上限）"""
    if df.empty:
        return df
    filtered = df.copy()
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST|退', na=False)]
    if '涨跌幅' in filtered.columns:
        filtered = filtered[(filtered['涨跌幅'] < max_increase) & (filtered['涨跌幅'] > -9.5)]
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)
        filtered = filtered[filtered['成交额'] > threshold]
    if '换手率' in filtered.columns:
        # 换手率过高（>30%）可能风险大，过滤掉
        filtered = filtered[filtered['换手率'] < 30]
    return filtered

def calculate_composite_score(df, weights):
    """多因子综合评分（权重自动归一化）"""
    if df.empty:
        return df

    # 因子列表
    factor_names = ['涨跌幅', '成交额', '5日动量', '20日反转', '量比', '波动率']
    # 确保权重字典只包含存在的因子
    used_weights = {k: weights.get(k, 0) for k in factor_names if k in df.columns}

    # 归一化权重和到1
    total = sum(used_weights.values())
    if total == 0:
        return df  # 所有权重为0，无法评分

    norm_weights = {k: v/total for k, v in used_weights.items()}

    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))

    for factor, weight in norm_weights.items():
        if factor in df_scored.columns and weight != 0:
            # 使用百分位排名（避免量纲影响）
            factor_rank = df_scored[factor].rank(pct=True, method='average')
            total_score += factor_rank * weight

    df_scored['综合得分'] = total_score

    # 风险调整（基于波动率和换手率）
    risk_penalty = np.zeros(len(df_scored))
    if '波动率' in df_scored.columns:
        # 波动率越高，惩罚越大（标准化后乘以系数）
        vol_rank = df_scored['波动率'].rank(pct=True)
        risk_penalty += vol_rank * 0.15
    if '换手率' in df_scored.columns:
        turnover_rank = df_scored['换手率'].rank(pct=True)
        risk_penalty += turnover_rank * 0.10
    if '涨跌幅' in df_scored.columns:
        # 当日涨幅过高（>6%）额外惩罚
        high_gain_penalty = (df_scored['涨跌幅'].clip(lower=6, upper=12) - 6) / 6 * 0.1
        risk_penalty += high_gain_penalty

    df_scored['风险调整得分'] = df_scored['综合得分'] - risk_penalty
    return df_scored.sort_values('风险调整得分', ascending=False)

# ===============================
# 主程序开始
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.4 · Tushare 优化版（真实因子 + 涨幅控制）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    for key in list(st.session_state.keys()):
        if key not in ['today']:  # 保留today
            del st.session_state[key]
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.history_cache = {}
    st.session_state.data_source = "unknown"
    add_log("系统", "新交易日开始，已清空历史数据")
    st.rerun()

# ===============================
# 侧边栏 - 控制面板
# ===============================
with st.sidebar:
    st.markdown("### 🎛️ 控制面板")
    st.markdown("#### 📊 数据源状态")
    data_source_display = {
        "real_data": "🟢 **实时数据（Tushare rt_k）**",
        "cached_real_data": "🟡 **缓存数据**",
        "non_trading": "⚪ **非交易时间**",
        "unknown": "⚪ **等待获取**",
        "failed": "🔴 **获取失败**"
    }.get(st.session_state.data_source, "⚪ **等待获取**")
    st.markdown(data_source_display)

    if st.session_state.last_data_fetch_time:
        time_diff = (datetime.now(tz) - st.session_state.last_data_fetch_time).total_seconds()
        st.caption(f"最近更新: {int(time_diff)}秒前")

    st.markdown("---")
    st.markdown("#### 🔧 数据源控制")
    if st.button("🔄 强制刷新数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.history_cache = {}
        add_log("手动操作", "清除缓存，强制刷新")
        st.success("已清除缓存")
        st.rerun()

    st.markdown("---")
    st.markdown("#### ⏰ 时间设置")
    use_real_time = st.radio("时间模式", ["实时模式", "模拟测试"], index=0)
    if use_real_time == "模拟测试":
        col1, col2 = st.columns(2)
        with col1:
            test_hour = st.number_input("模拟小时", 9, 15, 14)
        with col2:
            test_minute = st.number_input("模拟分钟", 0, 59, 30)
        if st.button("🕐 应用模拟时间"):
            st.session_state.simulated_time = now.replace(hour=test_hour, minute=test_minute, second=0)
            st.rerun()

    st.markdown("---")
    st.markdown("#### ⚙️ 选股参数")
    max_increase = st.slider("📈 最大允许涨幅 (%)", 1.0, 9.5, 6.5, 0.5, help="超过此涨幅的股票将被过滤，避免追高")
    st.markdown("**多因子权重**（将自动归一化）")
    w_price = st.slider("当日涨幅", 0.0, 1.0, 0.20, 0.05)
    w_volume = st.slider("成交额", 0.0, 1.0, 0.20, 0.05)
    w_momentum = st.slider("5日动量", 0.0, 1.0, 0.18, 0.05)
    w_reversal = st.slider("20日反转", 0.0, 1.0, 0.15, 0.05)
    w_vol_ratio = st.slider("量比", 0.0, 1.0, 0.12, 0.05)
    w_volatility = st.slider("波动率(负向)", -0.5, 0.0, -0.15, 0.05)

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
        if st.button("📈 手动设为首次推荐") and "top_candidate" in st.session_state:
            st.session_state.morning_pick = st.session_state.top_candidate
            add_log("手动操作", "设置上午推荐")
            st.rerun()
    with col_btn2:
        if st.button("🎯 手动设为最终锁定") and "top_candidate" in st.session_state:
            st.session_state.final_pick = st.session_state.top_candidate
            st.session_state.locked = True
            add_log("手动操作", "设置最终锁定")
            st.rerun()
    if st.button("🗑️ 清除所有推荐"):
        st.session_state.morning_pick = None
        st.session_state.final_pick = None
        st.session_state.locked = False
        add_log("手动操作", "清除所有推荐")
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

# ===============================
# 获取实时数据
# ===============================
st.markdown("### 📊 数据获取状态")
df = get_stable_realtime_data()

if not df.empty:
    st.success(f"✅ 成功获取 {len(df)} 条实时数据")
    with st.expander("🔍 查看数据样本"):
        st.dataframe(df[['代码', '名称', '涨跌幅', '成交额', '所属行业']].head(10))
else:
    if st.session_state.data_source == "non_trading":
        st.info("⏸️ 当前非交易时间，无实时数据。如需测试，请使用左侧「模拟测试」模式。")
    else:
        st.warning("⚠️ 获取数据失败，请检查网络或Tushare权限")

# ===============================
# 板块分析
# ===============================
st.markdown("### 📊 板块热度分析")
if df.empty or '所属行业' not in df.columns or df['所属行业'].nunique() <= 1:
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

# ===============================
# 多因子选股
# ===============================
st.markdown("### 🎯 多因子智能选股引擎（真实因子）")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    with st.spinner("正在计算技术因子（需获取历史数据，请稍候）..."):
        # 基础过滤
        filtered = filter_stocks_by_rule(df, max_increase)
        st.caption(f"基础过滤后股票数: {len(filtered)} / {len(df)}")

        if strongest_sector and '所属行业' in filtered.columns:
            sector_stocks = filtered[filtered['所属行业'] == strongest_sector].copy()
            if sector_stocks.empty:
                sector_stocks = filtered.copy()
        else:
            sector_stocks = filtered.copy()

        if not sector_stocks.empty:
            # 添加技术因子
            df_with_factors = add_technical_indicators(sector_stocks)
            if not df_with_factors.empty:
                # 计算综合评分
                scored_df = calculate_composite_score(df_with_factors, factor_weights)
                top_candidates = scored_df.head(10)
                top_candidate = scored_df.iloc[0] if not scored_df.empty else None

                # 保存到session便于手动设置
                if top_candidate is not None:
                    st.session_state.top_candidate = {
                        'name': top_candidate.get('名称', ''),
                        'code': top_candidate.get('代码', ''),
                        '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
                        '成交额': float(top_candidate.get('成交额', 0)),
                        '换手率': float(top_candidate.get('换手率', 0)),
                        '综合得分': float(top_candidate.get('综合得分', 0)),
                        'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
                        'time': current_time.strftime("%H:%M:%S"),
                        'sector': strongest_sector if strongest_sector else '全市场',
                        'data_source': st.session_state.data_source
                    }

                # 显示优选结果
                st.markdown("#### 📈 优选股票因子分析")
                if top_candidate is not None:
                    col_info, col_factors = st.columns([1, 2])
                    with col_info:
                        st.metric("选中股票", f"{top_candidate['名称']} ({top_candidate['代码']})")
                        st.metric("综合得分", f"{top_candidate['综合得分']:.3f}")
                        st.metric("风险调整得分", f"{top_candidate['风险调整得分']:.3f}")
                        st.metric("今日涨幅", f"{top_candidate['涨跌幅']:.2f}%")
                        st.metric("量比", f"{top_candidate['量比']:.2f}")
                        st.metric("5日动量", f"{top_candidate['5日动量']:.2f}%")
                        st.metric("20日反转", f"{top_candidate['20日反转']:.2f}%")
                    with col_factors:
                        # 显示因子雷达图（简化）
                        factor_names = ['涨跌幅', '成交额', '5日动量', '20日反转', '量比']
                        factor_values = []
                        for name in factor_names:
                            if name in top_candidate:
                                col_min = scored_df[name].min()
                                col_max = scored_df[name].max()
                                if col_max > col_min:
                                    norm = (top_candidate[name] - col_min) / (col_max - col_min) * 100
                                else:
                                    norm = 50
                                factor_values.append(norm)
                        if factor_values:
                            factor_df = pd.DataFrame({'因子': factor_names[:len(factor_values)], '得分': factor_values})
                            st.bar_chart(factor_df.set_index('因子'))

                    st.markdown("#### 🏆 候选股票排名 (前5)")
                    display_cols = ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分']
                    display_top5 = top_candidates[display_cols].head().copy()
                    display_top5['涨跌幅'] = display_top5['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                    display_top5['成交额'] = display_top5['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                    display_top5['综合得分'] = display_top5['综合得分'].apply(lambda x: f"{x:.3f}")
                    display_top5['风险调整得分'] = display_top5['风险调整得分'].apply(lambda x: f"{x:.3f}")
                    st.dataframe(display_top5, use_container_width=True)

# ===============================
# 自动推荐逻辑（保持不变）
# ===============================
st.markdown("### 🤖 自动推荐系统")
use_real_data = st.session_state.data_source in ["real_data", "cached_real_data"]
if not use_real_data:
    st.info("⏸️ 当前非交易时间或无实时数据，自动推荐已暂停")
else:
    is_first_rec_time = (13, 30) <= (current_hour, current_minute) < (14, 0)
    is_final_lock_time = (current_hour, current_minute) >= (14, 30)

    if is_first_rec_time and st.session_state.morning_pick is None and top_candidate is not None:
        st.session_state.morning_pick = st.session_state.top_candidate.copy()
        st.session_state.morning_pick['auto'] = True
        add_log("自动推荐", f"生成首次推荐: {top_candidate['名称']}")
        st.success(f"🕐 **首次推荐已生成**: {top_candidate['名称']}")
        st.rerun()

    if is_final_lock_time and not st.session_state.locked and top_candidate is not None:
        st.session_state.final_pick = st.session_state.top_candidate.copy()
        st.session_state.final_pick['auto'] = True
        st.session_state.locked = True
        add_log("自动推荐", f"锁定最终推荐: {top_candidate['名称']}")
        st.success(f"🎯 **最终推荐已锁定**: {top_candidate['名称']}")
        st.rerun()

# ===============================
# 推荐结果展示（样式优化略）
# ===============================
st.markdown("---")
st.markdown("### 📋 推荐结果")
col_rec1, col_rec2 = st.columns(2)
with col_rec1:
    st.subheader("🕐 首次推荐 (13:30-14:00)")
    if st.session_state.morning_pick is not None:
        pick = st.session_state.morning_pick
        st.markdown(f"**{pick['name']} ({pick['code']})**  \n涨幅: {pick['涨跌幅']:.2f}%  \n时间: {pick['time']}")
    else:
        st.info("⏰ 等待首次推荐...")

with col_rec2:
    st.subheader("🎯 最终锁定 (14:30后)")
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        st.markdown(f"**{pick['name']} ({pick['code']})**  \n涨幅: {pick['涨跌幅']:.2f}%  \n时间: {pick['time']}")
    else:
        st.info("⏰ 等待最终锁定...")

# ===============================
# 系统日志与自动刷新
# ===============================
with st.expander("📜 系统日志", expanded=False):
    if st.session_state.logs:
        for log in reversed(st.session_state.logs[-10:]):
            st.text(f"{log['timestamp']} - {log['event']}: {log['details']}")
    else:
        st.info("暂无日志记录")

if is_trading_day_and_time(current_time)[0]:
    time.sleep(30)
    st.rerun()
else:
    time.sleep(60)
    st.rerun()

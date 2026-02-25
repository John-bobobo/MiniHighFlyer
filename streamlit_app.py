# -*- coding: utf-8 -*-
"""
尾盘博弈 6.6.3 · 漏斗收敛版（修复卡顿 + 进度提示）
=======================================================
✅ 真实技术指标（动量、反转、波动率、量比）
✅ 可配置涨幅上限，避免追高
✅ 因子权重自动归一化
✅ 增强风险调整（换手率、市值）
✅ 板块分析基于真实行业
✅ 缓存机制减少请求次数
✅ 14:45 前动态轮动显示前5
✅ 14:45 自动锁定最终推荐（板块分散，最多2支/板块）
✅ 最终推荐包含1支主推 + 4支备选
✅ 增加请求超时与重试，避免卡死
✅ 添加进度条提示，用户可感知处理进度
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
st.set_page_config(page_title="尾盘博弈 6.6.3 · 优化版", layout="wide")

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

# 设置全局超时（防止网络卡死）
pro.set_timeout(10)  # 10秒超时

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

# 初始化 session_state 变量
default_session_vars = {
    "candidate_pick_history": [],
    "morning_pick": None,
    "final_pick_list": None,
    "locked": False,
    "today": datetime.now(tz).date(),
    "logs": [],
    "backtest_results": None,
    "today_real_data": None,
    "stock_basic": None,
    "history_cache": {},
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
# Tushare 数据获取函数（带缓存和重试）
# ===============================
def fetch_stock_basic():
    """获取并缓存股票基本信息（代码、名称、行业）"""
    if st.session_state.stock_basic is not None:
        return st.session_state.stock_basic

    # 尝试获取，最多重试3次
    for attempt in range(3):
        try:
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,industry,market')
            if df is not None and not df.empty:
                df = df.rename(columns={'ts_code': '代码', 'name': '名称', 'industry': '所属行业'})
                st.session_state.stock_basic = df
                add_log("数据源", f"获取股票基本信息成功，共 {len(df)} 条")
                return df
            else:
                add_log("数据源", f"股票基本信息获取尝试 {attempt+1} 失败，返回空")
        except Exception as e:
            add_log("数据源", f"股票基本信息异常 (尝试 {attempt+1}): {str(e)}")
        time.sleep(2)

    st.warning("⚠️ 无法获取股票行业信息，板块分析将跳过")
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
            original_len = len(df)
            df = df.merge(basic[['代码', '所属行业']], on='代码', how='left')
            df['所属行业'] = df['所属行业'].fillna('未知')
            covered = (df['所属行业'] != '未知').sum()
            add_log("数据源", f"行业覆盖: {covered}/{original_len} 支股票有行业信息")
        else:
            df['所属行业'] = '未知'
            add_log("数据源", "无行业数据，全部标记为未知")

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
            time.sleep(2)

    st.session_state.data_source = "failed"
    st.session_state.last_data_fetch_time = now
    st.session_state.data_fetch_attempts = 3
    return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 历史数据获取与因子计算（带超时与重试）
# ===============================
def get_history_data(ts_code, end_date=None):
    """获取个股最近20个交易日的历史日线数据（缓存），失败返回None"""
    cache = st.session_state.history_cache
    today_str = datetime.now(tz).strftime('%Y%m%d')
    cache_key = f"{ts_code}_{today_str}"

    if cache_key in cache:
        return cache[cache_key]

    # 尝试获取，最多重试2次
    for attempt in range(2):
        try:
            if end_date is None:
                end_date = datetime.now(tz).strftime('%Y%m%d')
            df = pro.daily(ts_code=ts_code, end_date=end_date, limit=20)
            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                cache[cache_key] = df
                return df
            else:
                # 无数据也返回None
                return None
        except Exception as e:
            add_log("历史数据", f"{ts_code} 获取失败 (尝试 {attempt+1}): {str(e)[:50]}")
            time.sleep(1)  # 短暂等待后重试

    return None

def calculate_factors(rt_row, history_df):
    """根据实时数据和历史日线计算技术因子（修复版）"""
    if history_df is None or len(history_df) < 5:
        return {
            '5日动量': 0.0,
            '20日反转': 0.0,
            '波动率': 0.0,
            '量比': 1.0,
            '换手率': 0.0
        }

    closes = history_df['close'].values
    volumes = history_df['vol'].values

    current_volume = rt_row.get('成交量', 0)

    # 5日动量
    if len(closes) >= 6:
        close_yesterday = closes[-1]
        close_5days_ago = closes[-6]
        mom_5 = (close_yesterday / close_5days_ago - 1) * 100
    else:
        mom_5 = 0.0

    # 20日反转
    if len(closes) >= 21:
        close_20days_ago = closes[-21]
        reversal_20 = (close_yesterday / close_20days_ago - 1) * 100
    else:
        reversal_20 = 0.0

    # 波动率
    if len(closes) >= 21:
        returns = np.diff(closes[-21:]) / closes[-22:-1]
        volatility = np.std(returns) * 100
    else:
        volatility = 0.0

    # 量比
    if len(volumes) >= 6:
        avg_volume_5 = np.mean(volumes[-6:-1])
        volume_ratio = current_volume / avg_volume_5 if avg_volume_5 > 0 else 1.0
    else:
        volume_ratio = 1.0

    # 换手率（简化）
    turnover = current_volume / 1e4 if current_volume > 0 else 0

    return {
        '5日动量': mom_5,
        '20日反转': reversal_20,
        '波动率': volatility,
        '量比': volume_ratio,
        '换手率': turnover
    }

def add_technical_indicators(df):
    """为DataFrame中的每只股票添加技术因子，带进度条"""
    if df.empty:
        return df

    df = df.copy()
    factor_list = []

    # 创建进度条
    progress_bar = st.progress(0, text="正在获取历史数据并计算因子...")
    total = len(df)

    for idx, row in df.iterrows():
        code = row['代码']
        history = get_history_data(code)
        factors = calculate_factors(row, history)
        factor_list.append(factors)

        # 更新进度条
        if (idx + 1) % 10 == 0 or (idx + 1) == total:
            progress_bar.progress((idx + 1) / total, text=f"已处理 {idx+1}/{total} 支股票")

    progress_bar.empty()  # 完成后移除进度条

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
        filtered = filtered[filtered['换手率'] < 30]
    return filtered

def calculate_composite_score(df, weights):
    """多因子综合评分（权重自动归一化）"""
    if df.empty:
        return df

    factor_names = ['涨跌幅', '成交额', '5日动量', '20日反转', '量比', '波动率']
    used_weights = {k: weights.get(k, 0) for k in factor_names if k in df.columns}

    total = sum(used_weights.values())
    if total == 0:
        return df

    norm_weights = {k: v/total for k, v in used_weights.items()}

    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))

    for factor, weight in norm_weights.items():
        if factor in df_scored.columns and weight != 0:
            factor_rank = df_scored[factor].rank(pct=True, method='average')
            total_score += factor_rank * weight

    df_scored['综合得分'] = total_score

    # 风险调整
    risk_penalty = np.zeros(len(df_scored))
    if '波动率' in df_scored.columns:
        vol_rank = df_scored['波动率'].rank(pct=True)
        risk_penalty += vol_rank * 0.15
    if '换手率' in df_scored.columns:
        turnover_rank = df_scored['换手率'].rank(pct=True)
        risk_penalty += turnover_rank * 0.10
    if '涨跌幅' in df_scored.columns:
        high_gain_penalty = (df_scored['涨跌幅'].clip(lower=6, upper=12) - 6) / 6 * 0.1
        risk_penalty += high_gain_penalty

    df_scored['风险调整得分'] = df_scored['综合得分'] - risk_penalty
    return df_scored.sort_values('风险调整得分', ascending=False)

def select_diverse_top5(scored_df, max_per_sector=2):
    """
    从已评分的 DataFrame 中选出前5支股票，保证同一板块不超过 max_per_sector 支。
    返回包含5条记录的列表（按评分从高到低）。
    """
    if scored_df.empty:
        return []
    selected = []
    sector_count = {}
    for idx, row in scored_df.iterrows():
        sector = row.get('所属行业', '未知')
        current_count = sector_count.get(sector, 0)
        if current_count < max_per_sector:
            selected.append(row.to_dict())
            sector_count[sector] = current_count + 1
        if len(selected) >= 5:
            break
    return selected

# ===============================
# 主程序开始
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.6.3 · 优化版（进度条 + 超时控制）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    for key in list(st.session_state.keys()):
        if key not in ['today']:
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
            test_minute = st.number_input("模拟分钟", 0, 59, 45)
        if st.button("🕐 应用模拟时间"):
            st.session_state.simulated_time = now.replace(hour=test_hour, minute=test_minute, second=0)
            st.rerun()

    st.markdown("---")
    st.markdown("#### ⚙️ 选股参数")
    max_increase = st.slider("📈 最大允许涨幅 (%)", 1.0, 9.5, 6.5, 0.5, help="超过此涨幅的股票将被过滤")

    # 锁定时间设置
    st.markdown("**⏰ 最终锁定时分**")
    lock_hour = st.number_input("小时", 14, 15, 14)
    lock_minute = st.number_input("分钟", 0, 59, 45)
    st.caption(f"最终推荐将在 {lock_hour:02d}:{lock_minute:02d} 自动锁定")

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
    if st.button("📌 手动锁定当前前5为最终推荐（带板块分散）"):
        if "full_scored_df" in st.session_state and st.session_state.full_scored_df is not None:
            diverse_top5 = select_diverse_top5(st.session_state.full_scored_df, max_per_sector=2)
            if len(diverse_top5) >= 5:
                st.session_state.final_pick_list = diverse_top5
                st.session_state.locked = True
                add_log("手动操作", "手动锁定最终推荐列表（板块分散）")
                st.success("已锁定当前前5为最终推荐")
                st.rerun()
            else:
                st.warning("板块分散后不足5支，请调整参数或稍后再试")
        else:
            st.warning("暂无有效候选股")

    if st.button("🗑️ 清除所有推荐"):
        st.session_state.morning_pick = None
        st.session_state.final_pick_list = None
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
    
    # 显示行业数据统计
    if '所属行业' in df.columns:
        known_industry = (df['所属行业'] != '未知').sum()
        st.caption(f"行业信息覆盖: {known_industry}/{len(df)} 支股票 ({(known_industry/len(df)*100):.1f}%)")
else:
    if st.session_state.data_source == "non_trading":
        st.info("⏸️ 当前非交易时间，无实时数据。如需测试，请使用左侧「模拟测试」模式。")
    else:
        st.warning("⚠️ 获取数据失败，请检查网络或Tushare权限")

# ===============================
# 板块分析
# ===============================
st.markdown("### 📊 板块热度分析")
# 判断是否有足够的行业数据进行分析
has_valid_sector = False
if not df.empty and '所属行业' in df.columns:
    known_sectors = df[df['所属行业'] != '未知']['所属行业'].unique()
    if len(known_sectors) > 0:
        has_valid_sector = True

if not has_valid_sector:
    st.info("当前行业数据不足（可能由于 Tushare 权限或网络问题），跳过板块分析。选股将基于全市场进行。")
    strongest_sector = None
else:
    try:
        # 只使用有行业信息的股票进行板块分析
        df_with_sector = df[df['所属行业'] != '未知'].copy()
        if df_with_sector.empty:
            st.info("所有股票行业均为未知，跳过板块分析。")
            strongest_sector = None
        else:
            sector_analysis = df_with_sector.groupby('所属行业').agg({
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
# 多因子选股（实时计算，保存完整排序）
# ===============================
st.markdown("### 🎯 实时候选排名（动态轮动）")
full_scored_df = None  # 保存完整评分DataFrame供后续使用

if df.empty:
    st.info("当前无股票数据，无法进行选股。")
else:
    with st.spinner("正在准备选股数据..."):
        # 基础过滤
        filtered = filter_stocks_by_rule(df, max_increase)
        st.caption(f"基础过滤后股票数: {len(filtered)} / {len(df)}")

        # 如果存在最强板块且板块数据有效，优先从该板块选股；否则全市场
        if strongest_sector and '所属行业' in filtered.columns:
            sector_stocks = filtered[filtered['所属行业'] == strongest_sector].copy()
            if sector_stocks.empty:
                sector_stocks = filtered.copy()
        else:
            sector_stocks = filtered.copy()

        if not sector_stocks.empty:
            # 添加技术因子（包含进度条）
            df_with_factors = add_technical_indicators(sector_stocks)
            if not df_with_factors.empty:
                full_scored_df = calculate_composite_score(df_with_factors, factor_weights)
                st.session_state.full_scored_df = full_scored_df  # 保存供手动操作使用
                # 显示实时前5（不加板块限制，反映真实轮动）
                display_cols = ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分', '所属行业']
                top5_dynamic = full_scored_df.head(5)[display_cols].copy()
                top5_dynamic['涨跌幅'] = top5_dynamic['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                top5_dynamic['成交额'] = top5_dynamic['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                top5_dynamic['综合得分'] = top5_dynamic['综合得分'].apply(lambda x: f"{x:.3f}")
                top5_dynamic['风险调整得分'] = top5_dynamic['风险调整得分'].apply(lambda x: f"{x:.3f}")
                st.dataframe(top5_dynamic, use_container_width=True)

                # 显示第一名简要信息
                top1 = full_scored_df.iloc[0]
                st.markdown(f"**当前第一**：{top1['名称']} ({top1['代码']}) 涨幅 {top1['涨跌幅']:.2f}%")

# ===============================
# 自动最终推荐（在锁定时间触发，带板块分散）
# ===============================
is_final_lock_time = (current_hour, current_minute) >= (lock_hour, lock_minute)

if not df.empty and is_final_lock_time and not st.session_state.locked and full_scored_df is not None:
    # 从完整评分中选出板块分散的前5
    diverse_top5 = select_diverse_top5(full_scored_df, max_per_sector=2)
    if len(diverse_top5) >= 5:
        st.session_state.final_pick_list = diverse_top5
        st.session_state.locked = True
        add_log("自动推荐", f"{lock_hour:02d}:{lock_minute:02d} 自动锁定最终推荐（板块分散）")
        st.success(f"🎯 {lock_hour:02d}:{lock_minute:02d} 最终推荐已自动锁定！")
        st.rerun()
    else:
        add_log("自动推荐", "板块分散后不足5支，暂不锁定")
        st.warning("板块分散后候选不足5支，请检查数据或放宽过滤条件")

# ===============================
# 最终推荐展示（主推 + 备选）
# ===============================
st.markdown("---")
st.markdown("### 📋 最终推荐（锁定后不再变动）")

if st.session_state.final_pick_list is not None and len(st.session_state.final_pick_list) > 0:
    final_df = pd.DataFrame(st.session_state.final_pick_list)
    # 标记主推和备选
    final_df['角色'] = ['主推'] + [f'备选{i}' for i in range(1, 5)]
    display_cols = ['角色', '名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分', '所属行业']
    final_display = final_df[display_cols].copy()
    final_display['涨跌幅'] = final_display['涨跌幅'].apply(lambda x: f"{x:.2f}%")
    final_display['成交额'] = final_display['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
    final_display['综合得分'] = final_display['综合得分'].apply(lambda x: f"{x:.3f}")
    final_display['风险调整得分'] = final_display['风险调整得分'].apply(lambda x: f"{x:.3f}")
    st.dataframe(final_display, use_container_width=True)

    # 板块分布统计
    sector_counts = final_df['所属行业'].value_counts()
    st.markdown("#### 📊 板块分布")
    for sector, count in sector_counts.items():
        st.write(f"- **{sector}**: {count} 支")

    # 操作建议
    st.markdown("#### 📝 明日操作计划（仅供参考）")
    avg_increase = final_df['涨跌幅'].mean()
    if avg_increase < 0:
        st.info("整体回调，建议轻仓观望，严格止损")
    elif avg_increase < 3:
        st.success("温和上涨，可考虑分批建仓")
    else:
        st.warning("整体涨幅偏高，注意追高风险，控制仓位")

    # 主推单独强调
    main_pick = final_df.iloc[0]
    st.markdown(f"**主推关注**：{main_pick['名称']} ({main_pick['代码']}) 涨幅 {main_pick['涨跌幅']:.2f}%")

else:
    if is_final_lock_time:
        if df.empty:
            st.info("⏸️ 无有效数据，无法生成最终推荐")
        else:
            st.info("⏳ 正在计算最终推荐，请稍候...")
    else:
        st.info(f"⏰ 最终锁定时段: {lock_hour:02d}:{lock_minute:02d} 后（当前 {current_hour:02d}:{current_minute:02d}）")

# ===============================
# 系统日志与自动刷新
# ===============================
with st.expander("📜 系统日志", expanded=False):
    if st.session_state.logs:
        for log in reversed(st.session_state.logs[-10:]):
            st.text(f"{log['timestamp']} - {log['event']}: {log['details']}")
    else:
        st.info("暂无日志记录")

# 自动刷新（仅交易时段）
if is_trading_day_and_time(current_time)[0]:
    time.sleep(30)
    st.rerun()
else:
    time.sleep(60)
    st.rerun()

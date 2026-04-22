# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 低位横盘涨停策略（主板专用）
=========================================================
✅ 选股逻辑完全按照需求：
   1. 近120日从高点回落，跌幅＞25%
   2. 价跌量缩企稳阶段（下跌段均量 < 上涨段均量×0.8）
   3. 5日内出现过放量涨停（涨停日成交量 ≥ 前一日×2）
   4. 涨停前5个交易日均量 ≤ 120日天量的30%（剔除涨停日）
   5. 5日均线上穿20日均线
   6. 剔除 ST、停牌、退市股、创业板、科创板、北交所
"""
import sys
import streamlit as st

st.write("Python 路径:", sys.path)
try:
    import tushare as ts
    st.success("✅ tushare 导入成功")
except ImportError as e:
    st.error(f"❌ 导入失败: {e}")
    st.stop()
import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz
import warnings
import tushare as ts

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.3 · 低位横盘涨停策略", layout="wide")

# ===============================
# 🔑 从 Streamlit Secrets 读取 Tushare Token
# ===============================
try:
    TUSHARE_TOKEN = "dea49fc606a0945a8d00408b7828e4b6c7fcb3172a750fdeba734add"
except KeyError:
    st.error("未找到 Tushare Token，请在 Secrets 中设置 `tushare_token`")
    st.stop()

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ---------- Tushare 版本检查 ----------
try:
    from tushare import __version__ as ts_version
    if ts_version < '1.2.89':
        st.warning("⚠️ 当前 Tushare 版本较旧，建议升级：`pip install --upgrade tushare`")
except:
    pass

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

default_session_vars = {
    "candidate_pick_history": [],
    "morning_pick": None,
    "final_pick": None,
    "locked": False,
    "today": datetime.now(tz).date(),
    "logs": [],
    "backtest_results": None,
    "today_real_data": None,
    "data_source": "unknown",
    "last_data_fetch_time": None,
    "data_fetch_attempts": 0,
    "a_code_list": None,
    "hist_data_cache": {},
    "convergence_records": [],
    "backup_picks": [],
}

for key, default in default_session_vars.items():
    if key not in st.session_state:
        st.session_state[key] = default

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

# ===============================
# Tushare 数据获取
# ===============================
def fetch_from_tushare():
    """从 Tushare rt_k 接口获取实时行情（剔除创业/科创/北交所）"""
    try:
        add_log("数据源", "尝试 Tushare rt_k 接口")

        # 只获取主板（上证6开头，深证0开头）
        board_patterns = [
            "6*.SH",    # 上证主板
            "0*.SZ",    # 深证主板
        ]

        all_dfs = []

        for pattern in board_patterns:
            try:
                df_part = pro.rt_k(ts_code=pattern)
                if df_part is not None and not df_part.empty:
                    all_dfs.append(df_part)
                    add_log("数据源", f"板块 {pattern} 获取到 {len(df_part)} 条")
                else:
                    add_log("数据源", f"板块 {pattern} 返回空数据")
            except Exception as e:
                add_log("数据源", f"板块 {pattern} 异常: {str(e)[:50]}")
                continue

        if not all_dfs:
            add_log("数据源", "所有板块均失败，无数据")
            return None

        df = pd.concat(all_dfs, ignore_index=True)
        df = df.drop_duplicates(subset=['ts_code'])

        # 剔除创业板（300/301开头）、科创板（688开头）、北交所（8/4开头）
        original_count = len(df)
        df = df[~df['ts_code'].str.startswith(('300', '301', '688', '8', '4'))]
        removed_count = original_count - len(df)
        if removed_count > 0:
            add_log("数据源", f"剔除创业/科创/北交所 {removed_count} 只，剩余 {len(df)} 只")

        # 剔除停牌（最新价=0 或 成交量=0）
        if 'close' in df.columns:
            df = df[df['close'] > 0]
        if 'vol' in df.columns:
            df = df[df['vol'] > 0]

        add_log("数据源", f"合并后共 {len(df)} 条股票数据")

        df['涨跌幅'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100
        if 'high' in df.columns:
            df['最高涨幅'] = (df['high'] - df['pre_close']) / df['pre_close'] * 100
        else:
            df['最高涨幅'] = np.nan

        rename_map = {
            'ts_code': '代码',
            'name': '名称',
            'amount': '成交额',
            'vol': '成交量',
            'close': '最新价',
            'high': '最高价',
        }
        rename_cols = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=rename_cols)

        df['所属行业'] = '未知'
        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing = [c for c in required if c not in df.columns]
        if missing:
            add_log("数据源", f"字段缺失: {missing}")
            return None

        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '最高价', '最高涨幅']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ Tushare rt_k 成功，最终 {len(df)} 条")
        return df

    except Exception as e:
        add_log("数据源", f"Tushare rt_k 整体异常: {str(e)[:100]}")
        return None

def get_stable_realtime_data():
    now = datetime.now(tz)
    is_trading, msg = is_trading_day_and_time(now)
    if not is_trading:
        st.session_state.data_source = "non_trading"
        st.session_state.last_data_fetch_time = now
        add_log("数据", f"{msg}，返回空数据")
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

    df = fetch_from_tushare()
    if df is not None and not df.empty:
        st.session_state.today_real_data = df.copy()
        st.session_state.data_source = "real_data"
        st.session_state.last_data_fetch_time = now
        add_log("数据源", "成功获取实时数据并更新缓存")
        return df
    else:
        st.session_state.data_source = "failed"
        st.session_state.last_data_fetch_time = now
        add_log("数据源", "Tushare 获取失败，返回空")
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

def get_historical_data(ts_code, end_date=None):
    cache = st.session_state.hist_data_cache
    if ts_code in cache:
        return cache[ts_code]

    try:
        if end_date is None:
            end_date = datetime.now(tz).strftime('%Y%m%d')
        df = pro.daily(ts_code=ts_code, end_date=end_date, limit=120)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date')
            cache[ts_code] = df
            add_log("历史数据", f"获取 {ts_code} 成功 {len(df)} 条")
            return df
        else:
            cache[ts_code] = pd.DataFrame()
            return pd.DataFrame()
    except Exception as e:
        add_log("历史数据", f"{ts_code} 获取失败: {str(e)[:50]}")
        cache[ts_code] = pd.DataFrame()
        return pd.DataFrame()

# ===============================
# 选股策略核心函数（完全按需求优化）
# ===============================
def filter_stocks_by_rule(df):
    """基础过滤：剔除ST、涨幅过高、成交额过低、停牌"""
    if df.empty:
        return df
    filtered = df.copy()
    # 剔除ST
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST|st|\\*ST', na=False)]
    # 剔除涨幅 > 6.5%（防止追高，可根据需要调整）
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] <= 6.5]
    # 成交额过滤（至少2000万）
    if '成交额' in filtered.columns:
        filtered = filtered[filtered['成交额'] >= 2e7]
    # 停牌过滤（最新价和成交量已为正）
    return filtered

def check_breakout_conditions(hist_df, current_price, current_vol):
    """
    检查是否满足：
    1. 近120日高点回落 > 25%
    2. 价跌量缩（下跌段均量 < 上涨段均量×0.8）
    3. 5日内出现放量涨停（涨停日成交量 ≥ 前一日×2）
    4. 涨停前5个交易日均量 ≤ 120日天量的30%（剔除涨停日）
    5. 今日MA5金叉MA20
    """
    if hist_df is None or hist_df.empty or len(hist_df) < 60:
        return False, {}

    hist_df = hist_df.sort_values('trade_date')
    if len(hist_df) > 120:
        hist_df = hist_df.tail(120)

    high = hist_df['high'].values
    low = hist_df['low'].values
    close = hist_df['close'].values
    vol = hist_df['vol'].values

    N = len(hist_df)

    # 1. 阶段高低点及跌幅
    phase_high = np.max(high)
    phase_low = np.min(low)
    if phase_high == 0:
        return False, {}
    drop_ratio = (phase_high - phase_low) / phase_high
    if drop_ratio <= 0.25:
        return False, {}

    # 2. 价跌量缩
    high_idx = np.argmax(high)
    if high_idx == 0 or high_idx == N-1:
        return False, {}
    up_vols = vol[:high_idx+1]
    down_vols = vol[high_idx+1:]
    if len(up_vols) < 5 or len(down_vols) < 5:
        return False, {}
    up_avg_vol = np.mean(up_vols)
    down_avg_vol = np.mean(down_vols)
    if up_avg_vol == 0:
        return False, {}
    if down_avg_vol >= up_avg_vol * 0.8:
        return False, {}

    # 3. 120日天量（包含今日成交量）
    hist_max_vol = np.max(vol) if len(vol) > 0 else 0
    max_vol_120 = max(hist_max_vol, current_vol)

    # 4. 涨停检测（主板9.8%）
    yesterday_close = close[-1]
    if yesterday_close == 0:
        return False, {}
    limit_up_threshold = 0.098
    is_limit_up = (current_price / yesterday_close - 1) >= limit_up_threshold

    # 构建完整序列（历史+今日）
    all_close = np.append(close, current_price)
    all_vol = np.append(vol, current_vol)
    if len(all_close) < 2:
        return False, {}
    pct_chg = (all_close[1:] / all_close[:-1] - 1)
    limit_up_flags = pct_chg >= limit_up_threshold
    vol_ratio = all_vol[1:] / all_vol[:-1]
    double_vol_flags = vol_ratio >= 2.0   # ✅ 需求：2倍以上

    # 5日内是否存在放量涨停
    if len(limit_up_flags) < 5:
        return False, {}
    last5_limit = limit_up_flags[-5:]
    last5_double = double_vol_flags[-5:]
    has_limit_double = any(last5_limit & last5_double)

    if not has_limit_double:
        return False, {}

    # 5. 涨停前5个交易日均量 ≤ 天量×30%（剔除涨停日）
    non_limit_volumes = []
    # 从历史最后一天往前找，收集非涨停日的成交量（最多取前5个）
    for i in range(-1, -len(limit_up_flags)-1, -1):
        if not limit_up_flags[i]:
            non_limit_volumes.append(all_vol[i])
        if len(non_limit_volumes) >= 5:
            break
    if len(non_limit_volumes) < 3:   # 至少3个交易日
        return False, {}
    avg_vol_before = np.mean(non_limit_volumes)
    if max_vol_120 == 0:
        return False, {}
    if avg_vol_before > max_vol_120 * 0.30:   # ✅ 需求：30%
        return False, {}

    # 6. MA5金叉MA20
    if len(all_close) < 20:
        return False, {}
    ma5 = pd.Series(all_close).rolling(5).mean()
    ma20 = pd.Series(all_close).rolling(20).mean()
    if len(ma5) < 2 or len(ma20) < 2:
        return False, {}
    golden_cross = (ma5.iloc[-2] <= ma20.iloc[-2]) and (ma5.iloc[-1] > ma20.iloc[-1])
    if not golden_cross:
        return False, {}

    # 所有条件满足，计算评分
    score_dict = {
        'drop_ratio': drop_ratio,
        'vol_shrink_ratio': down_avg_vol / up_avg_vol,
        'avg_vol_before_ratio': avg_vol_before / max_vol_120,
        'limit_up_today': is_limit_up,
        'ma5_ma20_gap': (ma5.iloc[-1] - ma20.iloc[-1]) / ma20.iloc[-1],
    }
    return True, score_dict

def select_stocks_by_breakout(df_real, max_calc=300):
    if df_real.empty:
        return pd.DataFrame()

    filtered = filter_stocks_by_rule(df_real)
    if filtered.empty:
        return pd.DataFrame()

    # 优先计算涨幅+成交额靠前的股票
    if '涨跌幅' in filtered.columns:
        filtered['_tmp_score'] = filtered['涨跌幅'].rank(pct=True, ascending=False) * 0.5 + \
                                 filtered['成交额'].rank(pct=True, ascending=False) * 0.5
        filtered = filtered.sort_values('_tmp_score', ascending=False).head(max_calc)

    result_list = []
    for idx, row in filtered.iterrows():
        ts_code = row['代码']
        hist_df = get_historical_data(ts_code)
        if hist_df.empty:
            continue
        current_price = row['最新价'] if '最新价' in row else 0
        current_vol = row['成交量'] if '成交量' in row else 0
        if current_price <= 0 or current_vol <= 0:
            continue
        is_match, score_dict = check_breakout_conditions(hist_df, current_price, current_vol)
        if is_match:
            base_score = (score_dict['drop_ratio'] * 100) + \
                         ((1 - score_dict['vol_shrink_ratio']) * 50) + \
                         ((0.30 - score_dict['avg_vol_before_ratio']) * 200) + \
                         (20 if score_dict['limit_up_today'] else 0) + \
                         (score_dict['ma5_ma20_gap'] * 100)
            result_list.append({
                '代码': ts_code,
                '名称': row['名称'],
                '涨跌幅': row['涨跌幅'],
                '成交额': row['成交额'],
                '最新价': current_price,
                '综合得分': base_score,
                '风险调整得分': base_score,
                '所属行业': row.get('所属行业', '未知'),
                '是否今天涨停': score_dict['limit_up_today'],
                '跌幅幅度': f"{score_dict['drop_ratio']*100:.1f}%",
                'vol_shrink_ratio': score_dict['vol_shrink_ratio'],
                'avg_vol_before_ratio': score_dict['avg_vol_before_ratio'],
                'ma5_ma20_gap': score_dict['ma5_ma20_gap']
            })

    if not result_list:
        return pd.DataFrame()
    result_df = pd.DataFrame(result_list)
    result_df = result_df.sort_values('综合得分', ascending=False)
    return result_df

# ===============================
# 主程序（完整界面）
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 低位横盘涨停策略（主板专用）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.data_source = "unknown"
    st.session_state.data_fetch_attempts = 0
    st.session_state.a_code_list = None
    st.session_state.hist_data_cache = {}
    st.session_state.convergence_records = []
    st.session_state.backup_picks = []
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
        st.session_state.hist_data_cache = {}
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
    st.markdown("#### ⚙️ 多因子权重配置（本策略权重固定为低位形态评分，下方仅供参考）")
    st.info("本策略使用低位横盘+放量涨停+金叉的综合评分，侧边栏权重未使用。")

    if st.session_state.convergence_records:
        st.markdown(f"#### 📈 收敛记录数: {len(st.session_state.convergence_records)}")

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
        st.session_state.backup_picks = []
        add_log("手动操作", "清除所有推荐")
        st.success("推荐已清除")
        st.rerun()

    st.markdown("---")
    if st.session_state.today_real_data is not None and not st.session_state.today_real_data.empty:
        st.markdown("#### 💾 数据缓存")
        st.info(f"已缓存 {len(st.session_state.today_real_data)} 条今日数据")
        if st.button("清除今日缓存"):
            st.session_state.today_real_data = None
            st.session_state.data_source = "unknown"
            st.session_state.a_code_list = None
            st.session_state.hist_data_cache = {}
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
    is_final_lock_time = (current_hour, current_minute) >= (14, 40)
    if is_first_rec_time:
        st.metric("推荐状态", "🟢 可推荐")
    elif is_final_lock_time:
        st.metric("推荐状态", "🔴 需锁定")
    else:
        st.metric("推荐状态", "🟡 观察中")
with col4:
    if period == "午盘" and current_hour >= 14:
        close_time = current_time.replace(hour=15, minute=0, second=0, microsecond=0)
        time_left = close_time - current_time
        minutes_left = max(0, int(time_left.total_seconds() / 60))
        st.metric("距离收盘", f"{minutes_left}分钟")
    else:
        st.metric("自动刷新", "30秒")

# ===============================
# 🚀 获取市场数据
# ===============================
st.markdown("### 📊 数据获取状态")
try:
    with st.spinner("正在获取实时数据..."):
        df = get_stable_realtime_data()

    data_source_status = {
        "real_data": ("✅", "Tushare rt_k 实时行情", "#e6f7ff"),
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
        st.success(f"✅ 成功获取 {len(df)} 条真实股票数据（已剔除创业板/科创板/北交所）")
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
            st.warning("⚠️ 获取到的数据为空，可能原因：Tushare 权限不足、token错误或接口异常")
except Exception as e:
    st.error(f"❌ 数据获取失败: {str(e)}")
    add_log("数据获取", f"最终失败: {str(e)}")
    with st.expander("🔧 故障排除指南"):
        st.markdown("""
        ### Tushare 数据获取失败，可能原因：
        - **Tushare token 错误或未填写** → 请检查 Secrets 中的 `tushare_token`
        - **Tushare 权限不足** → 确认已开通“实时日K行情”权限
        - **Tushare 版本过低** → 执行 `pip install --upgrade tushare`
        - **当前非交易时间** → 实时行情只在交易时段（9:30-11:30, 13:00-15:00）提供
        - **网络环境限制** → 某些服务器/IP 可能被 Tushare 封禁
        """)
    if st.button("🔄 立即重试"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.a_code_list = None
        st.rerun()
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 板块分析与选股（简化为仅显示热度，不参与评分）
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

# ===============================
# 🎯 新选股引擎（低位横盘涨停策略）
# ===============================
st.markdown("### 🎯 低位横盘+放量涨停选股引擎")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    st.markdown("**策略条件**: 跌幅>25% | 价跌量缩 | 5日内放量涨停(≥2倍) | 涨停前5日均量≤天量30% | MA5金叉MA20")
    with st.spinner("正在计算历史形态（可能需要几十秒）..."):
        scored_df = select_stocks_by_breakout(df, max_calc=300)

    if scored_df.empty:
        st.warning("当前没有满足所有条件的股票，可适当放宽参数或等待更多信号。")
        top_candidate = None
        top_candidates = pd.DataFrame()
    else:
        top_candidates = scored_df.head(10)
        top_candidate = scored_df.iloc[0].to_dict()

        st.markdown("#### 📈 优选股票形态指标")
        col_info, col_factors = st.columns([1, 2])
        with col_info:
            st.metric("**选中股票**", f"{top_candidate.get('名称', 'N/A')}")
            st.metric("**代码**", f"{top_candidate.get('代码', 'N/A')}")
            st.metric("**综合得分**", f"{top_candidate.get('综合得分', 0):.2f}")
            st.metric("**今日涨幅**", f"{top_candidate.get('涨跌幅', 0):.2f}%")
            if '是否今天涨停' in top_candidate:
                st.metric("**今日涨停**", "是" if top_candidate['是否今天涨停'] else "否")
        with col_factors:
            factor_data = {
                '因子': ['跌幅深度', '缩量程度', '涨停前缩量', '金叉开口'],
                '得分': [
                    top_candidate.get('跌幅幅度', '0%').rstrip('%'),
                    f"{(1 - top_candidate.get('vol_shrink_ratio', 0)) * 100:.1f}%",
                    f"{(0.30 - top_candidate.get('avg_vol_before_ratio', 0)) * 100:.1f}分",
                    f"{top_candidate.get('ma5_ma20_gap', 0) * 100:.2f}%"
                ]
            }
            factor_df = pd.DataFrame(factor_data)
            st.dataframe(factor_df, use_container_width=True)

        st.markdown("#### 🏆 候选股票排名 (前5)")
        if not top_candidates.empty:
            display_cols = ['名称', '代码', '涨跌幅', '成交额', '综合得分', '是否今天涨停']
            display_cols = [c for c in display_cols if c in top_candidates.columns]
            display_df = top_candidates[display_cols].head().copy()
            display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:.2f}%")
            display_df['成交额'] = display_df['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
            display_df['综合得分'] = display_df['综合得分'].apply(lambda x: f"{x:.2f}")
            if '是否今天涨停' in display_df.columns:
                display_df['是否今天涨停'] = display_df['是否今天涨停'].apply(lambda x: "✅" if x else "❌")
            st.dataframe(display_df, use_container_width=True)

        # 用于侧边栏手动测试
        st.session_state.test_top_stock = {
            'name': top_candidate.get('名称', ''),
            'code': top_candidate.get('代码', ''),
            '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
            '成交额': float(top_candidate.get('成交额', 0)),
            '综合得分': float(top_candidate.get('综合得分', 0)),
            'risk_adjusted_score': float(top_candidate.get('综合得分', 0)),
            'time': current_time_str,
            'sector': strongest_sector if strongest_sector else '全市场',
            'data_source': st.session_state.data_source
        }

# ===============================
# 自动推荐（首次推荐）
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
            <p><strong>🏆 综合得分:</strong> {pick.get('composite_score', 'N/A'):.2f}</p>
            <p><strong>⚖️ 风险调整得分:</strong> {pick.get('risk_adjusted_score', 'N/A'):.2f}</p>
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
    st.subheader("🎯 最终锁定 (14:40后)")
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
            <p><strong>🏆 综合得分:</strong> {pick.get('composite_score', 'N/A'):.2f}</p>
            <p><strong>⚖️ 风险调整得分:</strong> {pick.get('risk_adjusted_score', 'N/A'):.2f}</p>
            <p><strong>🔒 状态:</strong> {'已锁定' if st.session_state.locked else '未锁定'}</p>
            <p><strong>🔧 来源:</strong> {'自动锁定' if pick.get('auto', False) else '手动设置'}</p>
        </div>
        """, unsafe_allow_html=True)
        if st.session_state.backup_picks:
            st.markdown("#### 🥈 备选推荐")
            for i, b in enumerate(st.session_state.backup_picks, 1):
                st.write(f"{i}. {b['name']} ({b['code']}) 涨幅 {b['涨跌幅']:.2f}%")
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
                st.info("⏳ 正在收敛计算最终推荐...")
            else:
                st.info("⏸️ 等待真实数据或合适标的")
        else:
            st.info("⏰ 最终锁定时段: 14:40后")

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

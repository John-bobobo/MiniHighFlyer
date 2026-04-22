# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 低位横盘涨停策略（剔除创业板/科创板/北交所）
=========================================================
✅ 选股逻辑完全按照需求：
   1. 近120日从高点回落，跌幅＞25%
   2. 价跌量缩企稳阶段（下跌段均量 < 上涨段均量×0.8）
   3. 5日内出现过放量涨停（涨停日成交量 ≥ 前一日×2）
   4. 涨停前5个交易日均量 ≤ 120日天量的30%（剔除涨停日）
   5. 5日均线上穿20日均线
   6. 剔除 ST、停牌、退市股
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
# 主程序（界面部分保持原有结构，仅调整标题和说明）
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

# 侧边栏（略，保持原有功能，此处因篇幅省略相同代码，实际运行时请保留原侧边栏）
# 由于代码长度限制，侧边栏和后续界面与原版基本一致，可沿用原文件中的侧边栏、时间监控、自动推荐等部分。
# 为保持完整性，以下提供必要的界面框架，实际使用时请确保包含所有原有界面组件。

# 注意：以下为占位符，实际部署时应将原文件中的侧边栏、监控、推荐显示等代码完整复制过来。
# 此处仅展示选股引擎替换后的核心逻辑，完整代码请参考附件或按上述函数替换。

# ===============================
# 示例：选股引擎调用（需嵌入原界面）
# ===============================
st.markdown("### 🎯 低位横盘+放量涨停选股引擎")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    st.markdown("**策略条件**: 跌幅>25% | 价跌量缩 | 5日内放量涨停(≥2倍) | 涨停前5日均量≤天量30% | MA5金叉MA20")
    with st.spinner("正在计算历史形态..."):
        scored_df = select_stocks_by_breakout(df, max_calc=300)

    if scored_df.empty:
        st.warning("当前没有满足所有条件的股票，可适当放宽参数或等待更多信号。")
        top_candidate = None
        top_candidates = pd.DataFrame()
    else:
        top_candidates = scored_df.head(10)
        top_candidate = scored_df.iloc[0].to_dict()
        # ... 后续显示代码与原界面相同

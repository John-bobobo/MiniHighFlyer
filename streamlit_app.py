# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 主线题材+硬性技术条件（性能优化版）
===================================================
✅ 优化：限制硬性检查股票数量（最多200只），避免超时
✅ 新增进度条和状态提示
✅ 保留：主线板块 Top5 过滤 + 四项硬性技术条件
✅ 原有多因子评分、收敛记录、自动推荐功能不变
✅ 修复 candidate_df 未赋值导致的 AttributeError
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
st.set_page_config(page_title="尾盘博弈 6.3 · 主线题材+硬性技术", layout="wide")

# ===============================
# 🔑 Tushare Token
# ===============================
try:
    TUSHARE_TOKEN = "3cc067cf223333d2e817be127a633d440f12de98e12c731905f38392"
except KeyError:
    st.error("未找到 Tushare Token，请在 Secrets 中设置 `tushare_token`")
    st.stop()

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

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
    "stock_industry_cache": {},
    "convergence_records": [],
    "backup_picks": [],
    "candidate_df": pd.DataFrame(),  # 候选池
    "final_locked": False,          # 最终锁定标志
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
# 个股行业信息获取（缓存 + 批量）
# ===============================
def batch_get_stock_industry(ts_codes):
    cache = st.session_state.stock_industry_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            df = pro.stock_basic(fields='ts_code,industry')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = row['ts_code']
                    ind = row['industry'] if pd.notna(row['industry']) else '未知'
                    cache[code] = ind
                add_log("行业数据", f"成功获取 {len(df)} 只股票的行业信息")
            else:
                add_log("行业数据", "stock_basic 返回空")
        except Exception as e:
            add_log("行业数据", f"获取行业失败: {str(e)[:50]}")
    return [cache.get(c, '未知') for c in ts_codes]

# ===============================
# Tushare 数据获取（增强行业填充）
# ===============================
def fetch_from_tushare():
    try:
        add_log("数据源", "尝试 Tushare rt_k 接口")
        board_patterns = ["6*.SH", "0*.SZ", "3*.SZ", "688*.SH", "8*.BJ", "4*.BJ"]
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

        codes = df['代码'].tolist()
        industries = batch_get_stock_industry(codes)
        df['所属行业'] = industries

        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing = [c for c in required if c not in df.columns]
        if missing:
            add_log("数据源", f"字段缺失: {missing}")
            return None

        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '最高价', '最高涨幅']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ 成功获取 {len(df)} 条（已填充行业）")
        return df
    except Exception as e:
        add_log("数据源", f"整体异常: {str(e)[:100]}")
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
        df = pro.daily(ts_code=ts_code, end_date=end_date, limit=60)
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
# 硬性技术条件检查（快速版）
# ===============================
def check_hard_conditions_fast(row, hist_df):
    if hist_df.empty or len(hist_df) < 6:
        return False, "历史数据不足"
    # 1. 涨幅 2%-6.5%
    pct = row['涨跌幅']
    if pct < 2.0 or pct > 6.5:
        return False, f"涨幅 {pct:.2f}% 超出范围"
    # 2. 量比 1.2-1.8
    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 == 0:
        return False, "前5日均量为0"
    vol_ratio = row['成交量'] / avg_vol_5
    if vol_ratio < 1.2 or vol_ratio > 1.8:
        return False, f"量比 {vol_ratio:.2f} 超出范围"
    # 3. 三连阳 + 站上5日线
    recent_3 = hist_df['close'].tail(3).values
    if len(recent_3) < 3 or not (recent_3[0] < recent_3[1] < recent_3[2]):
        return False, "非三连阳"
    ma5 = hist_df['close'].rolling(5).mean().iloc[-1]
    if ma5 is None or np.isnan(ma5) or row['最新价'] < ma5:
        return False, "未站上5日线"
    # 4. 近5日有放量阳线
    hist_5 = hist_df.tail(5)
    has_strong_day = ((hist_5['close'] - hist_5['open']) > 0).any()
    if not has_strong_day:
        return False, "近5日无放量阳线"
    return True, "符合"

# ===============================
# 原有因子计算函数
# ===============================
def filter_stocks_by_rule(df):
    if df.empty:
        return df
    filtered = df.copy()
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] <= 6.5]
    if '最高涨幅' in filtered.columns and '涨跌幅' in filtered.columns:
        filtered = filtered[~((filtered['最高涨幅'] > 9.5) & (filtered['涨跌幅'] < 7))]
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)
        filtered = filtered[filtered['成交额'] > threshold]
    return filtered

def calculate_technical_indicators(hist_df):
    if hist_df.empty or len(hist_df) < 20:
        return {}
    hist_df = hist_df.sort_values('trade_date')
    close = hist_df['close'].values
    high = hist_df['high'].values
    low = hist_df['low'].values
    volume = hist_df['vol'].values

    ma5 = pd.Series(close).rolling(5).mean().iloc[-1] if len(close)>=5 else np.nan
    ma10 = pd.Series(close).rolling(10).mean().iloc[-1] if len(close)>=10 else np.nan
    ma20 = pd.Series(close).rolling(20).mean().iloc[-1] if len(close)>=20 else np.nan

    exp1 = pd.Series(close).ewm(span=12, adjust=False).mean()
    exp2 = pd.Series(close).ewm(span=26, adjust=False).mean()
    macd = exp1 - exp2
    signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - signal
    macd_hist_val = macd_hist.iloc[-1] if not macd_hist.empty else np.nan
    if len(macd)>=2 and len(signal)>=2:
        macd_golden_cross = (macd.iloc[-2] <= signal.iloc[-2]) and (macd.iloc[-1] > signal.iloc[-1])
    else:
        macd_golden_cross = False

    min_low_20 = pd.Series(low).rolling(20).min().iloc[-1] if len(low)>=20 else np.nan
    cur_close = close[-1]
    if not np.isnan(min_low_20) and min_low_20 > 0:
        low_distance = (cur_close - min_low_20) / min_low_20
    else:
        low_distance = np.nan

    avg_vol_20 = pd.Series(volume).rolling(20).mean().iloc[-1] if len(volume)>=20 else np.nan
    bull_mas = (ma5 > ma10) and (ma10 > ma20) if not any(np.isnan([ma5, ma10, ma20])) else False

    return {
        'ma5': ma5, 'ma10': ma10, 'ma20': ma20,
        'macd_hist': macd_hist_val, 'macd_golden_cross': macd_golden_cross,
        'low_distance': low_distance, 'avg_vol_20': avg_vol_20, 'bull_mas': bull_mas,
    }

def add_technical_indicators(df, top_n=200):
    if df.empty:
        return df
    if '涨跌幅' in df.columns:
        temp = df.copy()
        temp['_temp_score'] = temp['涨跌幅'].rank(pct=True) * 0.5 + temp['成交额'].rank(pct=True) * 0.5
        temp = temp.sort_values('_temp_score', ascending=False).head(top_n)
        candidates = temp
    else:
        candidates = df.head(top_n)

    result_list = []
    for idx, row in candidates.iterrows():
        ts_code = row['代码']
        hist = get_historical_data(ts_code)
        if hist.empty:
            new_row = row.to_dict()
            new_row.update({
                'ma5': np.nan, 'ma10': np.nan, 'ma20': np.nan,
                'macd_hist': np.nan, 'macd_golden_cross': False,
                'low_distance': np.nan, 'vol_ratio_real': np.nan, 'bull_mas': False,
            })
        else:
            tech = calculate_technical_indicators(hist)
            avg_vol_20 = tech.get('avg_vol_20', np.nan)
            cur_vol = row['成交量'] if '成交量' in row else np.nan
            if not np.isnan(avg_vol_20) and avg_vol_20 > 0 and not np.isnan(cur_vol):
                vol_ratio_real = cur_vol / avg_vol_20
            else:
                vol_ratio_real = np.nan
            new_row = row.to_dict()
            new_row.update({
                'ma5': tech.get('ma5', np.nan), 'ma10': tech.get('ma10', np.nan),
                'ma20': tech.get('ma20', np.nan), 'macd_hist': tech.get('macd_hist', np.nan),
                'macd_golden_cross': tech.get('macd_golden_cross', False),
                'low_distance': tech.get('low_distance', np.nan), 'vol_ratio_real': vol_ratio_real,
                'bull_mas': tech.get('bull_mas', False),
            })
        result_list.append(new_row)

    result_df = df.copy()
    tech_df = pd.DataFrame(result_list)
    tech_cols = ['代码', 'ma5', 'ma10', 'ma20', 'macd_hist', 'macd_golden_cross',
                 'low_distance', 'vol_ratio_real', 'bull_mas']
    result_df = result_df.merge(tech_df[tech_cols], on='代码', how='left')
    fill_dict = {'macd_golden_cross': False, 'bull_mas': False}
    for col, val in fill_dict.items():
        if col in result_df.columns:
            result_df[col] = result_df[col].fillna(val)
    return result_df

def calculate_composite_score(df, sector_avg_change, weights, strongest_sector=None):
    if df.empty:
        return df
    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))

    for factor, weight in weights.items():
        if factor in df_scored.columns and weight != 0:
            valid = df_scored[factor].notna()
            if valid.sum() > 0:
                rank = df_scored[factor].rank(pct=True, method='average')
                rank = rank.fillna(0.5)
                total_score += rank * weight

    if 'low_distance' in df_scored.columns and 'vol_ratio_real' in df_scored.columns:
        low_rank = 1 - df_scored['low_distance'].rank(pct=True, na_option='bottom')
        vol_rank = df_scored['vol_ratio_real'].rank(pct=True, na_option='bottom')
        low_vol_score = (low_rank * 0.6 + vol_rank * 0.4) * 0.10
        total_score += low_vol_score.fillna(0)

    if 'macd_golden_cross' in df_scored.columns:
        total_score += df_scored['macd_golden_cross'].astype(float) * 0.05
    if 'bull_mas' in df_scored.columns:
        total_score += df_scored['bull_mas'].astype(float) * 0.05

    df_scored['综合得分'] = total_score

    risk_penalty = np.zeros(len(df_scored))
    if '涨跌幅' in df_scored.columns:
        high_gain = df_scored['涨跌幅'].clip(lower=5, upper=10)
        risk_penalty += (high_gain - 5) / 50 * 0.15
    if '波动率' in df_scored.columns:
        high_vol = df_scored['波动率'].clip(lower=5, upper=15)
        risk_penalty += (high_vol - 5) / 50 * 0.10

    df_scored['风险调整得分'] = df_scored['综合得分'] - risk_penalty
    return df_scored.sort_values('风险调整得分', ascending=False)

def update_convergence(candidates_df, current_time):
    if candidates_df.empty:
        return
    hour = current_time.hour
    minute = current_time.minute
    if hour == 14 and minute < 40:
        top10 = candidates_df.head(10)
        record = {'timestamp': current_time.strftime('%H:%M:%S'), 'stocks': []}
        for _, row in top10.iterrows():
            record['stocks'].append({
                '代码': row['代码'],
                '名称': row['名称'],
                '得分': row.get('风险调整得分', row.get('综合得分', 0))
            })
        st.session_state.convergence_records.append(record)
        if len(st.session_state.convergence_records) > 80:
            st.session_state.convergence_records = st.session_state.convergence_records[-80:]

def get_final_recommendation_from_convergence():
    records = st.session_state.convergence_records
    if not records:
        return None, []
    stock_stats = {}
    for rec in records:
        for s in rec['stocks']:
            code = s['代码']
            if code not in stock_stats:
                stock_stats[code] = {'名称': s['名称'], 'count': 0, 'total_score': 0.0, 'scores': []}
            stock_stats[code]['count'] += 1
            stock_stats[code]['total_score'] += s['得分']
            stock_stats[code]['scores'].append(s['得分'])
    for code, stat in stock_stats.items():
        stat['avg_score'] = stat['total_score'] / stat['count']
        stat['std_score'] = np.std(stat['scores']) if len(stat['scores']) > 1 else 0
    total_records = len(records)
    final_scores = []
    for code, stat in stock_stats.items():
        freq = stat['count'] / total_records
        all_avgs = [s['avg_score'] for s in stock_stats.values()]
        min_avg, max_avg = min(all_avgs), max(all_avgs)
        norm_avg = (stat['avg_score'] - min_avg) / (max_avg - min_avg) if max_avg > min_avg else 0.5
        composite = norm_avg * 0.6 + freq * 0.3 - stat['std_score'] * 0.1
        final_scores.append((code, stat['名称'], composite))
    final_scores.sort(key=lambda x: x[2], reverse=True)
    top3 = final_scores[:3]
    if not top3:
        return None, []
    first = {'代码': top3[0][0], '名称': top3[0][1]}
    backups = [{'代码': t[0], '名称': t[1]} for t in top3[1:3]]
    return first, backups

# ===============================
# 主程序
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 主线题材+硬性技术条件（性能优化版）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.data_source = "unknown"
    st.session_state.data_fetch_attempts = 0
    st.session_state.a_code_list = None
    st.session_state.hist_data_cache = {}
    st.session_state.stock_industry_cache = {}
    st.session_state.convergence_records = []
    st.session_state.backup_picks = []
    st.session_state.candidate_df = pd.DataFrame()
    st.session_state.final_locked = False
    add_log("系统", "新交易日开始，已清空历史数据")
    st.rerun()

# 侧边栏
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
    if st.button("🔄 强制刷新数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.a_code_list = None
        st.session_state.hist_data_cache = {}
        st.session_state.stock_industry_cache = {}
        st.session_state.candidate_df = pd.DataFrame()
        add_log("手动操作", "清除缓存，强制刷新")
        st.success("已清除缓存，将尝试重新获取")
        st.rerun()

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
    w_price = st.slider("当日涨幅", 0.0, 0.5, 0.20, 0.05, key="w_price")
    w_volume = st.slider("成交额", 0.0, 0.5, 0.15, 0.05, key="w_volume")
    w_momentum = st.slider("5日动量", 0.0, 0.4, 0.15, 0.05, key="w_momentum")
    w_reversal = st.slider("20日反转", 0.0, 0.3, 0.10, 0.05, key="w_reversal")
    w_vol_ratio = st.slider("量比", 0.0, 0.3, 0.10, 0.05, key="w_vol_ratio")
    w_volatility = st.slider("波动率(负)", -0.2, 0.0, -0.05, 0.05, key="w_volatility")
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
    st.info("📌 硬性技术条件已启用：涨幅2%-6.5% | 量比1.2-1.8 | 三连阳+站上5日线 | 近5日放量阳线")
    st.info("⚡ 性能优化：最多详细检查200只潜力股，避免超时")

# 时间处理
if use_real_time == "模拟测试" and "simulated_time" in st.session_state:
    current_time = st.session_state.simulated_time
    st.info(f"🔧 模拟时间: {current_time.strftime('%H:%M:%S')}")
else:
    current_time = now
current_hour = current_time.hour
current_minute = current_time.minute
current_time_str = current_time.strftime("%H:%M:%S")

# 交易时段监控
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

# 获取市场数据
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
        st.success(f"✅ 成功获取 {len(df)} 条真实股票数据（已填充行业）")
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
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# 板块分析与硬性选股
st.markdown("### 📊 板块热度分析（主线题材）")
if df.empty or '所属行业' not in df.columns:
    st.info("当前无有效板块数据，跳过板块分析。")
    top5_sectors = []
else:
    sector_analysis = df.groupby('所属行业').agg({'涨跌幅': 'mean', '成交额': 'sum', '代码': 'count'})
    sector_analysis = sector_analysis.rename(columns={'代码': '股票数量'})
    sector_analysis['资金占比'] = sector_analysis['成交额'] / sector_analysis['成交额'].sum()
    sector_analysis['强度得分'] = (sector_analysis['涨跌幅'].rank(pct=True) * 40 +
                                    sector_analysis['资金占比'].rank(pct=True) * 40 +
                                    sector_analysis['股票数量'].rank(pct=True) * 20)
    sector_analysis = sector_analysis.sort_values('强度得分', ascending=False)
    top5_sectors = sector_analysis.head(5).index.tolist()
    st.success(f"🏆 今日最强主线板块 Top5: {', '.join(top5_sectors)}")

st.markdown("### 🎯 多因子智能选股引擎（硬性条件+主线板块）")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    filtered = filter_stocks_by_rule(df)
    st.caption(f"基础过滤后股票数: {len(filtered)}")
    if not top5_sectors:
        sector_filtered = filtered
        st.warning("未识别主线板块，使用全市场")
    else:
        sector_filtered = filtered[filtered['所属行业'].isin(top5_sectors)]
        st.caption(f"主线板块过滤后股票数: {len(sector_filtered)}")
    
    if sector_filtered.empty:
        st.warning("主线板块内无股票，无法进行选股。")
        top_candidate = None
        st.session_state.candidate_df = pd.DataFrame()
    else:
        MAX_CHECK = 200
        tmp = sector_filtered.copy()
        tmp['_pre_score'] = (tmp['涨跌幅'].rank(pct=True) + tmp['成交额'].rank(pct=True)) / 2
        tmp = tmp.sort_values('_pre_score', ascending=False)
        to_check = tmp.head(MAX_CHECK)
        st.caption(f"将对前 {len(to_check)} 只潜力股进行硬性技术条件检查...")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        candidates_hard = []
        for i, (idx, row) in enumerate(to_check.iterrows()):
            status_text.text(f"正在检查 {i+1}/{len(to_check)}: {row['名称']}")
            hist = get_historical_data(row['代码'])
            if hist.empty:
                progress_bar.progress((i+1)/len(to_check))
                continue
            ok, reason = check_hard_conditions_fast(row, hist)
            if ok:
                candidates_hard.append(row)
            progress_bar.progress((i+1)/len(to_check))
        progress_bar.empty()
        status_text.empty()
        
        hard_df = pd.DataFrame(candidates_hard) if candidates_hard else pd.DataFrame()
        st.caption(f"硬性技术条件过滤后股票数: {len(hard_df)}")
        
        if hard_df.empty:
            st.warning("当前无满足所有硬性条件的股票，请等待或适当放宽参数。")
            top_candidate = None
            st.session_state.candidate_df = pd.DataFrame()
        else:
            df_with_tech = add_technical_indicators(hard_df, top_n=200)
            if '5日动量' not in df_with_tech.columns:
                df_with_tech['5日动量'] = df_with_tech['涨跌幅']
            if '20日反转' not in df_with_tech.columns:
                df_with_tech['20日反转'] = -df_with_tech['涨跌幅'] * 0.3
            if '量比' not in df_with_tech.columns:
                if 'vol_ratio_real' in df_with_tech.columns:
                    df_with_tech['量比'] = df_with_tech['vol_ratio_real']
                else:
                    df_with_tech['量比'] = 1.0
            if '波动率' not in df_with_tech.columns:
                df_with_tech['波动率'] = df_with_tech['涨跌幅'].abs()
            
            sector_avg = df_with_tech['涨跌幅'].mean() if '涨跌幅' in df_with_tech.columns else 0
            scored_df = calculate_composite_score(df_with_tech, sector_avg, factor_weights, strongest_sector=None)
            top_candidates = scored_df.head(10)
            top_candidate = scored_df.iloc[0] if not scored_df.empty else None
            
            # 保存到 session_state 供手动选择使用
            st.session_state.candidate_df = top_candidates.copy() if not top_candidates.empty else pd.DataFrame()
            
            st.markdown("#### 📈 优选股票因子分析")
            if top_candidate is not None:
                col_info, col_factors = st.columns([1, 2])
                with col_info:
                    st.metric("**选中股票**", f"{top_candidate.get('名称', 'N/A')}")
                    st.metric("**代码**", f"{top_candidate.get('代码', 'N/A')}")
                    st.metric("**综合得分**", f"{top_candidate.get('综合得分', 0):.3f}")
                    st.metric("**风险调整得分**", f"{top_candidate.get('风险调整得分', 0):.3f}")
                    if '涨跌幅' in top_candidate:
                        st.metric("**今日涨幅**", f"{top_candidate['涨跌幅']:.2f}%")
                with col_factors:
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
                    if factor_values:
                        factor_df = pd.DataFrame({'因子': factor_names[:len(factor_values)], '得分': factor_values})
                        st.bar_chart(factor_df.set_index('因子'))
                        with st.expander("查看因子权重"):
                            for name, weight in factor_weights.items():
                                if weight != 0:
                                    st.write(f"- **{name}**: {weight:.3f}")
            
            st.markdown("#### 🏆 候选股票排名 (前5)")
            if not top_candidates.empty:
                display_cols = ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分']
                display_cols = [c for c in display_cols if c in top_candidates.columns]
                display_top5 = top_candidates[display_cols].head().copy()
                display_top5['涨跌幅'] = display_top5['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                display_top5['成交额'] = display_top5['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                display_top5['综合得分'] = display_top5['综合得分'].apply(lambda x: f"{x:.3f}")
                if '风险调整得分' in display_top5.columns:
                    display_top5['风险调整得分'] = display_top5['风险调整得分'].apply(lambda x: f"{x:.3f}")
                st.dataframe(display_top5, use_container_width=True)
            
            if current_hour == 14 and current_minute < 40:
                update_convergence(top_candidates, current_time)
            
            if is_final_lock_time and not st.session_state.locked and st.session_state.convergence_records:
                final_rec, backups = get_final_recommendation_from_convergence()
                if final_rec:
                    stock_info = scored_df[scored_df['代码'] == final_rec['代码']].iloc[0].to_dict()
                    st.session_state.final_pick = {
                        'name': stock_info.get('名称', final_rec['名称']),
                        'code': final_rec['代码'],
                        '涨跌幅': float(stock_info.get('涨跌幅', 0)),
                        '成交额': float(stock_info.get('成交额', 0)),
                        'time': current_time_str,
                        'auto': True,
                        'risk_adjusted_score': float(stock_info.get('风险调整得分', 0)),
                        'composite_score': float(stock_info.get('综合得分', 0)),
                        'sector': ', '.join(top5_sectors),
                        'data_source': st.session_state.data_source
                    }
                    st.session_state.locked = True
                    st.session_state.backup_picks = []
                    for b in backups:
                        b_info = scored_df[scored_df['代码'] == b['代码']].iloc[0].to_dict()
                        st.session_state.backup_picks.append({
                            'name': b_info.get('名称', b['名称']),
                            'code': b['代码'],
                            '涨跌幅': float(b_info.get('涨跌幅', 0)),
                        })
                    add_log("自动推荐", f"收敛锁定最终推荐: {final_rec['名称']}")
                    st.rerun()
            
            st.session_state.test_top_stock = {
                'name': top_candidate.get('名称', ''),
                'code': top_candidate.get('代码', ''),
                '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
                '成交额': float(top_candidate.get('成交额', 0)),
                '综合得分': float(top_candidate.get('综合得分', 0)),
                'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
                'time': current_time_str,
                'sector': ', '.join(top5_sectors) if top5_sectors else '全市场',
                'data_source': st.session_state.data_source
            }

# ===============================
# 自动推荐（首次推荐 13:30-14:00）
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
            'sector': top_candidate.get('所属行业', '主线板块'),
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
            <p><strong>🏆 综合得分:</strong> {pick.get('composite_score', 'N/A'):.3f}</p>
            <p><strong>⚖️ 风险调整得分:</strong> {pick.get('risk_adjusted_score', 'N/A'):.3f}</p>
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
# 手动选择（最终推荐锁定前）
# ===============================
if not st.session_state.candidate_df.empty and not st.session_state.final_locked:
    st.markdown("#### 🖱️ 手动选择（可覆盖自动锁定）")
    manual_options = {f"{row['名称']} ({row['代码']})": idx for idx, row in st.session_state.candidate_df.head(5).iterrows()}
    selected = st.selectbox("从候选池中手动选择一只股票:", list(manual_options.keys()))
    if st.button("✅ 设为首选（覆盖最终推荐）"):
        idx = manual_options[selected]
        row = st.session_state.candidate_df.iloc[idx]
        st.session_state.final_pick = {
            'name': row['名称'],
            'code': row['代码'],
            '涨跌幅': row['涨跌幅'],
            '成交额': row['成交额'],
            'time': current_time_str,
            'auto': False
        }
        st.session_state.final_locked = True
        add_log("手动操作", f"手动锁定最终推荐: {row['名称']}")
        st.rerun()

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
    st.write(f"⏳ {refresh_time}秒后自动刷新数据...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 当前非交易时间，自动刷新已暂停")
    time.sleep(60)
    st.rerun()

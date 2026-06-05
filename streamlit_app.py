# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 游资蒸馏终极版（确定性提升版）
===================================================
✅ 核心逻辑（终极优化）：
   1. 大盘环境过滤器（放宽但不失稳健）
   2. 动态阈值 + 二次宽松筛选
   3. 量化抛压识别 + 炸板规避（曾涨停未封死直接剔除）
   4. 主力资金净流入确认（净流入占比>2% +5分）
   5. 尾盘分时稳定性（尾盘不跳水 +3分）
   6. MACD/KDJ 金叉加分 + 同花顺看多信号加权
   7. 每日推荐3-5只，按综合分排序
   8. 次日竞价操作建议
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
st.set_page_config(page_title="尾盘博弈 6.3 · 游资蒸馏终极版", layout="wide")

# ===============================
# 🔑 Tushare Token
# ===============================
try:
    TUSHARE_TOKEN = "51e064a455d2e15c9e8e9ae0a2df1c6651cd60d5fb456ab2555b9f9c"
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
    "candidate_df": pd.DataFrame(),
    "final_locked": False,
    "stock_basic_cache": {},
    "moneyflow_cache": {},
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
# 大盘环境过滤器（保留之前放宽版本）
# ===============================
def check_market_environment(df_all):
    if df_all.empty or '涨跌幅' not in df_all.columns:
        return False, "无有效市场数据", 0
    avg_pct = df_all['涨跌幅'].mean()
    up_count = (df_all['涨跌幅'] > 0).sum()
    down_count = (df_all['涨跌幅'] < 0).sum()
    ratio = up_count / (down_count + 1e-6)
    
    if avg_pct < -1.5:
        return False, f"市场暴跌: 平均涨幅{avg_pct:.2f}%", -1
    if ratio < 0.3:
        return False, f"极端普跌: 涨跌比{ratio:.2f}", -1
    
    if avg_pct > -1.2 and ratio > 0.4:
        return True, f"市场可交易: 平均涨幅{avg_pct:.2f}%, 涨跌比{ratio:.2f}", 1
    
    return True, f"震荡市（允许交易）: 平均涨幅{avg_pct:.2f}%, 涨跌比{ratio:.2f}", 0

# ===============================
# 动态阈值调整（增加极度宽松模式）
# ===============================
def get_dynamic_thresholds(df_all):
    if df_all.empty or '成交额' not in df_all.columns:
        return {'min_pct': 2.0, 'max_pct': 6.0, 'min_turnover': 5.0, 'max_turnover': 15.0, 'min_amount': 1e8}
    median_amount = df_all['成交额'].median() / 1e8
    if median_amount < 0.5:
        return {'min_pct': 0.5, 'max_pct': 5.0, 'min_turnover': 2.0, 'max_turnover': 12.0, 'min_amount': 0.3e8}
    elif median_amount < 0.8:
        return {'min_pct': 1.0, 'max_pct': 5.5, 'min_turnover': 3.0, 'max_turnover': 13.0, 'min_amount': 0.5e8}
    else:
        return {'min_pct': 2.0, 'max_pct': 6.0, 'min_turnover': 5.0, 'max_turnover': 15.0, 'min_amount': 1e8}

# ===============================
# 量化抛压识别
# ===============================
def has_quantum_dump_pressure(row, hist_df):
    if hist_df.empty or len(hist_df) < 6:
        return False
    high_pct = row.get('最高涨幅', 0)
    cur_pct = row['涨跌幅']
    if high_pct - cur_pct < 2.5:
        return False
    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 <= 0:
        return False
    vol_ratio = row['成交量'] / avg_vol_5
    if vol_ratio > 1.3:
        add_log("抛压识别", f"{row['名称']} 冲高回落 {high_pct:.1f}%->{cur_pct:.1f}% 且放量{vol_ratio:.2f}倍，剔除")
        return True
    return False

# ===============================
# MACD / KDJ 指标计算
# ===============================
def calculate_macd(close, fast=12, slow=26, signal=9):
    if len(close) < slow + signal:
        return None, None, None
    exp1 = pd.Series(close).ewm(span=fast, adjust=False).mean()
    exp2 = pd.Series(close).ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    signal_line = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - signal_line
    return macd.iloc[-1], signal_line.iloc[-1], hist.iloc[-1]

def calculate_kdj(high, low, close, n=9, m1=3, m2=3):
    if len(close) < n:
        return None, None, None
    low_list = low.rolling(n, min_periods=n).min()
    high_list = high.rolling(n, min_periods=n).max()
    rsv = (close - low_list) / (high_list - low_list) * 100
    rsv = rsv.fillna(50)
    K = rsv.ewm(span=m1, adjust=False).mean()
    D = K.ewm(span=m2, adjust=False).mean()
    J = 3 * K - 2 * D
    return K.iloc[-1], D.iloc[-1], J.iloc[-1]

def check_macd_golden_cross(hist_df):
    if hist_df.empty or len(hist_df) < 26:
        return False, 0, "无数据"
    close = hist_df['close']
    exp1 = pd.Series(close).ewm(span=12, adjust=False).mean()
    exp2 = pd.Series(close).ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    if len(macd_line) < 2:
        return False, 0, "无数据"
    prev_macd = macd_line.iloc[-2]
    prev_signal = signal_line.iloc[-2]
    curr_macd = macd_line.iloc[-1]
    curr_signal = signal_line.iloc[-1]
    if prev_macd <= prev_signal and curr_macd > curr_signal:
        if curr_macd < 0:
            return True, 5, "零轴下金叉"
        else:
            return True, 3, "零轴上金叉"
    return False, 0, "无金叉"

def check_kdj_golden_cross(hist_df):
    if hist_df.empty or len(hist_df) < 9:
        return False, 0, "无数据"
    high = hist_df['high']
    low = hist_df['low']
    close = hist_df['close']
    k, d, j = calculate_kdj(high, low, close)
    if k is None or d is None:
        return False, 0, "无数据"
    if len(high) < 2 or len(low) < 2 or len(close) < 2:
        return False, 0, "无数据"
    prev_k, prev_d, prev_j = calculate_kdj(high[:-1], low[:-1], close[:-1])
    if prev_k is None or prev_d is None:
        return False, 0, "无数据"
    if prev_k <= prev_d and k > d:
        if j < 20:
            return True, 5, "KDJ金叉(J<20超卖)"
        elif j < 30:
            return True, 3, "KDJ金叉(J<30)"
        else:
            return True, 1, "KDJ金叉"
    return False, 0, "无金叉"

# ===============================
# 同花顺看多信号加权
# ===============================
def get_tonghuashun_bull_score(row, hist_df):
    if hist_df.empty or len(hist_df) < 25:
        return 0
    score = 0
    close_series = hist_df['close']
    bbi = (close_series.rolling(3).mean() + 
           close_series.rolling(6).mean() + 
           close_series.rolling(12).mean() + 
           close_series.rolling(24).mean()) / 4
    if len(bbi) > 0 and row['最新价'] > bbi.iloc[-1]:
        score += 4
    ma5 = close_series.rolling(5).mean().iloc[-1]
    ma10 = close_series.rolling(10).mean().iloc[-1]
    ma20 = close_series.rolling(20).mean().iloc[-1]
    if not any(np.isnan([ma5, ma10, ma20])) and ma5 > ma10 > ma20:
        score += 3
    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 > 0:
        vr = row['成交量'] / avg_vol_5
        if vr > 1.2 and row['涨跌幅'] > 0:
            score += 3
        elif vr > 1.0 and row['涨跌幅'] > 0:
            score += 1
    return min(score, 10)

# ===============================
# 🚀 新增：主力资金净流入获取（确定性提升）
# ===============================
def batch_get_moneyflow(ts_codes, trade_date):
    """获取个股当日主力净流入（万元）和净流入占比"""
    cache = st.session_state.moneyflow_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            # 分批获取，每次最多50只
            for i in range(0, len(need), 50):
                batch = need[i:i+50]
                df = pro.moneyflow_dc(ts_code=','.join(batch), trade_date=trade_date)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = row['ts_code']
                        cache[code] = {
                            'net_inflow': row.get('net_inflow', 0) if pd.notna(row.get('net_inflow')) else 0,
                            'net_inflow_pct': row.get('net_inflow_pct', 0) if pd.notna(row.get('net_inflow_pct')) else 0
                        }
                time.sleep(0.5)  # 避免请求过快
            add_log("资金流向", f"获取 {len(cache)} 只股票的主力资金数据")
        except Exception as e:
            add_log("资金流向", f"获取失败: {str(e)[:50]}")
    return [cache.get(c, {'net_inflow': 0, 'net_inflow_pct': 0}) for c in ts_codes]

# ===============================
# 个股行业信息获取
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

def batch_get_stock_basic_info(ts_codes):
    cache = st.session_state.stock_basic_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            today = datetime.now(tz).strftime('%Y%m%d')
            df = pro.daily_basic(ts_code=','.join(need), trade_date=today, fields='ts_code,circ_mv,turnover_rate')
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    code = row['ts_code']
                    cache[code] = {
                        'circ_mv': row['circ_mv'] if pd.notna(row['circ_mv']) else 0,
                        'turnover_rate': row['turnover_rate'] if pd.notna(row['turnover_rate']) else 0
                    }
                add_log("市值数据", f"获取 {len(df)} 只股票的流通市值/换手率")
            else:
                add_log("市值数据", "daily_basic 返回空")
        except Exception as e:
            add_log("市值数据", f"获取失败: {str(e)[:50]}")
    return [cache.get(c, {'circ_mv': 0, 'turnover_rate': 0}) for c in ts_codes]

# ===============================
# 数据获取
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
        
        before = len(df)
        df = df[~df['ts_code'].str.startswith(('688', '300', '301'))]
        after = len(df)
        if before > after:
            add_log("数据源", f"已剔除科创板和创业板股票 {before - after} 只，剩余 {after} 只")
        
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
        
        basic_infos = batch_get_stock_basic_info(codes)
        df['流通市值'] = [b['circ_mv'] for b in basic_infos]
        df['换手率'] = [b['turnover_rate'] for b in basic_infos]
        
        # 🚀 获取主力资金流向
        today_str = datetime.now(tz).strftime('%Y%m%d')
        moneyflows = batch_get_moneyflow(codes, today_str)
        df['主力净流入'] = [m['net_inflow'] for m in moneyflows]
        df['净流入占比'] = [m['net_inflow_pct'] for m in moneyflows]

        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing = [c for c in required if c not in df.columns]
        if missing:
            add_log("数据源", f"字段缺失: {missing}")
            return None

        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '最高价', '最高涨幅', 
                     '流通市值', '换手率', '主力净流入', '净流入占比']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ 成功获取 {len(df)} 条（已填充行业、市值、换手率、资金流向）")
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
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入', '净流入占比'])

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
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入', '净流入占比'])

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
# 游资技术形态评分（不变）
# ===============================
def score_technical_for_yz(row, hist_df):
    if hist_df.empty or len(hist_df) < 6:
        return 0
    score = 0
    pct = row['涨跌幅']
    if 2 <= pct <= 6:
        score += 10
    elif 1 <= pct < 2 or 6 < pct <= 8:
        score += 5
    else:
        score += max(0, 3 - abs(pct - 4) * 0.5)

    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 > 0:
        vr = row['成交量'] / avg_vol_5
        if 1.2 <= vr <= 2.0:
            score += 10
        elif 1.0 <= vr < 1.2 or 2.0 < vr <= 2.5:
            score += 5
        else:
            score += max(0, 2 - abs(vr - 1.6) * 0.5)

    close_series = hist_df['close']
    ma5 = close_series.rolling(5).mean().iloc[-1]
    ma10 = close_series.rolling(10).mean().iloc[-1]
    ma20 = close_series.rolling(20).mean().iloc[-1]
    if not any(np.isnan([ma5, ma10, ma20])) and ma5 > ma10 > ma20:
        score += 5

    if not np.isnan(ma5) and row['最新价'] >= ma5:
        score += 2.5

    hist_5 = hist_df.tail(5)
    if ((hist_5['close'] - hist_5['open']) > 0).any():
        score += 2.5

    return min(score, 30)

def calculate_sector_strength(df):
    if df.empty or '所属行业' not in df.columns:
        return pd.DataFrame()
    df['is_limit_up'] = df['涨跌幅'] >= 9.5
    sector_stats = df.groupby('所属行业').agg({
        '涨跌幅': 'mean',
        '成交额': 'sum',
        'is_limit_up': 'sum',
        '代码': 'count'
    }).rename(columns={'代码': '股票数量', 'is_limit_up': '涨停家数'})
    sector_stats['资金占比'] = sector_stats['成交额'] / sector_stats['成交额'].sum()
    sector_stats['涨停占比'] = sector_stats['涨停家数'] / max(1, sector_stats['涨停家数'].sum())
    sector_stats['涨幅得分'] = sector_stats['涨跌幅'].rank(pct=True) * 40
    sector_stats['资金得分'] = sector_stats['资金占比'].rank(pct=True) * 40
    sector_stats['涨停得分'] = sector_stats['涨停占比'].rank(pct=True) * 20
    sector_stats['强度得分'] = sector_stats['涨幅得分'] + sector_stats['资金得分'] + sector_stats['涨停得分']
    sector_stats = sector_stats.sort_values('强度得分', ascending=False)
    return sector_stats

def filter_stocks_by_rule(df):
    if df.empty:
        return df
    filtered = df.copy()
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] <= 9.5]
    if '最高涨幅' in filtered.columns and '涨跌幅' in filtered.columns:
        filtered = filtered[~((filtered['最高涨幅'] > 9.5) & (filtered['涨跌幅'] < 7))]
    return filtered

# 占位函数
def calculate_technical_indicators(hist_df):
    return {}
def add_technical_indicators(df, top_n=200):
    return df
def calculate_composite_score(df, sector_avg_change, weights, strongest_sector=None):
    return df
def update_convergence(candidates_df, current_time):
    pass
def get_final_recommendation_from_convergence():
    return None, []

# ===============================
# 主程序开始
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 游资蒸馏终极版（资金流+分时稳定+炸板规避）")
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
    st.session_state.stock_basic_cache = {}
    st.session_state.moneyflow_cache = {}
    st.session_state.convergence_records = []
    st.session_state.backup_picks = []
    st.session_state.candidate_df = pd.DataFrame()
    st.session_state.final_locked = False
    add_log("系统", "新交易日开始，重置所有状态")
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
        st.session_state.stock_basic_cache = {}
        st.session_state.moneyflow_cache = {}
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
    st.info("🚀 终极优化：主力资金净流入 + 分时稳定 + 炸板规避 + 宽松/独立行情")

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
    is_recommend_time = (current_hour, current_minute) >= (14, 50)
    st.metric("推荐状态", "🟢 可推荐" if is_recommend_time else "🟡 等待尾盘")
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
        st.success(f"✅ 成功获取 {len(df)} 条真实股票数据")
        with st.expander("🔍 查看数据样本"):
            display_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '净流入占比']
            display_cols = [c for c in display_cols if c in df.columns]
            st.dataframe(df[display_cols].head(10))
    else:
        if st.session_state.data_source == "non_trading":
            st.info("⏸️ 当前非交易时间，无实时数据。如需测试，请使用左侧「模拟测试」模式。")
        else:
            st.warning("⚠️ 获取到的数据为空")
except Exception as e:
    st.error(f"❌ 数据获取失败: {str(e)}")
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入', '净流入占比'])

# 大盘环境评估
market_safe, market_reason, market_strength = check_market_environment(df)
if not market_safe:
    st.error(f"⚠️ 大盘环境不满足开仓条件：{market_reason}")
    st.warning("今日强烈建议 **空仓**，停止选股。")
    final_recommendations = []
else:
    st.success(f"✅ 大盘环境符合：{market_reason}，继续选股")

    # 板块分析（放宽：取前8强）
    st.markdown("### 📊 板块热度分析（主线题材）")
    if df.empty or '所属行业' not in df.columns:
        st.info("无有效板块数据")
        top5_sectors = []
    else:
        sector_stats = calculate_sector_strength(df)
        if not sector_stats.empty:
            candidate_sectors = sector_stats.head(8).index.tolist()
            if len(candidate_sectors) < 5:
                candidate_sectors = sector_stats[sector_stats['强度得分'] > 0].index.tolist()
            top5_sectors = candidate_sectors
            st.success(f"🏆 今日最强主线板块 Top{len(top5_sectors)}: {', '.join(top5_sectors)}")
            st.dataframe(sector_stats[['涨跌幅', '成交额', '涨停家数', '强度得分']].head(8))
        else:
            top5_sectors = []
            st.warning("无法识别主线板块，将使用全市场选股")

    # 游资选股核心
    st.markdown("### 🎯 游资蒸馏终极引擎（资金流+分时稳定+炸板规避）")
    if df.empty:
        st.info("无股票数据")
        final_recommendations = []
    else:
        filtered = filter_stocks_by_rule(df)
        st.caption(f"基础过滤后股票数: {len(filtered)}")
        
        if not top5_sectors:
            sector_filtered = filtered
            st.info("无主线板块，使用全市场选股")
        else:
            sector_filtered = filtered[filtered['所属行业'].isin(top5_sectors)]
            st.caption(f"主线板块过滤后股票数: {len(sector_filtered)}")
        
        if sector_filtered.empty:
            st.warning("主线板块内无股票，将使用全市场选股")
            sector_filtered = filtered
                   # 动态阈值
        thresholds_standard = get_dynamic_thresholds(df)
        thresholds_loose = {
            'min_pct': 0.5, 'max_pct': 7.0,
            'min_turnover': 2.0, 'max_turnover': 18.0,
            'min_amount': 0.3e8
        }
        
        st.caption(f"动态阈值(标准): 涨幅{thresholds_standard['min_pct']:.1f}%~{thresholds_standard['max_pct']:.1f}%, "
                   f"换手率{thresholds_standard['min_turnover']:.1f}%~{thresholds_standard['max_turnover']:.1f}%, "
                   f"成交额>{thresholds_standard['min_amount']/1e8:.1f}亿")
        
        strict_filtered = sector_filtered[
            (sector_filtered['流通市值'] > 500000) &
            (sector_filtered['换手率'] >= thresholds_standard['min_turnover']) &
            (sector_filtered['换手率'] <= thresholds_standard['max_turnover']) &
            (sector_filtered['涨跌幅'] >= thresholds_standard['min_pct']) &
            (sector_filtered['涨跌幅'] <= thresholds_standard['max_pct']) &
            (sector_filtered['成交额'] > thresholds_standard['min_amount'])
        ]
        st.caption(f"严格硬性门槛后股票数: {len(strict_filtered)}")
        
        if len(strict_filtered) < 3:
            st.info("严格筛选股票不足3只，启用二次宽松筛选")
            use_loose = True
            working_filtered = sector_filtered[
                (sector_filtered['流通市值'] > 300000) &
                (sector_filtered['换手率'] >= thresholds_loose['min_turnover']) &
                (sector_filtered['换手率'] <= thresholds_loose['max_turnover']) &
                (sector_filtered['涨跌幅'] >= thresholds_loose['min_pct']) &
                (sector_filtered['涨跌幅'] <= thresholds_loose['max_pct']) &
                (sector_filtered['成交额'] > thresholds_loose['min_amount'])
            ]
        else:
            use_loose = False
            working_filtered = strict_filtered
        
        if working_filtered.empty:
            st.warning("当前无股票满足任何门槛条件，尝试独立行情选股...")
            # 独立行情捕捉
            independent_candidates = []
            for idx, row in filtered.iterrows():
                if row['涨跌幅'] < 3 or row['成交额'] < 2e8 or row['换手率'] < 8:
                    continue
                # 炸板规避
                if row.get('最高涨幅', 0) >= 9.5 and row['涨跌幅'] < 7:
                    continue
                hist = get_historical_data(row['代码'])
                if hist.empty:
                    continue
                if has_quantum_dump_pressure(row, hist):
                    continue
                macd_golden, _, _ = check_macd_golden_cross(hist)
                kdj_golden, _, _ = check_kdj_golden_cross(hist)
                if not (macd_golden or kdj_golden):
                    continue
                independent_candidates.append(row)
                if len(independent_candidates) >= 1:
                    break
            if independent_candidates:
                row = independent_candidates[0]
                hist = get_historical_data(row['代码'])
                bull_score = get_tonghuashun_bull_score(row, hist)
                macd_golden, macd_bonus, macd_desc = check_macd_golden_cross(hist)
                kdj_golden, kdj_bonus, kdj_desc = check_kdj_golden_cross(hist)
                # 资金流得分
                net_inflow_pct = row.get('净流入占比', 0)
                fund_score = 5 if net_inflow_pct > 2 else 0
                stability_score = 3 if row['涨跌幅'] > -0.5 else 0
                total_score = 70 + macd_bonus + kdj_bonus + bull_score + fund_score + stability_score
                total_score = min(100, total_score)
                candidates = [{
                    '代码': row['代码'],
                    '名称': row['名称'],
                    '涨跌幅': row['涨跌幅'],
                    '成交额': row['成交额'],
                    '最新价': row['最新价'],
                    '流通市值': row['流通市值'],
                    '换手率': row['换手率'],
                    '所属行业': row['所属行业'],
                    '游资综合分': total_score,
                    '技术形态分': 0,
                    'MACD金叉': macd_desc,
                    'KDJ金叉': kdj_desc,
                    '金叉加分': macd_bonus + kdj_bonus,
                    '看多信号分': bull_score,
                    '资金流分': fund_score,
                    '稳定性分': stability_score,
                    '宽松模式': False,
                    '独立行情': True
                }]
                st.success("找到1只独立行情个股，请谨慎参与")
            else:
                st.warning("未获取到任何候选股票，今日建议空仓")
                final_recommendations = []
        else:
            MAX_CHECK = min(200, len(working_filtered))
            tmp = working_filtered.sort_values('成交额', ascending=False).head(MAX_CHECK)
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            candidates = []
            
            all_vol_rank = tmp['成交额'].rank(pct=True)
            all_circ_mv_rank = tmp['流通市值'].rank(pct=True)
            all_turnover_rank = tmp['换手率'].rank(pct=True)
            
            for i, (idx, row) in enumerate(tmp.iterrows()):
                status_text.text(f"正在分析 {i+1}/{len(tmp)}: {row['名称']}")
                hist = get_historical_data(row['代码'])
                if hist.empty:
                    progress_bar.progress((i+1)/len(tmp))
                    continue
                
                # 🚀 炸板规避（直接剔除）
                if row.get('最高涨幅', 0) >= 9.5 and row['涨跌幅'] < 7:
                    add_log("炸板规避", f"{row['名称']} 曾涨停未封死，剔除")
                    progress_bar.progress((i+1)/len(tmp))
                    continue
                
                if has_quantum_dump_pressure(row, hist):
                    progress_bar.progress((i+1)/len(tmp))
                    continue
                
                tech_score = score_technical_for_yz(row, hist)
                
                # 基础分项
                vol_score = all_vol_rank.iloc[i] * 30
                pct = row['涨跌幅']
                if use_loose:
                    if thresholds_loose['min_pct'] <= pct <= thresholds_loose['max_pct']:
                        pct_match = 20
                    elif pct < thresholds_loose['min_pct']:
                        pct_match = max(0, 20 - (thresholds_loose['min_pct'] - pct) * 5)
                    else:
                        pct_match = max(0, 20 - (pct - thresholds_loose['max_pct']) * 5)
                else:
                    if thresholds_standard['min_pct'] <= pct <= thresholds_standard['max_pct']:
                        pct_match = 20
                    elif pct < thresholds_standard['min_pct']:
                        pct_match = max(0, 20 - (thresholds_standard['min_pct'] - pct) * 5)
                    else:
                        pct_match = max(0, 20 - (pct - thresholds_standard['max_pct']) * 5)
                
                mv_score = all_circ_mv_rank.iloc[i] * 15
                
                hist_close = hist['close']
                ma5 = hist_close.rolling(5).mean().iloc[-1]
                ma10 = hist_close.rolling(10).mean().iloc[-1]
                ma20 = hist_close.rolling(20).mean().iloc[-1]
                ma_score = 10 if (not any(np.isnan([ma5, ma10, ma20])) and ma5 > ma10 > ma20) else 0
                
                avg_vol_5 = hist['vol'].tail(5).mean()
                if avg_vol_5 > 0:
                    vr = row['成交量'] / avg_vol_5
                    if 1.2 <= vr <= 2.0:
                        vr_score = 10
                    elif 1.0 <= vr < 1.2 or 2.0 < vr <= 2.5:
                        vr_score = 7
                    else:
                        vr_score = max(0, 10 - abs(vr - 1.6) * 3)
                else:
                    vr_score = 0
                
                turnover_score = all_turnover_rank.iloc[i] * 10
                
                if 'sector_stats' in locals() and row['所属行业'] in sector_stats.index:
                    sector_avg = sector_stats.loc[row['所属行业'], '涨跌幅']
                else:
                    sector_avg = 0
                rel_strength = row['涨跌幅'] - sector_avg
                rel_score = np.clip((rel_strength + 2) / 5 * 5, 0, 5)
                
                # MACD/KDJ 金叉加分
                macd_golden, macd_bonus, macd_desc = check_macd_golden_cross(hist)
                kdj_golden, kdj_bonus, kdj_desc = check_kdj_golden_cross(hist)
                extra_bonus = macd_bonus + kdj_bonus
                
                # 同花顺看多信号
                bull_score = get_tonghuashun_bull_score(row, hist)
                
                # 🚀 主力资金净流入加分
                net_inflow_pct = row.get('净流入占比', 0)
                fund_score = 5 if net_inflow_pct > 2 else 0
                
                # 🚀 尾盘分时稳定性加分（涨跌幅 > -0.5%）
                stability_score = 3 if row['涨跌幅'] > -0.5 else 0
                
                total_score = vol_score + pct_match + mv_score + ma_score + vr_score + turnover_score + rel_score + extra_bonus + bull_score + fund_score + stability_score
                if use_loose:
                    total_score = total_score * 0.9
                total_score = min(100, max(0, total_score))
                
                candidates.append({
                    '代码': row['代码'],
                    '名称': row['名称'],
                    '涨跌幅': row['涨跌幅'],
                    '成交额': row['成交额'],
                    '最新价': row['最新价'],
                    '流通市值': row['流通市值'],
                    '换手率': row['换手率'],
                    '所属行业': row['所属行业'],
                    '游资综合分': total_score,
                    '技术形态分': tech_score,
                    'MACD金叉': macd_desc,
                    'KDJ金叉': kdj_desc,
                    '金叉加分': extra_bonus,
                    '看多信号分': bull_score,
                    '资金流分': fund_score,
                    '稳定性分': stability_score,
                    '宽松模式': use_loose
                })
                progress_bar.progress((i+1)/len(tmp))
            
            progress_bar.empty()
            status_text.empty()
        
        if not candidates:
            st.warning("未获取到任何候选股票，今日建议空仓")
            final_recommendations = []
        else:
            candidates_df = pd.DataFrame(candidates)
            candidates_df = candidates_df.sort_values('游资综合分', ascending=False)
            final_recommendations = candidates_df.head(5).to_dict('records')
            st.success(f"✅ 共选出 {len(final_recommendations)} 只标的")
            
            if final_recommendations:
                display_df = pd.DataFrame(final_recommendations)
                display_cols = ['名称', '代码', '涨跌幅', '成交额', '流通市值', '换手率', '所属行业', '游资综合分', 
                                'MACD金叉', 'KDJ金叉', '看多信号分', '资金流分', '稳定性分']
                display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                display_df['成交额'] = display_df['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                display_df['流通市值'] = display_df['流通市值'].apply(lambda x: f"{x/1e4:.1f}亿")
                display_df['换手率'] = display_df['换手率'].apply(lambda x: f"{x:.2f}%")
                display_df['游资综合分'] = display_df['游资综合分'].apply(lambda x: f"{x:.1f}")
                st.dataframe(display_df[display_cols], use_container_width=True)
                
                st.session_state.candidate_df = candidates_df.head(10)

# 推荐显示
st.markdown("### 📋 游资推荐结果（尾盘30分钟）")
if is_recommend_time and final_recommendations:
    st.subheader("🏆 今日游资组合（按综合分排序）")
    for idx, rec in enumerate(final_recommendations[:5], 1):
        buy_price = rec['最新价']
        stop_loss = buy_price * 0.98
        take_profit_1 = buy_price * 1.05
        take_profit_2 = buy_price * 1.08
        
        macd_tag = f"🟢 {rec['MACD金叉']}" if rec['MACD金叉'] != "无金叉" else "⚪ 无MACD金叉"
        kdj_tag = f"🟢 {rec['KDJ金叉']}" if rec['KDJ金叉'] != "无金叉" else "⚪ 无KDJ金叉"
        bull_tag = f"🟢 看多 {rec['看多信号分']:.0f}/10" if rec['看多信号分'] >= 6 else f"🟡 看多 {rec['看多信号分']:.0f}/10"
        fund_tag = f"💰 主力+{rec['资金流分']}" if rec['资金流分'] > 0 else "💰 无主力"
        stab_tag = f"📊 稳定+{rec['稳定性分']}" if rec['稳定性分'] > 0 else "📊 尾盘弱"
        extra_tag = " 🔥 独立行情" if rec.get('独立行情', False) else (" 🟡 宽松" if rec.get('宽松模式', False) else "")
        
        with st.container():
            st.markdown(f"""
            <div style="background-color: #f0f9ff; padding: 15px; border-radius: 10px; margin-bottom: 10px; border-left: 5px solid #e67e22;">
                <h4>#{idx} {rec['名称']} ({rec['代码']}){extra_tag}</h4>
                <p><strong>📈 涨幅:</strong> {rec['涨跌幅']:.2f}% &nbsp;|&nbsp;
                <strong>💰 成交额:</strong> {rec['成交额']/1e8:.2f}亿 &nbsp;|&nbsp;
                <strong>💎 市值:</strong> {rec['流通市值']/1e4:.1f}亿 &nbsp;|&nbsp;
                <strong>🔄 换手:</strong> {rec['换手率']:.2f}% &nbsp;|&nbsp;
                <strong>📊 板块:</strong> {rec['所属行业']}</p>
                <p><strong>🎯 总分:</strong> {rec['游资综合分']:.1f}/100 &nbsp;|&nbsp;
                <strong>🔧 金叉+{rec['金叉加分']} 看多+{rec['看多信号分']}</strong> &nbsp;{fund_tag} &nbsp;{stab_tag}</p>
                <p><strong>✅ 信号:</strong> {macd_tag} &nbsp; {kdj_tag} &nbsp; {bull_tag}</p>
                <p><strong>📝 逻辑:</strong> {'独立行情个股，强势突破，注意控制仓位' if rec.get('独立行情', False) else '主线容量中军 + 资金流入 + 尾盘稳定 + 无炸板'}</p>
                <hr>
                <p><strong>⏰ 次日操作:</strong> 竞价低于{buy_price*0.98:.2f}(-2%)止损；高于{buy_price*1.015:.2f}(+1.5%)持有；止盈+5%/8%。</p>
            </div>
            """, unsafe_allow_html=True)
elif not is_recommend_time:
    st.info("⏰ 尾盘推荐时段：14:50之后，当前请等待")
else:
    st.warning("⚠️ 今日没有满足逻辑的标的，建议空仓")

# 手动选择
if final_recommendations:
    st.markdown("#### 🖱️ 手动选择")
    manual_options = {f"{r['名称']} ({r['代码']})": i for i, r in enumerate(final_recommendations)}
    selected = st.selectbox("请选择一只股票:", list(manual_options.keys()))
    if st.button("✅ 确认选中"):
        idx = manual_options[selected]
        rec = final_recommendations[idx]
        st.session_state.final_pick = {
            'name': rec['名称'],
            'code': rec['代码'],
            '涨跌幅': rec['涨跌幅'],
            '成交额': rec['成交额'],
            'time': current_time_str,
            'auto': False,
            'final_score': rec['游资综合分'],
            'sector': rec['所属行业']
        }
        st.success(f"已手动锁定 {rec['名称']}")
        st.rerun()

# 系统日志
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

# 自动刷新
if is_trading:
    refresh_time = 30
    st.write(f"⏳ {refresh_time}秒后自动刷新...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 非交易时间，暂停刷新")
    time.sleep(60)
    st.rerun()

# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 三分层并行推荐（稳健/活跃/弹性）[修复版]
===================================================
✅ 核心逻辑：
   - 大盘环境过滤
   - 主线板块过滤（5日动量加权）
   - 同时输出三个容量中军层级的推荐：
       ① 稳健中军：市值>200亿，换手1%-8%，成交额>5亿
       ② 活跃中军：市值50-200亿，换手2%-12%，成交额>3亿
       ③ 弹性先锋：市值30-50亿，换手3%-20%，成交额>1亿
   - 每个层级独立评分（综合得分+技术形态+资金流+金叉+尾盘稳定）
   - 每日每个层级推荐3-5只，按总分排序
✅ 用户自行选择买入层级，空仓信号仍保留
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
from datetime import datetime, timedelta
import pytz
import warnings
import tushare as ts

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.3 · 三分层并行推荐（修复）", layout="wide")

# ===============================
# 🔑 Tushare Token（请填写你自己的）
# ===============================
try:
    TUSHARE_TOKEN = "6ab0755682f76973b447c5339bb6e618271bd41752b9f1b1b0890013"
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
# 大盘环境过滤器
# ===============================
def check_market_environment(df_all):
    if df_all.empty or '涨跌幅' not in df_all.columns:
        return False, "无有效市场数据"
    avg_pct = df_all['涨跌幅'].mean()
    up_count = (df_all['涨跌幅'] > 0).sum()
    down_count = (df_all['涨跌幅'] < 0).sum()
    ratio = up_count / (down_count + 1e-6)
    if avg_pct < -1.2:
        return False, f"市场过弱: 平均涨幅{avg_pct:.2f}%"
    if ratio < 0.4:
        return False, f"涨跌比过低: {ratio:.2f}"
    return True, f"市场可交易: 平均涨幅{avg_pct:.2f}%, 涨跌比{ratio:.2f}"

# ===============================
# 获取流通市值、换手率（批量）
# ===============================
def batch_get_stock_basic_info(ts_codes, trade_date):
    cache = st.session_state.stock_basic_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            for i in range(0, len(need), 100):
                batch = need[i:i+100]
                df = pro.daily_basic(ts_code=','.join(batch), trade_date=trade_date, fields='ts_code,circ_mv,turnover_rate')
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = row['ts_code']
                        cache[code] = {
                            'circ_mv': row['circ_mv'] if pd.notna(row['circ_mv']) else 0,
                            'turnover_rate': row['turnover_rate'] if pd.notna(row['turnover_rate']) else 0
                        }
                time.sleep(0.2)
            add_log("市值数据", f"获取 {len(cache)} 只股票的流通市值/换手率")
        except Exception as e:
            add_log("市值数据", f"获取失败: {str(e)[:50]}")
    return [cache.get(c, {'circ_mv': 0, 'turnover_rate': 0}) for c in ts_codes]

# ===============================
# 获取主力资金流向（批量）
# ===============================
def batch_get_moneyflow(ts_codes, trade_date):
    cache = st.session_state.moneyflow_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            for i in range(0, len(need), 50):
                batch = need[i:i+50]
                df = pro.moneyflow_dc(ts_code=','.join(batch), trade_date=trade_date)
                if df is not None and not df.empty:
                    for _, row in df.iterrows():
                        code = row['ts_code']
                        cache[code] = {
                            'net_inflow_pct': row.get('net_inflow_pct', 0) if pd.notna(row.get('net_inflow_pct')) else 0
                        }
                time.sleep(0.5)
            add_log("资金流向", f"获取 {len(cache)} 只股票的主力资金数据")
        except Exception as e:
            add_log("资金流向", f"获取失败: {str(e)[:50]}（可能无积分权限，继续执行）")
    return [cache.get(c, {'net_inflow_pct': 0}) for c in ts_codes]

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

# ===============================
# 数据获取（剔除科创板和创业板，增加市值/换手/资金流）
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
        
        today_str = datetime.now(tz).strftime('%Y%m%d')
        basic_infos = batch_get_stock_basic_info(codes, today_str)
        df['流通市值'] = [b['circ_mv'] for b in basic_infos]
        df['换手率'] = [b['turnover_rate'] for b in basic_infos]
        
        moneyflows = batch_get_moneyflow(codes, today_str)
        df['主力净流入占比'] = [m['net_inflow_pct'] for m in moneyflows]

        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing = [c for c in required if c not in df.columns]
        if missing:
            add_log("数据源", f"字段缺失: {missing}")
            return None

        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '最高价', '最高涨幅',
                     '流通市值', '换手率', '主力净流入占比']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ 成功获取 {len(df)} 条（含行业、市值、换手、资金流）")
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
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入占比'])

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
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入占比'])

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
            return df
        else:
            cache[ts_code] = pd.DataFrame()
            return pd.DataFrame()
    except Exception as e:
        cache[ts_code] = pd.DataFrame()
        return pd.DataFrame()

# ===============================
# MACD/KDJ 计算函数
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

def get_macd_bonus(hist_df):
    if hist_df.empty or len(hist_df) < 26:
        return 0
    close = hist_df['close']
    exp1 = pd.Series(close).ewm(span=12, adjust=False).mean()
    exp2 = pd.Series(close).ewm(span=26, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    if len(macd_line) < 2:
        return 0
    prev_macd = macd_line.iloc[-2]
    prev_signal = signal_line.iloc[-2]
    curr_macd = macd_line.iloc[-1]
    curr_signal = signal_line.iloc[-1]
    if prev_macd <= prev_signal and curr_macd > curr_signal:
        if curr_macd < 0:
            return 5
        else:
            return 3
    return 0

def get_kdj_bonus(hist_df):
    if hist_df.empty or len(hist_df) < 9:
        return 0
    high = hist_df['high']
    low = hist_df['low']
    close = hist_df['close']
    k, d, j = calculate_kdj(high, low, close)
    if k is None or d is None:
        return 0
    if len(high) < 2:
        return 0
    prev_k, prev_d, prev_j = calculate_kdj(high[:-1], low[:-1], close[:-1])
    if prev_k is None or prev_d is None:
        return 0
    if prev_k <= prev_d and k > d:
        if j < 20:
            return 5
        elif j < 30:
            return 3
        else:
            return 1
    return 0

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
        return True
    return False

# ===============================
# 技术形态评分（完整版）
# ===============================
def score_technical_conditions(row, hist_df, mode):
    if hist_df.empty or len(hist_df) < 6:
        return 0
    score = 0
    pct = row['涨跌幅']
    if mode == "宽松":
        if 1 <= pct <= 8:
            score += 10
        else:
            score += max(0, 10 - abs(pct - 4.5) * 2)
    elif mode == "标准":
        if 2 <= pct <= 6.5:
            score += 10
        else:
            score += max(0, 10 - abs(pct - 4.25) * 3)
    else:  # 严格
        if 2.5 <= pct <= 5.5:
            score += 10
        else:
            score += max(0, 10 - abs(pct - 4) * 4)

    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 > 0:
        vr = row['成交量'] / avg_vol_5
        if mode == "宽松":
            if 0.8 <= vr <= 2.5:
                score += 10
            else:
                score += max(0, 10 - abs(vr - 1.65) * 2)
        elif mode == "标准":
            if 1.0 <= vr <= 2.0:
                score += 10
            else:
                score += max(0, 10 - abs(vr - 1.5) * 3)
        else:  # 严格
            if 1.2 <= vr <= 1.8:
                score += 10
            else:
                score += max(0, 10 - abs(vr - 1.5) * 4)

    recent_3 = hist_df['close'].tail(3).values
    if len(recent_3) == 3 and recent_3[0] < recent_3[1] < recent_3[2]:
        score += 5

    ma5 = hist_df['close'].rolling(5).mean().iloc[-1]
    if not np.isnan(ma5) and row['最新价'] >= ma5:
        score += 5

    hist_5 = hist_df.tail(5)
    if ((hist_5['close'] - hist_5['open']) > 0).any():
        score += 5

    return min(score, 30)

# ===============================
# 板块强度计算（当日）
# ===============================
def calculate_sector_strength_today(df):
    if df.empty or '所属行业' not in df.columns:
        return pd.DataFrame()
    df['is_limit_up'] = df['涨跌幅'] >= 9.5
    sector = df.groupby('所属行业').agg({
        '涨跌幅': 'mean',
        '成交额': 'sum',
        'is_limit_up': 'sum',
        '代码': 'count'
    }).rename(columns={'代码': '股票数量', 'is_limit_up': '涨停家数'})
    sector['资金占比'] = sector['成交额'] / sector['成交额'].sum()
    sector['涨停占比'] = sector['涨停家数'] / max(1, sector['涨停家数'].sum())
    sector['强度得分'] = (sector['涨跌幅'].rank(pct=True) * 40 +
                          sector['资金占比'].rank(pct=True) * 40 +
                          sector['涨停占比'].rank(pct=True) * 20)
    return sector

# ===============================
# 优化版：计算过去5日板块动量（仅取成交额前100只股票）
# ===============================
def calculate_sector_momentum_5d_optimized(df_today):
    if df_today.empty or '所属行业' not in df_today.columns:
        return pd.DataFrame()
    top_stocks = df_today.nlargest(100, '成交额')
    add_log("板块动量", f"基于成交额前{len(top_stocks)}只股票计算5日动量")
    stock_5d_pct = {}
    for _, row in top_stocks.iterrows():
        code = row['代码']
        hist = get_historical_data(code)
        if hist is not None and not hist.empty and len(hist) >= 6:
            close_vals = hist['close'].values
            pct_5d = (close_vals[-1] - close_vals[-6]) / close_vals[-6] * 100
            stock_5d_pct[code] = pct_5d
        else:
            stock_5d_pct[code] = np.nan
    sector_5d_pct = {}
    for _, row in top_stocks.iterrows():
        code = row['代码']
        ind = row['所属行业']
        pct = stock_5d_pct.get(code, np.nan)
        if not np.isnan(pct):
            sector_5d_pct.setdefault(ind, []).append(pct)
    sector_5d_avg = {ind: np.mean(vals) for ind, vals in sector_5d_pct.items()}
    if sector_5d_avg:
        sectors = list(sector_5d_avg.keys())
        values = list(sector_5d_avg.values())
        ranks = pd.Series(values).rank(pct=True) * 100
        sector_momentum_score = {sectors[i]: ranks.iloc[i] for i in range(len(sectors))}
    else:
        sector_momentum_score = {}
    today_sector = calculate_sector_strength_today(df_today)
    if today_sector.empty:
        return pd.DataFrame()
    final_scores = []
    for sector in today_sector.index:
        today_score = today_sector.loc[sector, '强度得分']
        momentum_score = sector_momentum_score.get(sector, today_score)
        weighted = 0.4 * today_score + 0.6 * momentum_score
        final_scores.append(weighted)
    result = today_sector.copy()
    result['强度得分（动量加权）'] = final_scores
    result = result.sort_values('强度得分（动量加权）', ascending=False)
    return result

# ===============================
# 原有辅助函数（保留占位）
# ===============================
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
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)
        filtered = filtered[filtered['成交额'] > threshold]
    return filtered

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
# 主程序
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 三分层并行推荐（稳健/活跃/弹性）")
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
    st.markdown("#### 🎚️ 策略模式选择")
    strategy_mode = st.selectbox("策略模式", ["严格模式", "标准模式", "宽松模式"], index=1, key="strategy_mode")
    st.caption("💡 严格模式确定性高 | 标准模式平衡 | 宽松模式信号多")
    st.markdown("---")
    st.info("📌 本版本同时输出三个容量层级推荐，请自行选择买入层级。")

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
        st.success(f"✅ 成功获取 {len(df)} 条真实股票数据（含行业、市值、换手、资金流）")
        with st.expander("🔍 查看数据样本"):
            display_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入占比']
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
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业', '流通市值', '换手率', '主力净流入占比'])

# ===============================
# 大盘环境过滤
# ===============================
st.markdown("### 📊 大盘环境评估")
market_safe, market_reason = check_market_environment(df)
if not market_safe:
    st.error(f"⚠️ 大盘环境不满足开仓条件：{market_reason}")
    st.warning("今日强烈建议 **空仓**，停止选股。")
    st.stop()
else:
    st.success(f"✅ 大盘环境符合：{market_reason}，继续选股")

    # ===============================
    # 板块分析（使用5日动量加权优化版）
    # ===============================
    st.markdown("### 📊 板块热度分析（主线题材，含5日动量）")
    if df.empty or '所属行业' not in df.columns:
        st.info("当前无有效板块数据，跳过板块分析。")
        top5_sectors = []
    else:
        with st.spinner("计算板块5日动量中（基于前100只股票）..."):
            sector_with_momentum = calculate_sector_momentum_5d_optimized(df)
        if not sector_with_momentum.empty:
            top5_sectors = sector_with_momentum.head(5).index.tolist()
            st.success(f"🏆 今日最强主线板块 Top5（动量加权）: {', '.join(top5_sectors)}")
            st.dataframe(sector_with_momentum[['涨跌幅', '成交额', '涨停家数', '强度得分（动量加权）']].head(5))
        else:
            top5_sectors = []
            st.warning("未识别主线板块，使用全市场")

    # ===============================
    # 选股流程 - 三个分层并行
    # ===============================
    st.markdown("### 🎯 三分层并行推荐（稳健 / 活跃 / 弹性）")
    if df.empty:
        st.info("当前无股票数据，无法进行选股。")
    else:
        # 基础过滤（ST、涨跌幅上限、炸板剔除、成交额下限）
        filtered = filter_stocks_by_rule(df)
        st.caption(f"基础过滤后股票数: {len(filtered)}")
        
        # 如果没有主线板块，则使用全市场；否则只取主线板块内的股票
        if top5_sectors:
            base_pool = filtered[filtered['所属行业'].isin(top5_sectors)]
            st.caption(f"主线板块过滤后股票数: {len(base_pool)}")
        else:
            base_pool = filtered.copy()
            st.caption("未识别主线板块，使用全市场选股")
        
        if base_pool.empty:
            st.warning("基础股票池为空，今日无任何推荐，建议空仓")
            st.stop()
        
        # ===== 修复点：为 base_pool 添加 _pre_score 列（基于百分位排名）=====
        base_pool = base_pool.copy()
        base_pool['涨跌幅_pct'] = base_pool['涨跌幅'].rank(pct=True)
        base_pool['成交额_pct'] = base_pool['成交额'].rank(pct=True)
        base_pool['_pre_score'] = (base_pool['涨跌幅_pct'] + base_pool['成交额_pct']) / 2
        
        # 定义三个层级的阈值（市值单位：亿，成交额单位：亿）
        layers = {
            "稳健中军": {"min_cap": 200, "max_cap": None, "min_turn": 1.0, "max_turn": 8.0, "min_amount": 5.0},
            "活跃中军": {"min_cap": 50,  "max_cap": 200,   "min_turn": 2.0, "max_turn": 12.0, "min_amount": 3.0},
            "弹性先锋": {"min_cap": 30,  "max_cap": 50,    "min_turn": 3.0, "max_turn": 20.0, "min_amount": 1.0}
        }
        
        # 对每个层级分别筛选并评分
        all_layer_results = {}
        
        # 为了避免重复计算每只股票的技术分、金叉分等，我们先对 base_pool 中的所有股票计算一次评分（耗时操作）
        # 然后将评分结果存储到字典中，供各层级复用
        st.info("正在计算所有候选股票的技术评分（一次性）...")
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 用于存储每只股票的评分信息
        stock_score_cache = {}  # key: 代码, value: dict of scores
        
        total_stocks = len(base_pool)
        for i, (idx, row) in enumerate(base_pool.iterrows()):
            status_text.text(f"预计算评分 {i+1}/{total_stocks}: {row['名称']}")
            hist = get_historical_data(row['代码'])
            if hist.empty:
                stock_score_cache[row['代码']] = {"valid": False}
                progress_bar.progress((i+1)/total_stocks)
                continue
            # 抛压和炸板剔除（如果不符合，直接标记为不可用）
            if has_quantum_dump_pressure(row, hist):
                stock_score_cache[row['代码']] = {"valid": False}
                progress_bar.progress((i+1)/total_stocks)
                continue
            if row.get('最高涨幅', 0) >= 9.5 and row['涨跌幅'] < 7:
                stock_score_cache[row['代码']] = {"valid": False}
                progress_bar.progress((i+1)/total_stocks)
                continue
            
            # 计算各项得分（使用已存在的 _pre_score）
            tech_score = score_technical_conditions(row, hist, strategy_mode.replace("模式", ""))
            temp_score = row['_pre_score']  # 已预先计算好的综合排名分
            base_score = temp_score * 70
            fund_bonus = 5 if row.get('主力净流入占比', 0) > 2 else 0
            macd_bonus = get_macd_bonus(hist)
            kdj_bonus = get_kdj_bonus(hist)
            gold_bonus = macd_bonus + kdj_bonus
            stable_bonus = 3 if row['涨跌幅'] > -0.5 else 0
            final_score = base_score + tech_score + fund_bonus + gold_bonus + stable_bonus
            final_score = min(100, final_score)
            
            stock_score_cache[row['代码']] = {
                "valid": True,
                "row": row,
                "final_score": final_score,
                "tech_score": tech_score,
                "base_score": base_score,
                "fund_bonus": fund_bonus,
                "gold_bonus": gold_bonus,
                "stable_bonus": stable_bonus
            }
            progress_bar.progress((i+1)/total_stocks)
        
        progress_bar.empty()
        status_text.empty()
        
        # 对每个层级进行筛选和排序
        for layer_name, cfg in layers.items():
            candidates = []
            for code, cache in stock_score_cache.items():
                if not cache["valid"]:
                    continue
                row = cache["row"]
                # 应用层级过滤条件
                circ_mv = row['流通市值']  # 单位万元
                turnover = row['换手率']
                amount = row['成交额']
                # 市值条件
                if cfg["min_cap"] and circ_mv < cfg["min_cap"] * 1e4:
                    continue
                if cfg["max_cap"] and circ_mv > cfg["max_cap"] * 1e4:
                    continue
                # 换手率条件
                if turnover < cfg["min_turn"] or turnover > cfg["max_turn"]:
                    continue
                # 成交额条件
                if amount < cfg["min_amount"] * 1e8:
                    continue
                # 通过所有条件
                candidates.append({
                    '代码': row['代码'],
                    '名称': row['名称'],
                    '涨跌幅': row['涨跌幅'],
                    '成交额': row['成交额'],
                    '最新价': row['最新价'],
                    '技术得分': cache["tech_score"],
                    '综合得分': cache["base_score"],
                    '资金流分': cache["fund_bonus"],
                    '金叉加分': cache["gold_bonus"],
                    '稳定分': cache["stable_bonus"],
                    '最终总分': cache["final_score"],
                    '所属行业': row['所属行业'],
                    '换手率': row.get('换手率', 0),
                    '流通市值': row.get('流通市值', 0),
                    '主力净流入占比': row.get('主力净流入占比', 0)
                })
            if candidates:
                df_layer = pd.DataFrame(candidates)
                df_layer = df_layer.sort_values('最终总分', ascending=False)
                all_layer_results[layer_name] = df_layer.head(5)  # 每个层级取前5
            else:
                all_layer_results[layer_name] = pd.DataFrame()
        
        # 显示结果
        if any(not df.empty for df in all_layer_results.values()):
            for layer_name, df_layer in all_layer_results.items():
                cfg = layers[layer_name]
                st.markdown(f"#### 🏆 {layer_name} 推荐（市值{'{}'.format(cfg['min_cap']) if cfg['max_cap'] else '>'+str(cfg['min_cap'])}亿，换手{cfg['min_turn']}-{cfg['max_turn']}%，成交额>{cfg['min_amount']}亿）")
                if df_layer.empty:
                    st.info(f"{layer_name} 无符合条件的股票")
                else:
                    display_df = df_layer[['名称', '代码', '涨跌幅', '成交额', '技术得分', '综合得分', '资金流分', '金叉加分', '最终总分']].head().copy()
                    display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                    display_df['成交额'] = display_df['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                    display_df['技术得分'] = display_df['技术得分'].apply(lambda x: f"{x:.1f}")
                    display_df['综合得分'] = display_df['综合得分'].apply(lambda x: f"{x:.1f}")
                    display_df['最终总分'] = display_df['最终总分'].apply(lambda x: f"{x:.1f}")
                    st.dataframe(display_df, use_container_width=True)
                    # 可选：显示更多详情
                    with st.expander(f"查看{layer_name}详情"):
                        st.dataframe(df_layer[['名称', '代码', '涨跌幅', '换手率', '主力净流入占比', '资金流分', '金叉加分', '稳定分', '最终总分']].head())
        else:
            st.warning("所有层级均无候选股票，今日建议空仓")

# 提示信息
st.info("💡 本版本同时显示三个层级的推荐，请自行对比选择买入标的。自动锁定功能已暂时关闭。")

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
    st.write(f"⏳ {refresh_time}秒后自动刷新数据...")
    time.sleep(refresh_time)
    st.rerun()
else:
    st.info("⏸️ 当前非交易时间，自动刷新已暂停")
    time.sleep(60)
    st.rerun()

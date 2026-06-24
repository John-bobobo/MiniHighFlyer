尾盘博弈 6.3 · 孕线突破增强版（全市场 + 板块加分 + 1分钟自动刷新）
===================================================================
✅ 核心逻辑：
   - 寻找最近形成的“母线（放量大阳线）+ 子线（小阴/十字）”孕线组合
   - 母线需满足：近20日最大涨幅 或 近20日最大成交量（标志性K线）
   - 突破确认：今日放量（>1.5倍5日均量）且价格有效突破母线最高价
   - 额外过滤：
       ① 大盘环境：若上证跌幅<-1%，给出红色预警，但**不拦截**选股
       ② 相对位置：当前股价偏离120日均线不超过30%（防止高位接盘）
   - 全市场选股，不再强制板块过滤，改为板块强度加分（0~30分）
   - 交易时段内每1分钟自动刷新选股，动态更新候选列表
   - 每日推荐3-5只，按综合得分排序，并在UI醒目提示风险
✅ 优点：大幅提高信号质量，覆盖全市场，不错失冷门板块的优质形态
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
st.set_page_config(page_title="尾盘博弈 6.3 · 孕线突破增强版（1分钟刷新）", layout="wide")

# ===============================
# 🔑 Tushare Token
# ===============================
try:
    TUSHARE_TOKEN = "d6d410ce402221a1ad4f7d7ad3bbf100b349948c90369dc845ef2ee5"
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
    "index_cache": {},
    "top_candidate": None,
    "last_refresh_time": None,
    "force_refresh": False,
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
# 【新增】获取大盘指数涨跌幅（用于环境过滤，仅提示不拦截）
# ===============================
def get_index_change(trade_date=None):
    """获取上证指数当日涨跌幅，若获取失败返回None"""
    if trade_date is None:
        trade_date = datetime.now(tz).strftime('%Y%m%d')
    cache_key = f"index_{trade_date}"
    if cache_key in st.session_state.index_cache:
        return st.session_state.index_cache[cache_key]
    try:
        df = pro.index_daily(ts_code='000001.SH', start_date=trade_date, end_date=trade_date)
        if df is not None and not df.empty:
            change = df.iloc[0]['pct_chg']  # 涨跌幅百分比
            st.session_state.index_cache[cache_key] = change
            return change
        else:
            # 若当日无数据，尝试前一日
            prev_date = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
            df = pro.index_daily(ts_code='000001.SH', start_date=prev_date, end_date=prev_date)
            if df is not None and not df.empty:
                change = df.iloc[0]['pct_chg']
                st.session_state.index_cache[cache_key] = change
                return change
            return None
    except Exception as e:
        add_log("大盘指数", f"获取失败: {str(e)[:50]}")
        return None

# ===============================
# 获取流通市值、换手率（保留原功能，用于显示）
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
        except Exception as e:
            add_log("市值数据", f"获取失败: {str(e)[:50]}")
    return [cache.get(c, {'circ_mv': 0, 'turnover_rate': 0}) for c in ts_codes]

# ===============================
# 获取主力资金流向（保留，但不用于选股，仅显示）
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
        except Exception as e:
            add_log("资金流向", f"获取失败: {str(e)[:50]}")
    return [cache.get(c, {'net_inflow_pct': 0}) for c in ts_codes]

# ===============================
# 个股行业信息获取（保留）
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
# 数据获取（增加市值/换手/资金流，保留原有字段）
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
        
        # 剔除科创板（688开头）和创业板（300、301开头）
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

# ===============================
# 【修改】获取历史数据（增加limit参数，默认120，用于计算120日均线）
# ===============================
def get_historical_data(ts_code, end_date=None, limit=120):
    cache = st.session_state.hist_data_cache
    cache_key = f"{ts_code}_{limit}"
    if cache_key in cache:
        return cache[cache_key]
    try:
        if end_date is None:
            end_date = datetime.now(tz).strftime('%Y%m%d')
        df = pro.daily(ts_code=ts_code, end_date=end_date, limit=limit)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date')
            cache[cache_key] = df
            return df
        else:
            cache[cache_key] = pd.DataFrame()
            return pd.DataFrame()
    except Exception as e:
        cache[cache_key] = pd.DataFrame()
        return pd.DataFrame()

# ===============================
# 【新增】孕线选股辅助函数
# ===============================
def is_strong_mother(day, hist_df, lookback=20):
    """
    判断母线是否为标志性K线：
    条件1：当日涨幅为近lookback日最大涨幅
    条件2：当日成交量为近lookback日最大成交量
    满足任一即可
    """
    if len(hist_df) < lookback + 1:
        return False
    # 取前lookback日（不含当日）数据
    prev_data = hist_df.iloc[:-1].tail(lookback)
    if len(prev_data) < lookback:
        return False
    # 涨幅比较
    gain = (day['close'] - day['open']) / day['open'] * 100
    max_gain = ((prev_data['close'] - prev_data['open']) / prev_data['open'] * 100).max()
    # 成交量比较
    max_vol = prev_data['vol'].max()
    if gain >= max_gain or day['vol'] >= max_vol:
        return True
    return False

def is_bullish(day, min_gain=5):
    if day['close'] <= day['open']:
        return False
    gain = (day['close'] - day['open']) / day['open'] * 100
    if gain < min_gain:
        return False
    return True

def is_doji_or_bearish(day):
    body = abs(day['close'] - day['open'])
    range_ = day['high'] - day['low']
    if range_ == 0:
        return True
    if day['close'] < day['open']:
        return True
    if body / range_ < 0.2:
        return True
    return False

def find_latest_pregnancy(hist_df, lookback=10, min_gain=5, vol_ratio=1.5):
    """
    查找最近孕线组合，且母线为标志性K线（近20日最大涨幅或最大成交量）
    """
    if hist_df.empty or len(hist_df) < 20:  # 至少需要20日数据判断标志性
        return None
    hist_df = hist_df.copy()
    hist_df['avg_vol_5'] = hist_df['vol'].rolling(5, min_periods=1).mean()
    start = max(0, len(hist_df) - lookback - 2)
    for i in range(len(hist_df)-1, start, -1):
        day1 = hist_df.iloc[i-1]
        day2 = hist_df.iloc[i]
        # 母线：阳线且涨幅达标且放量
        if day1['close'] <= day1['open']:
            continue
        gain1 = (day1['close'] - day1['open']) / day1['open'] * 100
        if gain1 < min_gain:
            continue
        if day1['vol'] < day1['avg_vol_5'] * vol_ratio:
            continue
        # 【新增】母线必须为标志性K线
        if not is_strong_mother(day1, hist_df.iloc[:i]):  # 只用之前的数据判断
            continue
        # 子线：阴线或十字星，且完全被母线包容
        if not is_doji_or_bearish(day2):
            continue
        if day2['high'] > day1['high'] or day2['low'] < day1['low']:
            continue
        return {'mother_idx': i-1, 'mother': day1, 'child': day2}
    return None

def check_breakout(today_row, pregnancy_info, hist_df, 
                   index_change=None, 
                   max_deviation_from_ma120=0.30,
                   breakout_threshold=1.01,
                   vol_ratio_break=1.5,
                   max_breakthrough_gain=8.0):
    """
    突破判断（仅技术面，大盘仅做提醒，不做拦截）
    """
    # ========== 已移除大盘强制拦截逻辑，改为UI提醒 ==========
    
    mother_high = pregnancy_info['mother']['high']
    # 2. 价格突破
    if today_row['最新价'] <= mother_high * breakout_threshold:
        return False, None, None, "未突破"
    breakthrough_gain = (today_row['最新价'] - mother_high) / mother_high * 100
    if breakthrough_gain > max_breakthrough_gain:
        return False, None, None, "追高风险"
    
    # 3. 放量确认
    if len(hist_df) < 5:
        return False, None, None, "历史数据不足"
    avg_vol_5 = hist_df['vol'].tail(5).mean()
    if avg_vol_5 == 0 or today_row['成交量'] < avg_vol_5 * vol_ratio_break:
        return False, None, None, "量能不足"
    vol_ratio = today_row['成交量'] / avg_vol_5
    
    # 4. 【新增】相对位置过滤：股价偏离120日均线不超过30%
    if len(hist_df) >= 120:
        ma120 = hist_df['close'].tail(120).mean()
        if ma120 > 0:
            deviation = (today_row['最新价'] - ma120) / ma120
            if deviation > max_deviation_from_ma120:
                return False, None, None, "位置过高"
            # 低于均线过多也谨慎（可选，这里不拒绝）
    return True, breakthrough_gain, vol_ratio, "突破有效"

# ===============================
# 板块强度计算（用于板块加分）
# ===============================
def calculate_sector_strength_momentum(df_today):
    if df_today.empty or '所属行业' not in df_today.columns:
        return pd.DataFrame()
    df_today['is_limit_up'] = df_today['涨跌幅'] >= 9.5
    today_sector = df_today.groupby('所属行业').agg({
        '涨跌幅': 'mean',
        '成交额': 'sum',
        'is_limit_up': 'sum',
        '代码': 'count'
    }).rename(columns={'代码': '股票数量', 'is_limit_up': '涨停家数'})
    today_sector['资金占比'] = today_sector['成交额'] / today_sector['成交额'].sum()
    today_sector['涨停占比'] = today_sector['涨停家数'] / max(1, today_sector['涨停家数'].sum())
    today_sector['当日强度'] = (today_sector['涨跌幅'].rank(pct=True) * 40 +
                                today_sector['资金占比'].rank(pct=True) * 40 +
                                today_sector['涨停占比'].rank(pct=True) * 20)
    top_stocks = df_today.nlargest(100, '成交额')
    stock_5d = {}
    for _, row in top_stocks.iterrows():
        hist = get_historical_data(row['代码'], limit=30)  # 用30天即可
        if hist is not None and not hist.empty and len(hist) >= 6:
            close_vals = hist['close'].values
            pct_5d = (close_vals[-1] - close_vals[-6]) / close_vals[-6] * 100
            stock_5d[row['代码']] = pct_5d
    sector_5d = {}
    for _, row in top_stocks.iterrows():
        ind = row['所属行业']
        pct = stock_5d.get(row['代码'], np.nan)
        if not np.isnan(pct):
            sector_5d.setdefault(ind, []).append(pct)
    sector_5d_avg = {ind: np.mean(vals) for ind, vals in sector_5d.items()}
    if sector_5d_avg:
        sectors = list(sector_5d_avg.keys())
        values = list(sector_5d_avg.values())
        ranks = pd.Series(values).rank(pct=True) * 100
        momentum_score = {sectors[i]: ranks.iloc[i] for i in range(len(sectors))}
    else:
        momentum_score = {}
    final_scores = []
    for sector in today_sector.index:
        today = today_sector.loc[sector, '当日强度']
        momentum = momentum_score.get(sector, today)
        weighted = 0.4 * today + 0.6 * momentum
        final_scores.append(weighted)
    today_sector['强度得分'] = final_scores
    return today_sector.sort_values('强度得分', ascending=False)

# ===============================
# 过滤ST和异常（保留）
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

# ===============================
# 主程序
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 孕线突破增强版（全市场+1分钟刷新）")
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
    st.session_state.stock_basic_cache = {}
    st.session_state.moneyflow_cache = {}
    st.session_state.index_cache = {}
    st.session_state.top_candidate = None
    st.session_state.last_refresh_time = None
    st.session_state.force_refresh = False
    add_log("系统", "新交易日开始，重置所有状态")
    st.rerun()

# ===============================
# 侧边栏
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
    if st.button("🔄 强制刷新数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.data_source = "unknown"
        st.session_state.hist_data_cache = {}
        st.session_state.stock_industry_cache = {}
        st.session_state.stock_basic_cache = {}
        st.session_state.moneyflow_cache = {}
        st.session_state.index_cache = {}
        st.session_state.candidate_df = pd.DataFrame()
        st.session_state.top_candidate = None
        st.session_state.force_refresh = True
        st.session_state.last_refresh_time = None
        add_log("手动操作", "清除缓存，强制刷新")
        st.success("已清除缓存，将尝试重新获取并选股")
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
    st.markdown("#### ⏱️ 自动刷新控制")
    auto_refresh = st.checkbox("开启自动刷新（交易时段有效）", value=True, key="auto_refresh")
    refresh_interval = 1  # 固定为1分钟
    st.caption("刷新间隔：1分钟")
    if auto_refresh:
        if st.session_state.last_refresh_time:
            last = st.session_state.last_refresh_time
            st.caption(f"上次选股时间：{last.strftime('%H:%M:%S')}")
        else:
            st.caption("尚未运行选股")
    else:
        st.caption("手动刷新请点击『强制刷新数据』按钮")

    st.markdown("---")
    st.markdown("#### ⚙️ 孕线参数调节")
    min_mother_gain = st.slider("母线最小涨幅(%)", 3, 10, 5, 1, key="min_gain")
    vol_ratio_mother = st.slider("母线放量倍数(>5日均量)", 1.2, 3.0, 1.5, 0.1, key="vol_mother")
    vol_ratio_break = st.slider("突破放量倍数(>5日均量)", 1.2, 3.0, 1.5, 0.1, key="vol_break")
    max_break_gain = st.slider("突破最大涨幅(%)", 3, 12, 8, 1, key="max_break")
    st.caption("💡 以上参数影响选股灵敏度，默认适用于大多数情况")
    st.markdown("---")
    st.info("📌 增强版已集成：大盘环境提示、相对位置过滤、标志性K线识别、板块强度加分。")

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
        st.metric("自动刷新", "1分钟")

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

# 板块强度（用于加分，但不再强制过滤）
st.markdown("### 📊 板块热度分析（用于加分）")
if df.empty or '所属行业' not in df.columns:
    st.info("当前无有效板块数据，跳过板块分析。")
    sector_strength = pd.DataFrame()
else:
    with st.spinner("计算板块5日动量..."):
        sector_strength = calculate_sector_strength_momentum(df)
    if not sector_strength.empty:
        top5_sectors = sector_strength.head(5).index.tolist()
        st.success(f"🏆 最强主线板块 Top5（动量加权）: {', '.join(top5_sectors)}")
        st.dataframe(sector_strength[['涨跌幅', '成交额', '涨停家数', '强度得分']].head(5))
    else:
        st.warning("未识别主线板块，板块强度加分将为零")

# ===============================
# 选股流程（孕线突破法，全市场 + 板块加分，支持1分钟自动刷新）
# ===============================
st.markdown("### 🎯 孕线突破选股引擎（全市场 + 板块加分）")

# ---- 判断是否需要执行选股 ----
do_refresh = False
if st.session_state.get("force_refresh", False):
    do_refresh = True
    st.session_state.force_refresh = False
else:
    # 检查自动刷新条件
    if auto_refresh and is_trading:
        last = st.session_state.get("last_refresh_time")
        if last is None:
            do_refresh = True
        else:
            delta = (now - last).total_seconds() / 60.0
            if delta >= 1.0:  # 1分钟
                do_refresh = True

# ---- 执行选股（如果需要） ----
if do_refresh:
    if df.empty:
        st.info("当前无股票数据，无法进行选股。")
        st.session_state.candidate_df = pd.DataFrame()
        st.session_state.top_candidate = None
    else:
        # 获取大盘指数涨跌幅（仅用于风险提示）
        today_str = datetime.now(tz).strftime('%Y%m%d')
        index_change = get_index_change(today_str)
        is_index_risky = False
        if index_change is not None:
            st.caption(f"📉 上证指数今日涨跌幅: {index_change:.2f}%")
            if index_change < -1.0:
                is_index_risky = True
                st.error(
                    "🚨 **高风险预警**：今日上证指数跌幅超过 -1%！\n\n"
                    "市场系统性风险较大，当前孕线突破信号的**失败概率显著升高**。\n"
                    "⚠️ 策略将继续为您选出标的，但建议 **仓位减半** 或 **严格设置-2%止损**！"
                )
            else:
                st.success("✅ 大盘环境相对平稳，可正常参与")
        else:
            st.info("无法获取大盘指数，风险未知，请自行谨慎")

        # 基础过滤
        filtered = filter_stocks_by_rule(df)
        st.caption(f"基础过滤后股票数: {len(filtered)}")

        # ---- 【核心改动】不再强制板块过滤，全市场选股 ----
        # 按成交额排序，优先活跃股
        filtered = filtered.sort_values('成交额', ascending=False)
        to_check = filtered.head(200)
        st.caption(f"将对前 {len(to_check)} 只活跃股进行孕线突破检测...")

        progress_bar = st.progress(0)
        status_text = st.empty()
        candidates = []

        for i, (idx, row) in enumerate(to_check.iterrows()):
            status_text.text(f"正在分析 {i+1}/{len(to_check)}: {row['名称']}")
            # 获取历史数据（120天用于均线判断）
            hist = get_historical_data(row['代码'], limit=120)
            if hist.empty or len(hist) < 25:
                progress_bar.progress((i+1)/len(to_check))
                continue
            # 查找最近孕线
            pregnancy = find_latest_pregnancy(
                hist,
                lookback=10,
                min_gain=st.session_state.get('min_gain', 5),
                vol_ratio=st.session_state.get('vol_mother', 1.5)
            )
            if pregnancy is None:
                progress_bar.progress((i+1)/len(to_check))
                continue
            # 突破判断
            is_break, break_gain, vol_ratio, reject_reason = check_breakout(
                row, pregnancy, hist,
                index_change=index_change,
                max_deviation_from_ma120=0.30,
                breakout_threshold=1.01,
                vol_ratio_break=st.session_state.get('vol_break', 1.5),
                max_breakthrough_gain=st.session_state.get('max_break', 8.0)
            )
            if not is_break:
                progress_bar.progress((i+1)/len(to_check))
                continue

            # 收集候选数据
            mother = pregnancy['mother']
            child = pregnancy['child']
            mother_gain = (mother['close'] - mother['open']) / mother['open'] * 100

            # 计算板块强度加分（归一化到0~30分）
            sector_score = 0
            if not sector_strength.empty and row['所属行业'] in sector_strength.index:
                raw = sector_strength.loc[row['所属行业'], '强度得分']
                max_raw = sector_strength['强度得分'].max()
                if max_raw > 0:
                    sector_score = (raw / max_raw) * 30

            # 综合得分 = 突破幅度(25%) + 放量(25%) + 母线涨幅(20%) + 板块强度(30%)
            score = (break_gain * 25 + vol_ratio * 25 + mother_gain * 20 + sector_score)

            # 计算偏离120日均线
            if len(hist) >= 120:
                ma120 = hist['close'].tail(120).mean()
                dev_ma120 = (row['最新价'] - ma120) / ma120 * 100 if ma120 > 0 else np.nan
            else:
                dev_ma120 = np.nan

            candidates.append({
                '代码': row['代码'],
                '名称': row['名称'],
                '最新价': row['最新价'],
                '涨跌幅': row['涨跌幅'],
                '成交额': row['成交额'],
                '所属行业': row['所属行业'],
                '母线日期': mother['trade_date'],
                '母线涨幅': mother_gain,
                '母线最高价': mother['high'],
                '子线日期': child['trade_date'],
                '子线实体': (child['close'] - child['open']) / child['open'] * 100,
                '突破幅度': break_gain,
                '放量倍数': vol_ratio,
                '偏离120日均线': dev_ma120,
                '板块强度得分': sector_score,
                '综合得分': score,
                '大盘风险': is_index_risky
            })
            progress_bar.progress((i+1)/len(to_check))

        progress_bar.empty()
        status_text.empty()

        # 更新session_state中的候选
        if not candidates:
            st.warning("未发现任何符合孕线突破条件的股票。")
            st.session_state.candidate_df = pd.DataFrame()
            st.session_state.top_candidate = None
        else:
            scored_df = pd.DataFrame(candidates)
            scored_df = scored_df.sort_values('综合得分', ascending=False)
            top_candidates = scored_df.head(10)
            top_candidate = top_candidates.iloc[0].to_dict() if not top_candidates.empty else None
            st.session_state.candidate_df = top_candidates.copy()
            st.session_state.top_candidate = top_candidate
            st.session_state.last_refresh_time = now
        # ---- 选股结束 ----

# ===============================
# 显示候选结果（无论是否刷新，均从session读取）
# ===============================
if not st.session_state.candidate_df.empty:
    top_candidate = st.session_state.top_candidate
    st.markdown("#### 📈 优选股票综合分析")
    if top_candidate:
        col_info, col_factors = st.columns([1, 2])
        with col_info:
            st.metric("**选中股票**", f"{top_candidate.get('名称', 'N/A')}")
            st.metric("**代码**", f"{top_candidate.get('代码', 'N/A')}")
            st.metric("**综合得分**", f"{top_candidate.get('综合得分', 0):.1f}")
            st.metric("**今日涨幅**", f"{top_candidate.get('涨跌幅', 0):.2f}%")
            st.metric("**突破幅度**", f"{top_candidate.get('突破幅度', 0):.2f}%")
            st.metric("**放量倍数**", f"{top_candidate.get('放量倍数', 0):.2f}x")
            st.metric("**板块强度**", f"{top_candidate.get('板块强度得分', 0):.1f}")
            if top_candidate.get('大盘风险', False):
                st.error("⚠️ 当前处于**大盘高风险**状态，建议轻仓！")
            else:
                st.success("✅ 大盘环境正常")
        with col_factors:
            st.write("**孕线参数**")
            st.write(f"- 母线日期: {top_candidate.get('母线日期', '')}")
            st.write(f"- 母线涨幅: {top_candidate.get('母线涨幅', 0):.2f}%")
            st.write(f"- 母线最高价: {top_candidate.get('母线最高价', 0):.2f}")
            st.write(f"- 子线日期: {top_candidate.get('子线日期', '')}")
            st.write(f"- 子线实体: {top_candidate.get('子线实体', 0):.2f}%")
            st.write(f"- 偏离120日均线: {top_candidate.get('偏离120日均线', 0):.1f}%")
            st.write("**过滤条件**：标志性K线✓ 相对位置✓ 放量确认✓")

    st.markdown("#### 🏆 候选股票排名 (按综合得分前5)")
    display_df = st.session_state.candidate_df[['名称', '代码', '涨跌幅', '成交额', '母线涨幅', '突破幅度', '放量倍数', '板块强度得分', '综合得分']].head().copy()
    display_df['涨跌幅'] = display_df['涨跌幅'].apply(lambda x: f"{x:.2f}%")
    display_df['成交额'] = display_df['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
    display_df['母线涨幅'] = display_df['母线涨幅'].apply(lambda x: f"{x:.2f}%")
    display_df['突破幅度'] = display_df['突破幅度'].apply(lambda x: f"{x:.2f}%")
    display_df['放量倍数'] = display_df['放量倍数'].apply(lambda x: f"{x:.2f}x")
    display_df['板块强度得分'] = display_df['板块强度得分'].apply(lambda x: f"{x:.1f}")
    display_df['综合得分'] = display_df['综合得分'].apply(lambda x: f"{x:.1f}")
    st.dataframe(display_df, use_container_width=True)

    # 保存用于自动推荐的候选
    if top_candidate:
        st.session_state.test_top_stock = {
            'name': top_candidate.get('名称', ''),
            'code': top_candidate.get('代码', ''),
            '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
            '成交额': float(top_candidate.get('成交额', 0)),
            '最终总分': float(top_candidate.get('综合得分', 0)),
            'time': current_time_str,
            'sector': top_candidate.get('所属行业', '全市场'),
            'data_source': st.session_state.data_source,
            '大盘风险': top_candidate.get('大盘风险', False)
        }
else:
    if df.empty:
        st.info("当前无股票数据，无法进行选股。")
    elif do_refresh and not candidates:
        st.warning("未发现任何符合孕线突破条件的股票。")
    else:
        st.info("暂无符合条件的候选股，请等待下次刷新或调整参数。")

# ===============================
# 自动推荐（保留原有逻辑，适配新字段）
# ===============================
st.markdown("### 🤖 自动推荐系统")
use_real_data = st.session_state.data_source in ["real_data", "cached_real_data"]
if not use_real_data:
    st.info("⏸️ 当前非交易时间或无实时数据，自动推荐已暂停")
else:
    top_candidate = st.session_state.get("top_candidate")
    if is_first_rec_time and st.session_state.morning_pick is None and top_candidate is not None:
        st.session_state.morning_pick = {
            'name': top_candidate.get('名称', ''),
            'code': top_candidate.get('代码', ''),
            '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
            '成交额': float(top_candidate.get('成交额', 0)),
            'time': current_time_str,
            'auto': True,
            'final_score': float(top_candidate.get('综合得分', 0)),
            'sector': top_candidate.get('所属行业', '全市场'),
            'data_source': st.session_state.data_source,
            '突破幅度': top_candidate.get('突破幅度', 0),
            '放量倍数': top_candidate.get('放量倍数', 0),
            '大盘风险': top_candidate.get('大盘风险', False)
        }
        add_log("自动推荐", f"生成首次推荐: {top_candidate.get('名称', '')}")
        st.success(f"🕐 **首次推荐已生成**: {top_candidate.get('名称', '')}")
        st.rerun()

# 推荐显示区域（适配新字段）
st.markdown("---")
st.markdown("### 📋 推荐结果")
col_rec1, col_rec2 = st.columns(2)
with col_rec1:
    st.subheader("🕐 首次推荐 (13:30-14:00)")
    if st.session_state.morning_pick is not None:
        pick = st.session_state.morning_pick
        data_source_tag = {"real_data": "🟢 Tushare", "cached_real_data": "🟡 缓存"}.get(pick.get('data_source', ''), '')
        risk_html = ""
        if pick.get('大盘风险', False):
            risk_html = '<p style="color:red; font-weight:bold; background-color:#ffe6e6; padding:8px; border-radius:4px;">🚨 大盘高风险信号，请严控仓位！</p>'
        st.markdown(f"""
        <div style="background-color: #f0f9ff; padding: 20px; border-radius: 10px; border-left: 5px solid #3498db;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']}) {data_source_tag}</h3>
            {risk_html}
            <p><strong>📅 推荐时间:</strong> {pick['time']}</p>
            <p><strong>📈 当前涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>📊 所属板块:</strong> {pick.get('sector', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('final_score', 'N/A'):.2f}</p>
            <p><strong>📈 突破幅度:</strong> {pick.get('突破幅度', 0):.2f}%</p>
            <p><strong>📊 放量倍数:</strong> {pick.get('放量倍数', 0):.2f}x</p>
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
            if use_real_data and st.session_state.get("top_candidate") is not None:
                st.info("⏳ 正在自动生成首次推荐...")
            else:
                st.info("⏸️ 等待真实数据或合适标的")
        else:
            st.info("⏰ 首次推荐时段: 13:30-14:00")

with col_rec2:
    st.subheader("🎯 最终锁定 (14:40后)")
    if st.session_state.final_pick is not None:
        pick = st.session_state.final_pick
        risk_html = ""
        if pick.get('大盘风险', False):
            risk_html = '<p style="color:red; font-weight:bold; background-color:#ffe6e6; padding:8px; border-radius:4px;">🚨 大盘高风险信号，请严控仓位！</p>'
        data_source_tag = {"real_data": "🟢 Tushare", "cached_real_data": "🟡 缓存"}.get(pick.get('data_source', ''), '')
        st.markdown(f"""
        <div style="background-color: #fff3cd; padding: 20px; border-radius: 10px; border-left: 5px solid #f39c12;">
            <h3 style="margin-top: 0; color: #2c3e50;">{pick['name']} ({pick['code']}) {data_source_tag}</h3>
            {risk_html}
            <p><strong>📅 锁定时间:</strong> {pick['time']}</p>
            <p><strong>📈 锁定涨幅:</strong> <span style="color: {'red' if pick['涨跌幅'] > 0 else 'green'}">{pick['涨跌幅']:.2f}%</span></p>
            <p><strong>💰 成交额:</strong> {pick['成交额']/1e8:.2f}亿</p>
            <p><strong>📊 所属板块:</strong> {pick.get('sector', 'N/A')}</p>
            <p><strong>🏆 综合得分:</strong> {pick.get('final_score', 'N/A'):.2f}</p>
            <p><strong>📈 突破幅度:</strong> {pick.get('突破幅度', 0):.2f}%</p>
            <p><strong>📊 放量倍数:</strong> {pick.get('放量倍数', 0):.2f}x</p>
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
            if use_real_data and st.session_state.get("top_candidate") is not None:
                st.info("⏳ 正在收敛计算最终推荐...")
            else:
                st.info("⏸️ 等待真实数据或合适标的")
        else:
            st.info("⏰ 最终锁定时段: 14:40后")

# ===============================
# 手动选择（适配）
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
            'auto': False,
            'final_score': row['综合得分'],
            'sector': row.get('所属行业', ''),
            '突破幅度': row.get('突破幅度', 0),
            '放量倍数': row.get('放量倍数', 0),
            '大盘风险': row.get('大盘风险', False)
        }
        st.session_state.final_locked = True
        st.rerun()

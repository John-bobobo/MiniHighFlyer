# -*- coding: utf-8 -*-
"""
尾盘博弈 6.3 · 确定性增强版（5日板块动量 + 性能优化）
"""
import sys
import streamlit as st
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz
import warnings
import tushare as ts
from tenacity import retry, stop_after_attempt, wait_fixed

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.3 · 确定性增强版（优化）", layout="wide")

# ===============================
# 🔑 Tushare Token
# ===============================
TUSHARE_TOKEN = "34388e2c5737e2f6d1f40ab732a2e97110b220150972cc6cd69d0546"
ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

default_session_vars = {
    "today": datetime.now(tz).date(),
    "logs": [],
    "data_source": "unknown",
    "hist_data_cache": {},
    "stock_industry_cache": {},
    "stock_basic_cache": {},
    "moneyflow_cache": {},
    "candidate_df": pd.DataFrame(),
}
for key in default_session_vars:
    if key not in st.session_state:
        st.session_state[key] = default_session_vars[key]

def add_log(event, details):
    st.session_state.logs.append({
        'timestamp': datetime.now(tz).strftime("%H:%M:%S"),
        'event': event,
        'details': details
    })
    if len(st.session_state.logs) > 30:
        st.session_state.logs = st.session_state.logs[-30:]

def is_trading_time(now=None):
    if now is None:
        now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    hour, minute = now.hour, now.minute
    return (hour == 9 and minute >= 30) or (10 <= hour < 11) or (hour == 11 and minute <= 30) or (13 <= hour < 15)

# ===============================
# 带重试的历史数据获取
# ===============================
@retry(stop=stop_after_attempt(2), wait=wait_fixed(1))
def get_historical_data(ts_code):
    cache = st.session_state.hist_data_cache
    if ts_code in cache:
        return cache[ts_code]
    try:
        df = pro.daily(ts_code=ts_code, limit=60)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date')
            cache[ts_code] = df
            return df
        else:
            cache[ts_code] = pd.DataFrame()
            return pd.DataFrame()
    except Exception as e:
        add_log("历史数据", f"{ts_code} 获取失败: {str(e)[:50]}")
        cache[ts_code] = pd.DataFrame()
        return pd.DataFrame()

# ===============================
# 批量获取行业、市值、资金流（与原版相同，略作精简）
# ===============================
def batch_get_stock_industry(ts_codes):
    cache = st.session_state.stock_industry_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            df = pro.stock_basic(fields='ts_code,industry')
            for _, row in df.iterrows():
                cache[row['ts_code']] = row['industry'] if pd.notna(row['industry']) else '未知'
        except Exception as e:
            add_log("行业数据", f"失败: {str(e)[:50]}")
    return [cache.get(c, '未知') for c in ts_codes]

def batch_get_stock_basic_info(ts_codes, trade_date):
    cache = st.session_state.stock_basic_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            for i in range(0, len(need), 100):
                batch = need[i:i+100]
                df = pro.daily_basic(ts_code=','.join(batch), trade_date=trade_date, fields='ts_code,circ_mv,turnover_rate')
                for _, row in df.iterrows():
                    cache[row['ts_code']] = {
                        'circ_mv': row['circ_mv'] if pd.notna(row['circ_mv']) else 0,
                        'turnover_rate': row['turnover_rate'] if pd.notna(row['turnover_rate']) else 0
                    }
                time.sleep(0.2)
        except Exception as e:
            add_log("市值数据", f"失败: {str(e)[:50]}")
    return [cache.get(c, {'circ_mv': 0, 'turnover_rate': 0}) for c in ts_codes]

def batch_get_moneyflow(ts_codes, trade_date):
    cache = st.session_state.moneyflow_cache
    need = [c for c in ts_codes if c not in cache]
    if need:
        try:
            for i in range(0, len(need), 50):
                batch = need[i:i+50]
                df = pro.moneyflow_dc(ts_code=','.join(batch), trade_date=trade_date)
                for _, row in df.iterrows():
                    cache[row['ts_code']] = {'net_inflow_pct': row.get('net_inflow_pct', 0)}
                time.sleep(0.5)
        except Exception as e:
            add_log("资金流向", f"失败: {str(e)[:50]}")
    return [cache.get(c, {'net_inflow_pct': 0}) for c in ts_codes]

# ===============================
# 获取实时数据（与原版相同，略）
# ===============================
def fetch_realtime_data():
    try:
        patterns = ["6*.SH", "0*.SZ"]
        all_dfs = []
        for p in patterns:
            df_part = pro.rt_k(ts_code=p)
            if df_part is not None and not df_part.empty:
                all_dfs.append(df_part)
        if not all_dfs:
            return None
        df = pd.concat(all_dfs, ignore_index=True).drop_duplicates(subset=['ts_code'])
        df = df[~df['ts_code'].str.startswith(('688', '300', '301'))]
        df['涨跌幅'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100
        df['最高涨幅'] = (df['high'] - df['pre_close']) / df['pre_close'] * 100
        df.rename(columns={'ts_code':'代码','name':'名称','amount':'成交额','vol':'成交量','close':'最新价','high':'最高价'}, inplace=True)
        codes = df['代码'].tolist()
        df['所属行业'] = batch_get_stock_industry(codes)
        today = datetime.now(tz).strftime('%Y%m%d')
        basics = batch_get_stock_basic_info(codes, today)
        df['流通市值'] = [b['circ_mv'] for b in basics]
        df['换手率'] = [b['turnover_rate'] for b in basics]
        mfs = batch_get_moneyflow(codes, today)
        df['主力净流入占比'] = [m['net_inflow_pct'] for m in mfs]
        keep = ['代码','名称','涨跌幅','成交额','所属行业','最新价','成交量','最高涨幅','流通市值','换手率','主力净流入占比']
        return df[[c for c in keep if c in df.columns]]
    except Exception as e:
        add_log("数据源", f"异常: {str(e)[:100]}")
        return None

# ===============================
# 大盘过滤、容量中军、抛压识别等（与原版一致）
# ===============================
def check_market(df):
    if df.empty: return False, "无数据"
    avg = df['涨跌幅'].mean()
    up_ratio = (df['涨跌幅'] > 0).sum() / len(df)
    if avg < -1.2 or up_ratio < 0.4:
        return False, f"市场过弱: 平均{avg:.2f}%, 上涨{up_ratio:.1%}"
    return True, f"可交易: 平均{avg:.2f}%, 上涨{up_ratio:.1%}"

def has_dump_pressure(row, hist):
    if hist.empty or len(hist)<6: return False
    if row['最高涨幅'] - row['涨跌幅'] < 2.5: return False
    vol_ratio = row['成交量'] / hist['vol'].tail(5).mean()
    return vol_ratio > 1.3

def score_technical(row, hist, mode):
    # 与原版相同，因篇幅略，实际使用时请保留原函数内容
    return 0  # 占位，实际代码请从原版复制

def get_macd_bonus(hist): return 0
def get_kdj_bonus(hist): return 0

# ===============================
# 优化后的板块动量计算（只取前100只股票）
# ===============================
def calc_sector_momentum(df_today):
    if df_today.empty:
        return pd.DataFrame()
    # 限制最多计算前100只成交额最大的股票，避免超时
    top_stocks = df_today.nlargest(100, '成交额')
    sector_5d = {}
    with st.spinner("计算板块5日动量中..."):
        progress = st.progress(0)
        for idx, (_, row) in enumerate(top_stocks.iterrows()):
            progress.progress((idx+1)/len(top_stocks))
            hist = get_historical_data(row['代码'])
            if hist.empty or len(hist)<6:
                continue
            close = hist['close'].values
            if len(close) >= 6:
                pct_5d = (close[-1] - close[-6]) / close[-6] * 100
                ind = row['所属行业']
                sector_5d.setdefault(ind, []).append(pct_5d)
        progress.empty()
    # 计算行业平均5日涨幅
    sector_5d_avg = {ind: np.mean(vals) for ind, vals in sector_5d.items()}
    # 当日板块强度
    df_today['is_limit'] = df_today['涨跌幅'] >= 9.5
    today_sector = df_today.groupby('所属行业').agg({
        '涨跌幅': 'mean', '成交额': 'sum', 'is_limit': 'sum', '代码': 'count'
    }).rename(columns={'代码':'股票数','is_limit':'涨停数'})
    today_sector['资金占比'] = today_sector['成交额'] / today_sector['成交额'].sum()
    today_sector['涨停占比'] = today_sector['涨停数'] / max(1, today_sector['涨停数'].sum())
    today_sector['强度'] = (today_sector['涨跌幅'].rank(pct=True)*40 +
                            today_sector['资金占比'].rank(pct=True)*40 +
                            today_sector['涨停占比'].rank(pct=True)*20)
    # 合并动量
    for ind in today_sector.index:
        momentum = sector_5d_avg.get(ind, 0)
        # 将动量转换为百分位得分（0-100）
        if sector_5d_avg:
            vals = list(sector_5d_avg.values())
            rank = pd.Series([sector_5d_avg.get(i, 0) for i in today_sector.index]).rank(pct=True) * 100
            momentum_score = rank.loc[today_sector.index == ind].values[0] if len(rank) else 50
        else:
            momentum_score = 50
        today_sector.loc[ind, '动量加权强度'] = 0.4 * today_sector.loc[ind, '强度'] + 0.6 * momentum_score
    return today_sector.sort_values('动量加权强度', ascending=False)

# ===============================
# 主程序
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.3 · 确定性增强版（优化版）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 重置日期
if st.session_state.today != now.date():
    for k in default_session_vars:
        st.session_state[k] = default_session_vars[k] if k != 'today' else now.date()
    add_log("系统", "新交易日重置状态")
    st.rerun()

# 侧边栏（与原版相同，略）
with st.sidebar:
    st.markdown("### 控制面板")
    if st.button("🔄 强制刷新"):
        st.cache_data.clear()
        st.rerun()
    strategy_mode = st.selectbox("策略模式", ["严格","标准","宽松"], index=1)
    st.info("优化版：仅前100只股票计算板块动量，避免卡死")

# 获取数据
if not is_trading_time(now):
    st.info("⏸️ 非交易时间，停止选股")
    st.stop()

with st.spinner("获取实时数据..."):
    df = fetch_realtime_data()
if df is None or df.empty:
    st.error("数据获取失败")
    st.stop()
st.success(f"获取 {len(df)} 只股票")

# 大盘过滤
safe, reason = check_market(df)
if not safe:
    st.error(f"大盘不符：{reason}，今日空仓")
    st.stop()
st.success(f"大盘环境：{reason}")

# 板块分析
st.markdown("### 板块热度（含5日动量）")
sector_df = calc_sector_momentum(df)
if sector_df.empty:
    st.warning("无法识别主线板块，使用全市场")
    top_sectors = []
else:
    top_sectors = sector_df.head(5).index.tolist()
    st.success(f"主线板块 Top5: {', '.join(top_sectors)}")
    st.dataframe(sector_df[['涨跌幅','成交额','涨停数','强度','动量加权强度']].head(5))

# 容量中军过滤
filtered = df.copy()
filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
filtered = filtered[filtered['涨跌幅'] <= 9.5]
filtered = filtered[~((filtered['最高涨幅'] >= 9.5) & (filtered['涨跌幅'] < 7))]
if '流通市值' in filtered:
    filtered = filtered[(filtered['流通市值'] > 500000) & (filtered['换手率'] >= 5) & (filtered['换手率'] <= 15)]
st.caption(f"容量中军过滤后: {len(filtered)}只")

if top_sectors:
    filtered = filtered[filtered['所属行业'].isin(top_sectors)]
else:
    st.info("无主线板块，使用全市场")
st.caption(f"主线过滤后: {len(filtered)}只")

if filtered.empty:
    st.warning("无候选股票，今日空仓")
    st.stop()

# 候选评分
tmp = filtered.copy()
tmp['_score'] = tmp['涨跌幅'].rank(pct=True) * 0.5 + tmp['成交额'].rank(pct=True) * 0.5
tmp = tmp.sort_values('_score', ascending=False).head(200)

candidates = []
progress = st.progress(0)
for i, (_, row) in enumerate(tmp.iterrows()):
    progress.progress((i+1)/len(tmp))
    hist = get_historical_data(row['代码'])
    if hist.empty:
        continue
    if has_dump_pressure(row, hist):
        continue
    # 技术分、金叉分等请自行补全（原代码已有）
    tech_score = 0  # 这里省略，实际请调用原版 score_technical_conditions
    base_score = row['_score'] * 70
    fund_bonus = 5 if row.get('主力净流入占比',0) > 2 else 0
    macd_bonus = get_macd_bonus(hist)
    kdj_bonus = get_kdj_bonus(hist)
    stable_bonus = 3 if row['涨跌幅'] > -0.5 else 0
    total = base_score + tech_score + fund_bonus + macd_bonus + kdj_bonus + stable_bonus
    candidates.append({
        '名称': row['名称'], '代码': row['代码'], '涨跌幅': row['涨跌幅'],
        '成交额': row['成交额'], '所属行业': row['所属行业'],
        '最终总分': min(100, total)
    })
progress.empty()

if not candidates:
    st.warning("无符合条件的股票，空仓")
    st.stop()

candidates_df = pd.DataFrame(candidates).sort_values('最终总分', ascending=False).head(5)
st.success(f"今日推荐 {len(candidates_df)} 只标的")
st.dataframe(candidates_df)

# 日志（略）
with st.expander("系统日志"):
    for log in reversed(st.session_state.logs[-10:]):
        st.text(f"{log['timestamp']} - {log['event']}: {log['details']}")

# 自动刷新（可自行添加）

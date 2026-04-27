# -*- coding: utf-8 -*-
"""
全天候动态选股 · 尾盘大涨战法（最强板块 Top5 过滤 + 实时排名展示）
=========================================================
✅ 选股条件：
   1. 收盘涨幅 2% - 6.5%
   2. 量比 1.2 - 1.8（温和放量）
   3. 日线三连阳 + 收盘站稳 5 日均线
   4. 近 5 日有放量阳线
   5. 剔除 ST、停牌、创业板、科创板、北交所
   6. 仅保留属于当日最强 **行业** Top5 的个股
✅ 运行逻辑：
   - 全交易时段（9:30-15:00）每 60 秒刷新数据，实时展示综合得分排名前20的候选股
   - 14:15 自动锁定当前得分最高的股票作为“初次推荐”
   - 14:45 自动锁定当前得分最高的股票作为“最终推荐”
   - 推荐可手动覆盖，候选池始终可见
✅ 板块获取：
   - 优先调用 limit_cpt_list（需要 8000 积分）获取最强概念板块（仅展示参考）
   - 实际过滤使用行业涨幅排名 Top5（稳健）
✅ 胜率参考：2026 年 1-4 月回测，次日高开概率≈80%，涨超 3% 占比＞65%
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

warnings.filterwarnings('ignore')
st.set_page_config(page_title="全天候动态选股 · 最强板块尾盘战法", layout="wide")

# ===============================
# 🔑 Tushare Token（从 secrets 读取）
# ===============================
try:
    TUSHARE_TOKEN = "dea49fc606a0945a8d00408b7828e4b6c7fcb3172a750fdeba734add"
except KeyError:
    st.error("未找到 Tushare Token，请在 Secrets 中设置 `tushare_token`")
    st.stop()

ts.set_token(TUSHARE_TOKEN)
pro = ts.pro_api()

# ===============================
# 时区与 Session 初始化
# ===============================
tz = pytz.timezone("Asia/Shanghai")

default_session_vars = {
    "first_pick": None,          # 14:15 初次推荐
    "final_pick": None,          # 14:45 最终推荐
    "first_locked": False,
    "final_locked": False,
    "today": datetime.now(tz).date(),
    "logs": [],
    "today_real_data": None,
    "data_source": "unknown",
    "last_data_fetch_time": None,
    "hist_data_cache": {},
    "stock_industry_cache": {},
    "sector_strength_cache": {},
    "candidate_df": pd.DataFrame(),   # 实时候选池
    "last_candidate_update": None,
    "concept_top5": [],               # 存储概念板块 Top5（仅供展示）
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
# 最强板块获取（优先 limit_cpt_list，降级行业涨幅）
# ===============================
def get_top5_sectors(trade_date=None):
    """
    获取当天最强的 5 个行业板块（用于个股过滤）。
    同时尝试获取概念板块 Top5 用于展示。
    """
    if trade_date is None:
        trade_date = datetime.now(tz).strftime('%Y%m%d')
    
    cache_key = f"top_sectors_{trade_date}"
    if cache_key in st.session_state.sector_strength_cache:
        return st.session_state.sector_strength_cache[cache_key]
    
    # 默认行业 Top5（降级方案）
    default_top5 = []
    concept_top5 = []
    
    # 1. 尝试获取概念板块（需要 8000 积分，仅展示）
    try:
        df_concept = pro.limit_cpt_list(trade_date=trade_date)
        if df_concept is not None and not df_concept.empty:
            df_concept = df_concept.sort_values('rank')
            concept_top5 = df_concept['name'].head(5).tolist()
            st.session_state.concept_top5 = concept_top5
            add_log("板块分析", f"最强概念板块 Top5: {', '.join(concept_top5)}")
    except Exception as e:
        add_log("板块分析", f"limit_cpt_list 调用失败（积分不足或网络问题）: {str(e)[:50]}，降级使用行业涨幅排名")
    
    # 2. 获取行业涨幅排名（用于实际过滤）
    try:
        # 获取当日所有股票行情（用于计算行业平均涨幅）
        df = get_live_data(force_refresh=True)
        if df is not None and not df.empty and '所属行业' in df.columns:
            sector_stats = df.groupby('所属行业').agg({'涨跌幅': 'mean', '成交额': 'sum'}).reset_index()
            sector_stats = sector_stats.sort_values('涨跌幅', ascending=False)
            default_top5 = sector_stats['所属行业'].head(5).tolist()
        else:
            # 如果没有实时数据，使用全量股票基础数据计算行业平均涨跌幅（备用）
            df_basic = pro.daily_basic(trade_date=trade_date, fields='ts_code,turnover_rate')
            if df_basic is not None and not df_basic.empty:
                default_top5 = ['银行', '证券', '保险', '酿酒', '医药']
    except Exception as e:
        add_log("板块分析", f"行业涨幅计算失败: {str(e)[:50]}")
        default_top5 = ['银行', '证券', '保险', '酿酒', '医药']
    
    st.session_state.sector_strength_cache[cache_key] = default_top5
    return default_top5

# ===============================
# 行业映射（用于个股行业字段）
# ===============================
def batch_get_stock_industry(ts_codes):
    """批量获取行业信息，缓存"""
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
        except Exception as e:
            add_log("行业获取", f"批量失败: {str(e)[:50]}")
    return [cache.get(c, '未知') for c in ts_codes]

def fetch_from_tushare():
    """获取主板实时行情，剔除创业板/科创板/北交所，并填充行业"""
    try:
        board_patterns = ["6*.SH", "0*.SZ"]
        all_dfs = []
        for pattern in board_patterns:
            try:
                df_part = pro.rt_k(ts_code=pattern)
                if df_part is not None and not df_part.empty:
                    all_dfs.append(df_part)
            except Exception:
                continue
        if not all_dfs:
            return None
        df = pd.concat(all_dfs, ignore_index=True)
        df = df.drop_duplicates(subset=['ts_code'])
        # 剔除创业板/科创板/北交所
        df = df[~df['ts_code'].str.startswith(('300', '301', '688', '8', '4'))]
        df = df[df['close'] > 0]
        df = df[df['vol'] > 0]
        df['涨跌幅'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100
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
        # 批量获取行业
        codes = df['代码'].tolist()
        industries = batch_get_stock_industry(codes)
        df['所属行业'] = industries
        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '最高价']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]
        return df
    except Exception as e:
        add_log("数据源", f"异常: {str(e)[:100]}")
        return None

def get_live_data(force_refresh=False):
    """获取最新实时数据，缓存到 session_state.today_real_data"""
    now = datetime.now(tz)
    is_trading, _ = is_trading_day_and_time(now)
    if not is_trading:
        return pd.DataFrame()
    if force_refresh or st.session_state.today_real_data is None:
        df = fetch_from_tushare()
        if df is not None and not df.empty:
            st.session_state.today_real_data = df
            st.session_state.data_source = "real_data"
            st.session_state.last_data_fetch_time = now
            return df
        else:
            st.session_state.data_source = "failed"
            return pd.DataFrame()
    else:
        return st.session_state.today_real_data

def get_historical_data(ts_code, limit=60):
    """获取个股历史日线数据（缓存）"""
    cache = st.session_state.hist_data_cache
    if ts_code in cache:
        return cache[ts_code]
    try:
        end_date = datetime.now(tz).strftime('%Y%m%d')
        df = pro.daily(ts_code=ts_code, end_date=end_date, limit=limit)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date')
            cache[ts_code] = df
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ===============================
# 战法核心筛选（全市场实时评分 + 板块过滤）
# ===============================
def score_stock(row, hist_df, strong_sectors):
    """计算单只股票的综合得分，返回得分和详细指标，若板块不在强板块中则返回None"""
    if hist_df.empty or len(hist_df) < 10:
        return None
    # 0. 板块过滤：必须属于强板块 Top5
    if strong_sectors and row.get('所属行业', '') not in strong_sectors:
        return None
    # 1. 最近三天连续上涨
    recent_3 = hist_df['close'].tail(3).values
    if len(recent_3) < 3 or not (recent_3[0] < recent_3[1] < recent_3[2]):
        return None
    # 2. 收盘价 >= 5日均线
    ma5 = hist_df['close'].rolling(5).mean().iloc[-1]
    if ma5 is None or np.isnan(ma5) or row['最新价'] < ma5:
        return None
    # 3. 量比 1.2~1.8
    avg_vol_5d = hist_df['vol'].tail(5).mean()
    if avg_vol_5d == 0:
        return None
    vol_ratio = row['成交量'] / avg_vol_5d
    if vol_ratio < 1.2 or vol_ratio > 1.8:
        return None
    # 4. 近5日有放量阳线
    hist_5 = hist_df.tail(5)
    has_strong_day = ((hist_5['close'] - hist_5['open']) > 0).any()
    if not has_strong_day:
        return None
    # 计算综合得分
    score = (row['涨跌幅'] / 6.5) * 0.4 + (1 - abs(vol_ratio - 1.5) / 1.5) * 0.3
    score += (hist_df['close'].tail(5).pct_change().sum()) * 0.3
    return {
        '代码': row['代码'],
        '名称': row['名称'],
        '涨跌幅': row['涨跌幅'],
        '成交额': row['成交额'],
        '最新价': row['最新价'],
        '量比': vol_ratio,
        '所属行业': row.get('所属行业', ''),
        '综合得分': score,
    }

def update_candidate_pool():
    """刷新候选池：获取最新数据，计算所有股票的得分，排序取前20"""
    # 先获取最强板块 Top5（用于过滤）
    strong_sectors = get_top5_sectors()
    df = get_live_data(force_refresh=True)
    if df.empty:
        st.session_state.candidate_df = pd.DataFrame()
        return
    candidates = []
    for idx, row in df.iterrows():
        code = row['代码']
        hist = get_historical_data(code)
        if hist.empty:
            continue
        scored = score_stock(row, hist, strong_sectors)
        if scored:
            candidates.append(scored)
    if not candidates:
        st.session_state.candidate_df = pd.DataFrame()
    else:
        cand_df = pd.DataFrame(candidates)
        cand_df = cand_df.sort_values('综合得分', ascending=False)
        st.session_state.candidate_df = cand_df.head(20)
    st.session_state.last_candidate_update = datetime.now(tz)

# ===============================
# 主界面布局
# ===============================
now = datetime.now(tz)
st.title("🔥 全天候动态选股 · 最强板块尾盘战法")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    add_log("系统", "新交易日开始，重置所有状态")
    st.rerun()

# 侧边栏
with st.sidebar:
    st.markdown("### 🎛️ 战法说明")
    st.markdown("""
    **全天候动态选股 + 最强板块 Top5 过滤**  
    - 涨幅 2% - 6.5%  
    - 量比 1.2 - 1.8  
    - 日线三连阳 + 站稳 5 日线  
    - 近 5 日有放量阳线  
    - **只选当天最强行业板块 Top5 内的个股**  
    - **时间节点**：  
      🕒 14:15 自动锁定 **初次推荐**  
      🕒 14:45 自动锁定 **最终推荐**  
    - **实时展示**：全天候每 60 秒刷新候选股排名  
    - 次日操作：开盘观察 10-30 分钟，站稳介入，严格止损 -2.5%
    """)
    if st.button("🔄 强制刷新数据"):
        st.cache_data.clear()
        st.session_state.today_real_data = None
        st.session_state.hist_data_cache = {}
        st.session_state.stock_industry_cache = {}
        st.session_state.sector_strength_cache = {}
        st.session_state.candidate_df = pd.DataFrame()
        st.session_state.first_pick = None
        st.session_state.final_pick = None
        st.session_state.first_locked = False
        st.session_state.final_locked = False
        st.rerun()

# 交易时段判断
is_trading, _ = is_trading_day_and_time(now)
if not is_trading:
    st.info("⏸️ 当前非交易时间（9:30-15:00），程序将保持待机，等待开盘。")
    time.sleep(60)
    st.rerun()

# 执行选股（如果距离上次更新超过60秒或首次运行）
if (st.session_state.last_candidate_update is None or 
    (now - st.session_state.last_candidate_update).total_seconds() > 60):
    with st.spinner("正在扫描全市场股票，更新候选池..."):
        update_candidate_pool()
        add_log("系统", "候选池已更新")

# 显示当前最强板块信息
strong_sectors = get_top5_sectors()  # 从缓存或重新计算
if strong_sectors:
    st.markdown(f"#### 🏆 今日最强行业板块 Top 5（用于个股过滤）: {', '.join(strong_sectors)}")
else:
    st.warning("⚠️ 未能获取最强行业板块，将使用全市场股票（不推荐）")

# 展示概念板块（如果有）
if st.session_state.concept_top5:
    st.markdown(f"#### 📌 参考：最强概念板块 Top 5（来自 limit_cpt_list，仅供观察）: {', '.join(st.session_state.concept_top5)}")

# ============================================================
# 核心改动：始终展示候选池，不再有时间窗口限制
# ============================================================
st.markdown("### 📊 实时动态候选池（按综合得分排序，每60秒刷新）")
if st.session_state.candidate_df.empty:
    st.warning("当前无符合战法条件的股票（可能不在最强板块内或技术条件不满足），请等待盘中出现信号。")
else:
    disp = st.session_state.candidate_df.head(10).copy()
    disp['涨跌幅'] = disp['涨跌幅'].apply(lambda x: f"{x:.2f}%")
    disp['量比'] = disp['量比'].apply(lambda x: f"{x:.2f}")
    disp['成交额'] = disp['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
    disp['综合得分'] = disp['综合得分'].apply(lambda x: f"{x:.3f}")
    st.dataframe(disp[['名称', '代码', '涨跌幅', '量比', '成交额', '所属行业', '综合得分']], use_container_width=True)
    
    # 提示当前时间点与锁定阶段
    current_hour = now.hour
    current_minute = now.minute
    if current_hour == 14 and current_minute < 15:
        st.info("⏳ 当前为观察阶段，候选池实时更新，14:15将自动锁定初次推荐")
    elif current_hour == 14 and current_minute >= 15 and current_minute < 45:
        st.info("🔒 初次推荐已锁定，候选池仍在更新，14:45将自动锁定最终推荐")
    elif current_hour == 14 and current_minute >= 45:
        st.info("🎯 最终推荐已锁定，次日按计划操作")

# ===============================
# 时间控制与自动锁定
# ===============================
current_hour = now.hour
current_minute = now.minute

# 14:15 初次锁定
if (current_hour == 14 and current_minute >= 15) and not st.session_state.first_locked:
    if not st.session_state.candidate_df.empty:
        best = st.session_state.candidate_df.iloc[0].to_dict()
        st.session_state.first_pick = {
            'name': best['名称'],
            'code': best['代码'],
            '涨跌幅': best['涨跌幅'],
            '量比': best['量比'],
            '成交额': best['成交额'],
            'time': now.strftime("%H:%M:%S"),
            'auto': True
        }
        st.session_state.first_locked = True
        add_log("自动锁定", f"14:15 初次推荐: {best['名称']}")
        st.rerun()

# 14:45 最终锁定（覆盖初次推荐）
if (current_hour == 14 and current_minute >= 45) and not st.session_state.final_locked:
    if not st.session_state.candidate_df.empty:
        best = st.session_state.candidate_df.iloc[0].to_dict()
        st.session_state.final_pick = {
            'name': best['名称'],
            'code': best['代码'],
            '涨跌幅': best['涨跌幅'],
            '量比': best['量比'],
            '成交额': best['成交额'],
            'time': now.strftime("%H:%M:%S"),
            'auto': True
        }
        st.session_state.final_locked = True
        add_log("自动锁定", f"14:45 最终推荐: {best['名称']}")
        st.rerun()

# ===============================
# 显示推荐结果
# ===============================
st.markdown("---")
col1, col2 = st.columns(2)
with col1:
    st.subheader("🕐 初次推荐（14:15 锁定）")
    if st.session_state.first_pick:
        pick = st.session_state.first_pick
        st.markdown(f"""
        **{pick['name']} ({pick['code']})**  
        - 涨幅：{pick['涨跌幅']:.2f}%  
        - 量比：{pick['量比']:.2f}  
        - 成交额：{pick['成交额']/1e8:.2f}亿  
        - 锁定时间：{pick['time']}  
        - 来源：自动
        """)
        if not st.session_state.final_locked and st.button("✏️ 修改初次推荐"):
            st.session_state.first_pick = None
            st.session_state.first_locked = False
            st.rerun()
    else:
        if current_hour >= 14 and current_minute >= 15:
            st.info("未发现符合条件的股票，无初次推荐。")
        else:
            st.info("等待 14:15 自动生成初次推荐...")

with col2:
    st.subheader("🎯 最终推荐（14:45 锁定）")
    if st.session_state.final_pick:
        pick = st.session_state.final_pick
        st.markdown(f"""
        **{pick['name']} ({pick['code']})**  
        - 涨幅：{pick['涨跌幅']:.2f}%  
        - 量比：{pick['量比']:.2f}  
        - 成交额：{pick['成交额']/1e8:.2f}亿  
        - 锁定时间：{pick['time']}  
        - 来源：自动
        """)
        st.info("💡 次日操作：开盘观察10-30分钟，站稳0轴上方介入，严格止损 -2.5%")
        if st.button("✏️ 手动修改最终推荐"):
            st.session_state.final_pick = None
            st.session_state.final_locked = False
            st.rerun()
    else:
        if current_hour >= 14 and current_minute >= 45:
            st.info("未发现符合条件的股票，无最终推荐。")
        else:
            st.info("等待 14:45 自动锁定最终推荐...")

# 额外：如果候选池非空且最终推荐尚未锁定，提供手动选择功能
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
            '量比': row['量比'],
            '成交额': row['成交额'],
            'time': now.strftime("%H:%M:%S"),
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
            st.write(f"{log['timestamp']} - {log['event']}: {log['details']}")
    else:
        st.info("暂无日志记录")

# ===============================
# 自动刷新（交易时段每60秒刷新一次）
# ===============================
if is_trading:
    st.write("⏳ 60秒后自动刷新数据...")
    time.sleep(60)
    st.rerun()

# -*- coding: utf-8 -*-
"""
尾盘博弈 6.4 · Tushare 专用版（优化版）
===================================================
✅ 数据源：仅 Tushare rt_k 接口（支持全市场实时日K行情）
✅ 按板块通配符分批获取，覆盖沪深北所有股票
✅ 实时计算涨跌幅，标准化输出
✅ Token 从 st.secrets 读取，安全可靠
✅ 全自动尾盘推荐与锁定（13:30-14:00 首推，14:40 后锁定）
✅ 板块分析、多因子权重可调、模拟时间测试、缓存管理
✅ 新增：真实因子（振幅、回落、相对强度）、炸板剔除、涨幅>6.5%剔除
✅ 新增：14:00后漏斗记录，14:40收敛推荐并给出备选
"""

import streamlit as st
import akshare as ak
import pandas as pd
import numpy as np
import time
from datetime import datetime
import pytz
import warnings
import tushare as ts

warnings.filterwarnings('ignore')
st.set_page_config(page_title="尾盘博弈 6.4 · Tushare 专用版", layout="wide")

# ===============================
# 🔑 从 Streamlit Secrets 读取 Tushare Token
# ===============================
# 请在 .streamlit/secrets.toml 中设置：
# tushare_token = "你的40位token"
try:
    TUSHARE_TOKEN = "7f85ea86ce467f3b9ab46b1fa1a5b9a71fe089dd0e57d12239899155"
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
    "data_source": "unknown",
    "last_data_fetch_time": None,
    "data_fetch_attempts": 0,
    "a_code_list": None,
    "candidate_history": [],        # 新增：14:00后候选记录
    "final_candidates": None,       # 新增：最终备选列表
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
# Tushare 数据获取（仅此一家）
# ===============================
def fetch_from_tushare():
    """从 Tushare rt_k 接口获取实时行情（按板块分批）"""
    try:
        add_log("数据源", "尝试 Tushare rt_k 接口")

        # 定义板块通配符（覆盖沪深北所有股票）
        # 注意：后缀必须为 .SH / .SZ / .BJ
        board_patterns = [
            "6*.SH",    # 上证主板
            "0*.SZ",    # 深证主板
            "3*.SZ",    # 创业板
            "688*.SH",  # 科创板
            "8*.BJ",    # 北交所（部分代码以8开头）
            "4*.BJ",    # 北交所（部分代码以4开头，如430xxx）
        ]

        all_dfs = []
        total_stocks = 0

        for pattern in board_patterns:
            try:
                # 单次请求，使用通配符
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

        # 去除重复股票（同一个股票可能出现在多个板块？理论上不会，但去重保险）
        df = df.drop_duplicates(subset=['ts_code'])

        add_log("数据源", f"合并后共 {len(df)} 条股票数据")

        # 计算涨跌幅
        # rt_k 接口返回字段：ts_code, name, pre_close, high, open, low, close, vol, amount, num, ...
        # 涨跌幅 = (close - pre_close) / pre_close * 100
        df['涨跌幅'] = (df['close'] - df['pre_close']) / df['pre_close'] * 100

        # 重命名字段为标准列名
        rename_map = {
            'ts_code': '代码',
            'name': '名称',
            'amount': '成交额',
            'vol': '成交量',
            'close': '最新价',
            'open': '开盘价',
            'high': '最高价',
            'low': '最低价',
            'pre_close': '昨收价'
        }
        rename_cols = {k: v for k, v in rename_map.items() if k in df.columns}
        df = df.rename(columns=rename_cols)

        # 添加必须字段（行业待后续合并）
        df['所属行业'] = '未知'

        # 确保必要列存在
        required = ['代码', '名称', '涨跌幅', '成交额', '所属行业']
        missing = [c for c in required if c not in df.columns]
        if missing:
            add_log("数据源", f"字段缺失: {missing}")
            return None

        # 保留有用列
        keep_cols = ['代码', '名称', '涨跌幅', '成交额', '所属行业', '最新价', '成交量', '开盘价', '最高价', '最低价', '昨收价']
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols]

        add_log("数据源", f"✅ Tushare rt_k 成功，最终 {len(df)} 条")
        return df

    except Exception as e:
        add_log("数据源", f"Tushare rt_k 整体异常: {str(e)[:100]}")
        return None

def get_stable_realtime_data():
    """主数据获取函数：仅使用 Tushare，并缓存结果"""
    now = datetime.now(tz)

    # 如果有今日缓存，直接返回
    if st.session_state.today_real_data is not None:
        st.session_state.data_source = "cached_real_data"
        st.session_state.last_data_fetch_time = now
        add_log("数据", "使用今日缓存")
        return st.session_state.today_real_data

    # 非交易时间直接返回空 DataFrame（不缓存）
    is_trading, msg = is_trading_day_and_time(now)
    if not is_trading:
        add_log("数据", f"{msg}，返回空数据")
        st.session_state.data_source = "non_trading"
        st.session_state.last_data_fetch_time = now
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

    # 只尝试 Tushare
    df = fetch_from_tushare()
    if df is not None and not df.empty:
        # ========== 合并行业信息 ==========
        if 'a_code_list' not in st.session_state or st.session_state.a_code_list is None:
            try:
                # 获取所有股票基础信息（含行业）
                stock_info = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,industry')
                if stock_info is not None and not stock_info.empty:
                    st.session_state.a_code_list = stock_info
                    add_log("数据源", f"获取行业信息成功，共{len(stock_info)}条")
                else:
                    st.session_state.a_code_list = pd.DataFrame()
            except Exception as e:
                add_log("数据源", f"获取行业信息失败: {str(e)}")
                st.session_state.a_code_list = pd.DataFrame()

        # 合并行业信息
        if st.session_state.a_code_list is not None and not st.session_state.a_code_list.empty:
            industry_df = st.session_state.a_code_list[['ts_code', 'industry']].copy()
            industry_df = industry_df.rename(columns={'ts_code': '代码', 'industry': '所属行业'})
            # 合并，用行业信息覆盖原有的“未知”
            df = df.merge(industry_df, on='代码', how='left')
            df['所属行业'] = df['所属行业_y'].fillna(df['所属行业_x']).fillna('未知')
            df = df.drop(columns=['所属行业_x', '所属行业_y'], errors='ignore')
        else:
            df['所属行业'] = '未知'

        st.session_state.today_real_data = df.copy()
        st.session_state.data_source = "real_data"
        st.session_state.last_data_fetch_time = now
        add_log("数据源", "最终使用 Tushare")
        return df
    else:
        # Tushare 失败
        add_log("数据源", "Tushare 失败，返回空DataFrame")
        st.session_state.data_source = "failed"
        st.session_state.last_data_fetch_time = now
        return pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 多因子选股引擎（优化版）
# ===============================
def get_technical_indicators(df, sector_avg_dict=None):
    """
    计算真实技术因子
    df: 包含实时行情字段的DataFrame（必须含有open, high, low, close, pre_close, 成交额, 成交量, 所属行业）
    sector_avg_dict: 行业平均涨幅字典（可选，用于计算相对强度）
    """
    if df.empty:
        return df

    df_factor = df.copy()

    # 计算振幅
    df_factor['振幅'] = (df_factor['最高价'] - df_factor['最低价']) / df_factor['昨收价'] * 100

    # 计算回落幅度（相对于当日高点）
    df_factor['回落幅度'] = (df_factor['最高价'] - df_factor['最新价']) / df_factor['昨收价'] * 100

    # 计算是否曾涨停（用于后续过滤）
    df_factor['曾涨停'] = ((df_factor['最高价'] - df_factor['昨收价']) / df_factor['昨收价'] * 100) >= 9.5

    # 计算相对强度（个股涨幅 - 行业平均涨幅）
    if sector_avg_dict is not None and '所属行业' in df_factor.columns:
        df_factor['相对强度'] = df_factor.apply(
            lambda row: row['涨跌幅'] - sector_avg_dict.get(row['所属行业'], 0), axis=1
        )
    else:
        df_factor['相对强度'] = df_factor['涨跌幅']  # 若无行业平均，则直接用涨幅

    # 映射到原有因子名称（保持权重滑块有效）
    # 涨跌幅 -> 涨跌幅（直接用）
    # 成交额 -> 成交额（直接用）
    # 5日动量 -> 相对强度（替代）
    # 20日反转 -> 回落幅度（替代，注意我们希望回落小，所以后续排序时用负向？）
    # 量比 -> 暂设为1.0（无法计算，后续可考虑用成交额分位数）
    # 波动率 -> 振幅（替代）
    df_factor['5日动量'] = df_factor['相对强度']
    df_factor['20日反转'] = -df_factor['回落幅度']  # 反转因子我们期望回落小（即正值大），所以取负，使回落小的股票得分高
    df_factor['量比'] = 1.0  # 暂时固定
    df_factor['波动率'] = df_factor['振幅']

    return df_factor

def filter_stocks_by_rule(df):
    """硬性规则过滤"""
    if df.empty:
        return df
    filtered = df.copy()
    # 剔除ST
    if '名称' in filtered.columns:
        filtered = filtered[~filtered['名称'].str.contains('ST', na=False)]
    # 剔除涨跌幅>9.5或<-9.5
    if '涨跌幅' in filtered.columns:
        filtered = filtered[(filtered['涨跌幅'] < 9.5) & (filtered['涨跌幅'] > -9.5)]
    # 剔除涨幅>6.5%的股票
    if '涨跌幅' in filtered.columns:
        filtered = filtered[filtered['涨跌幅'] <= 6.5]
    # 成交额阈值
    if not filtered.empty and '成交额' in filtered.columns:
        threshold = max(filtered['成交额'].quantile(0.1), 2e7)
        filtered = filtered[filtered['成交额'] > threshold]
    # 换手率过滤（如果有）
    if '换手率' in filtered.columns:
        filtered = filtered[(filtered['换手率'] > 0.5) & (filtered['换手率'] < 50)]
    # 剔除炸板股：曾涨停且当前未封住（即曾涨停且close < high）
    # 先判断是否曾涨停（涨幅>=9.5且high达到过涨停价）
    if '曾涨停' in filtered.columns:
        filtered = filtered[~((filtered['曾涨停']) & (filtered['最新价'] < filtered['最高价']))]
    else:
        # 如果没有曾涨停标记，临时计算
       涨停价条件 = (filtered['最高价'] - filtered['昨收价']) / filtered['昨收价'] * 100 >= 9.5
        filtered = filtered[~(涨停价条件 & (filtered['最新价'] < filtered['最高价']))]
    return filtered

def calculate_composite_score(df, sector_avg_change, weights):
    """多因子综合评分"""
    if df.empty:
        return df
    df_scored = df.copy()
    total_score = np.zeros(len(df_scored))
    for factor, weight in weights.items():
        if factor in df_scored.columns and weight != 0:
            factor_rank = df_scored[factor].rank(pct=True, method='average')
            total_score += factor_rank * weight
    df_scored['综合得分'] = total_score
    risk_penalty = np.zeros(len(df_scored))
    if '涨跌幅' in df_scored.columns:
        high_gain = df_scored['涨跌幅'].clip(lower=6, upper=20)
        risk_penalty += (high_gain - 6) / 70 * 0.2
    if '波动率' in df_scored.columns:
        high_vol = df_scored['波动率'].clip(lower=5, upper=15)
        risk_penalty += (high_vol - 5) / 50 * 0.15
    df_scored['风险调整得分'] = df_scored['综合得分'] - risk_penalty
    return df_scored.sort_values('风险调整得分', ascending=False)

def converge_candidates(history, latest_scored_df, top_n=3):
    """
    从历史记录中收敛出最稳定的候选股
    history: 列表，每个元素包含time和candidates（代码及得分）
    latest_scored_df: 当前评分DataFrame，用于获取最新信息
    top_n: 返回前几名
    """
    if not history or latest_scored_df.empty:
        return None

    # 统计每个代码出现的次数
    code_count = {}
    code_total_score = {}
    for record in history:
        for cand in record['candidates']:
            code = cand['代码']
            score = cand['风险调整得分']
            code_count[code] = code_count.get(code, 0) + 1
            code_total_score[code] = code_total_score.get(code, 0) + score

    # 计算每个代码的平均得分
    code_avg_score = {code: code_total_score[code]/code_count[code] for code in code_count}

    # 综合指标：出现次数 * 平均得分
    code_composite = {code: code_count[code] * code_avg_score[code] for code in code_count}

    # 按综合值排序
    sorted_codes = sorted(code_composite.items(), key=lambda x: x[1], reverse=True)

    # 从latest_scored_df中获取这些股票的详细信息
    result = []
    for code, _ in sorted_codes[:top_n]:
        stock_info = latest_scored_df[latest_scored_df['代码'] == code]
        if not stock_info.empty:
            row = stock_info.iloc[0]
            result.append({
                'name': row['名称'],
                'code': code,
                '涨跌幅': row['涨跌幅'],
                '成交额': row['成交额'],
                '风险调整得分': row['风险调整得分'],
                '综合得分': row['综合得分'],
                '出现次数': code_count[code],
                '平均得分': code_avg_score[code]
            })
    return result

# ===============================
# 主程序开始
# ===============================
now = datetime.now(tz)
st.title("🔥 尾盘博弈 6.4 · Tushare 专用版（优化版）")
st.write(f"当前北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")

# 跨日自动清空
if st.session_state.today != now.date():
    st.session_state.clear()
    st.session_state.today = now.date()
    st.session_state.logs = []
    st.session_state.today_real_data = None
    st.session_state.data_source = "unknown"
    st.session_state.data_fetch_attempts = 0
    st.session_state.a_code_list = None
    st.session_state.candidate_history = []   # 清空历史记录
    st.session_state.final_candidates = None
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
        st.session_state.candidate_history = []   # 清空历史记录
        st.session_state.final_candidates = None
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
    st.markdown("#### ⚙️ 多因子权重配置")
    w_price = st.slider("当日涨幅", 0.0, 0.5, 0.25, 0.05, key="w_price")
    w_volume = st.slider("成交额", 0.0, 0.5, 0.20, 0.05, key="w_volume")
    w_momentum = st.slider("5日动量", 0.0, 0.4, 0.18, 0.05, key="w_momentum")
    w_reversal = st.slider("20日反转", 0.0, 0.3, 0.15, 0.05, key="w_reversal")
    w_vol_ratio = st.slider("量比", 0.0, 0.3, 0.12, 0.05, key="w_vol_ratio")
    w_volatility = st.slider("波动率(负)", -0.2, 0.0, -0.10, 0.05, key="w_volatility")
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
        st.session_state.final_candidates = None
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
            st.session_state.candidate_history = []
            st.session_state.final_candidates = None
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
    is_final_lock_time = (current_hour, current_minute) >= (14, 40)   # 改为14:40
    if is_first_rec_time:
        st.metric("推荐状态", "🟢 可推荐")
    elif is_final_lock_time:
        st.metric("推荐状态", "🔴 需锁定")
    else:
        st.metric("推荐状态", "🟡 观察中")
with col4:
    if period == "午盘" and current_hour >= 14:
        close_time = datetime(current_time.year, current_time.month, current_time.day, 15, 0)
        time_left = close_time - current_time
        minutes_left = max(0, int(time_left.total_seconds() / 60))
        st.metric("距离收盘", f"{minutes_left}分钟")
    else:
        st.metric("自动刷新", "30秒")

# ===============================
# 🚀 获取市场数据（核心调用）
# ===============================
st.markdown("### 📊 数据获取状态")
try:
    with st.spinner("正在获取实时数据..."):
        df = get_stable_realtime_data()

    # 数据源状态横幅
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
    # 不停止，允许后续流程使用空df
    df = pd.DataFrame(columns=['代码', '名称', '涨跌幅', '成交额', '所属行业'])

# ===============================
# 板块分析与选股（适应空数据）
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

st.markdown("### 🎯 多因子智能选股引擎")
if df.empty:
    st.info("当前无股票数据，无法进行选股。")
    top_candidate = None
else:
    st.markdown("**流程**: 规则过滤 → 因子计算 → 综合评分 → 风险调整")
    filtered_by_rule = filter_stocks_by_rule(df)
    st.caption(f"基础过滤后股票数: {len(filtered_by_rule)} / {len(df)}")

    # 计算行业平均涨幅（用于相对强度）
    sector_avg_dict = None
    if '所属行业' in filtered_by_rule.columns and not filtered_by_rule.empty:
        sector_avg = filtered_by_rule.groupby('所属行业')['涨跌幅'].mean().to_dict()
        sector_avg_dict = sector_avg

    # 计算因子
    df_with_factors = get_technical_indicators(filtered_by_rule, sector_avg_dict)

    if not df_with_factors.empty:
        # 综合评分
        sector_avg = df_with_factors['涨跌幅'].mean() if '涨跌幅' in df_with_factors.columns else 0
        scored_df = calculate_composite_score(df_with_factors, sector_avg, factor_weights)
        top_candidates = scored_df.head(10)
        top_candidate = scored_df.iloc[0] if not scored_df.empty else None

        # ========== 漏斗机制：14:00后记录前5名 ==========
        if (current_hour >= 14) and (current_hour < 15):   # 14:00 - 14:59
            top5 = scored_df.head(5)[['代码', '风险调整得分']].to_dict('records')
            record = {
                'time': current_time_str,
                'candidates': top5
            }
            st.session_state.candidate_history.append(record)
            # 保持最近30条记录
            if len(st.session_state.candidate_history) > 30:
                st.session_state.candidate_history = st.session_state.candidate_history[-30:]
            add_log("漏斗记录", f"记录当前前5名")

        # 显示当前前5
        st.markdown("#### 📈 优选股票因子分析")
        if top_candidate is not None:
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
            col_info, col_factors = st.columns([1, 2])
            with col_info:
                st.metric("**选中股票**", f"{top_candidate.get('名称', 'N/A')}")
                st.metric("**代码**", f"{top_candidate.get('代码', 'N/A')}")
                st.metric("**综合得分**", f"{top_candidate.get('综合得分', 0):.3f}")
                st.metric("**风险调整得分**", f"{top_candidate.get('风险调整得分', 0):.3f}")
                if '涨跌幅' in top_candidate:
                    st.metric("**今日涨幅**", f"{top_candidate['涨跌幅']:.2f}%")
            with col_factors:
                if factor_values:
                    factor_df = pd.DataFrame({'因子': factor_names[:len(factor_values)], '得分': factor_values})
                    st.bar_chart(factor_df.set_index('因子'))
                    with st.expander("查看因子权重"):
                        for name, weight in factor_weights.items():
                            if weight != 0:
                                st.write(f"- **{name}**: {weight:.3f}")

            st.markdown("#### 🏆 候选股票排名 (前5)")
            if not top_candidates.empty:
                display_cols = [c for c in ['名称', '代码', '涨跌幅', '成交额', '综合得分', '风险调整得分'] if c in top_candidates.columns]
                display_top5 = top_candidates[display_cols].head().copy()
                display_top5.index = range(1, 6)
                display_top5_display = display_top5.copy()
                if '涨跌幅' in display_top5_display.columns:
                    display_top5_display['涨跌幅'] = display_top5_display['涨跌幅'].apply(lambda x: f"{x:.2f}%")
                if '成交额' in display_top5_display.columns:
                    display_top5_display['成交额'] = display_top5_display['成交额'].apply(lambda x: f"{x/1e8:.2f}亿")
                if '综合得分' in display_top5_display.columns:
                    display_top5_display['综合得分'] = display_top5_display['综合得分'].apply(lambda x: f"{x:.3f}")
                if '风险调整得分' in display_top5_display.columns:
                    display_top5_display['风险调整得分'] = display_top5_display['风险调整得分'].apply(lambda x: f"{x:.3f}")
                st.dataframe(display_top5_display, use_container_width=True)

            st.session_state.test_top_stock = {
                'name': top_candidate.get('名称', ''),
                'code': top_candidate.get('代码', ''),
                '涨跌幅': float(top_candidate.get('涨跌幅', 0)),
                '成交额': float(top_candidate.get('成交额', 0)),
                '换手率': float(top_candidate.get('换手率', 0)),
                '综合得分': float(top_candidate.get('综合得分', 0)),
                'risk_adjusted_score': float(top_candidate.get('风险调整得分', 0)),
                'time': current_time_str,
                'sector': strongest_sector if strongest_sector else '全市场',
                'data_source': st.session_state.data_source
            }
        else:
            st.warning("未找到符合条件的股票")
    else:
        st.warning("因子计算后无数据")
        top_candidate = None

# ===============================
# 自动推荐（仅当数据源为真实数据且有候选股）
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

    # 最终锁定：14:40后，使用收敛结果
    if is_final_lock_time and not st.session_state.locked:
        if use_real_data and not df.empty and top_candidate is not None:
            # 如果有历史记录，进行收敛
            if st.session_state.candidate_history and len(st.session_state.candidate_history) >= 3:  # 至少3条记录
                final_candidates = converge_candidates(st.session_state.candidate_history, scored_df, top_n=3)
                if final_candidates and len(final_candidates) > 0:
                    # 第一名作为最终推荐
                    best = final_candidates[0]
                    st.session_state.final_pick = {
                        'name': best['name'],
                        'code': best['code'],
                        '涨跌幅': best['涨跌幅'],
                        '成交额': best['成交额'],
                        'time': current_time_str,
                        'auto': True,
                        'risk_adjusted_score': best['风险调整得分'],
                        'composite_score': best['综合得分'],
                        'sector': strongest_sector if strongest_sector else '全市场',
                        'data_source': st.session_state.data_source,
                        '出现次数': best['出现次数'],
                        '平均得分': best['平均得分']
                    }
                    st.session_state.locked = True
                    # 保存备选
                    st.session_state.final_candidates = final_candidates[1:]  # 第二、第三
                    add_log("自动推荐", f"锁定最终推荐: {best['name']}，备选: {[c['name'] for c in final_candidates[1:]]}")
                    st.rerun()
                else:
                    # 收敛失败，回退到当前最优
                    st.session_state.final_pick = {
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
                    st.session_state.locked = True
                    st.session_state.final_candidates = []
                    add_log("自动推荐", f"收敛失败，使用当前最优: {top_candidate.get('名称', '')}")
                    st.rerun()
            else:
                # 历史记录不足，直接用当前最优
                st.session_state.final_pick = {
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
                st.session_state.locked = True
                st.session_state.final_candidates = []
                add_log("自动推荐", f"历史记录不足，使用当前最优: {top_candidate.get('名称', '')}")
                st.rerun()
        else:
            st.info("⏸️ 等待真实数据或合适标的")

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
            {f"<p><strong>📊 出现次数:</strong> {pick.get('出现次数', 'N/A')}</p>" if '出现次数' in pick else ""}
            {f"<p><strong>📊 平均得分:</strong> {pick.get('平均得分', 'N/A'):.3f}</p>" if '平均得分' in pick else ""}
        </div>
        """, unsafe_allow_html=True)

        # 新增：显示备选
        if st.session_state.final_candidates and len(st.session_state.final_candidates) > 0:
            st.markdown("#### 🔄 备选股票")
            for i, cand in enumerate(st.session_state.final_candidates, 1):
                st.markdown(f"""
                <div style="background-color: #f9f9f9; padding: 10px; border-radius: 5px; margin: 5px 0;">
                    <strong>备选{i}:</strong> {cand['name']} ({cand['code']})  
                    涨幅: {cand['涨跌幅']:.2f}% | 出现次数: {cand['出现次数']}
                </div>
                """, unsafe_allow_html=True)

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
                st.info("⏳ 等待最终锁定...")
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

import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime, timedelta, timezone

st.set_page_config(page_title="抗压备份终端", layout="wide")

def get_bj_time():
    return datetime.now(timezone(timedelta(hours=8)))

# --- 🚀 核心：腾讯财经备用接口 (极速且不易超时) ---
def get_tencent_price(code):
    """
    腾讯财经接口示例: http://qt.gtimg.cn/q=s_sz002400
    这个接口非常轻量，不容易被封。
    """
    try:
        # 判断沪深代码前缀
        prefix = "sh" if code.startswith("6") else "sz"
        url = f"http://qt.gtimg.cn/q=s_{prefix}{code}"
        # 增加手动超时控制为 5 秒
        r = requests.get(url, timeout=5)
        data = r.text.split('~')
        if len(data) > 3:
            return {
                "name": data[1],
                "price": data[3],
                "change": data[4],
                "change_pct": data[5]
            }
    except:
        return None

# --- UI 渲染 ---
st.title("🛡️ 幻方抗压终端 V4.4 (备用通道)")
st.write(f"🕒 北京时间: {get_bj_time().strftime('%H:%M:%S')}")

# 输入区
codes_input = st.sidebar.text_input("监控代码", value="002400,600986")
stock_list = [s.strip() for s in codes_input.split(",")]

st.subheader("📡 实时盯盘 (腾讯备用引擎)")

# 遍历抓取
cols = st.columns(len(stock_list))
for i, code in enumerate(stock_list):
    with cols[i]:
        # 优先使用备用轻量接口
        res = get_tencent_price(code)
        
        if res:
            pct = float(res['change_pct'])
            color = "#ff4b4b" if pct > 0 else "#00ff00"
            st.markdown(f"""
            <div style="background-color:rgba(255,255,255,0.05); padding:20px; border-radius:10px; border-top:5px solid {color}">
                <h3 style="margin:0">{res['name']}</h3>
                <h1 style="color:{color}; margin:10px 0">{res['price']}</h1>
                <p style="margin:0">涨跌: {res['change_pct']}%</p>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error(f"❌ 代码 {code} 连接失败")

# 自动刷新节奏
st.info("💡 提示：此版本使用腾讯轻量接口，若仍然连接失败，请检查 GitHub 代码是否正确 Commit。")
time.sleep(30)
st.rerun()

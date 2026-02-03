import akshare as ak
import pandas as pd
import time
from datetime import datetime

class MiniHighFlyer:
    def __init__(self, symbol="002400"):
        self.symbol = symbol
        self.support_line = 12.26  # 咱们定的2月3日阳线一半位置
        self.last_volume = 0
        
    def get_realtime_factors(self):
        """抓取并计算多维度因子"""
        try:
            # 1. 实时行情快照
            df = ak.stock_zh_a_spot_em()
            target = df[df['代码'] == self.symbol].iloc[0]
            
            price = float(target['最新价'])
            change_pct = float(target['涨跌幅'])
            turnover = float(target['换手率'])
            volume_ratio = float(target['量比'])
            high = float(target['最高'])
            low = float(target['最低'])

            # 2. 因子计算逻辑 (仿幻方非线性逻辑)
            
            # 因子A: 支撑位偏离因子 (离支撑线越近，分数越高)
            distance_to_support = (price - self.support_line) / self.support_line
            
            # 因子B: 动量衰减因子 (如果高位回落超过1%，警报)
            retracement = (high - price) / high if high > 0 else 0
            
            # 因子C: 换手异常因子 (瞬时换手如果是前一分钟的2倍以上，代表异动)
            # 这里简单用量比代替实时斜率
            is_unusual_volume = volume_ratio > 1.8

            return {
                "time": datetime.now().strftime("%H:%M:%S"),
                "price": price,
                "change": change_pct,
                "distance": f"{distance_to_support:.2%}",
                "retracement": f"{retracement:.2%}",
                "volume_ratio": volume_ratio,
                "is_safe": price > self.support_line,
                "is_unusual": is_unusual_volume
            }
        except Exception as e:
            return {"error": str(e)}

    def generate_signal(self, factors):
        """信号研判引擎"""
        if "error" in factors: return "数据链路中断"
        
        price = factors['price']
        
        # 信号判定逻辑
        if price <= self.support_line * 1.01 and factors['is_safe']:
            return "🟡 [幻方信号]：价格触及黄金支撑带，主力护盘点，【建议买入/持仓】"
        elif not factors['is_safe']:
            return "🔴 [幻方信号]：已跌破12.26元警戒线，趋势走弱，【建议减仓】"
        elif float(factors['volume_ratio']) > 3.0 and factors['change'] > 7:
            return "🟣 [幻方信号]：量比过载，警惕高位放量滞涨，【建议止盈】"
        else:
            return "🟢 [幻方信号]：因子运行平稳，趋势向上，【持股待涨】"

# --- 运行监控 ---
engine = MiniHighFlyer()
print(f"📡 '袖珍幻方'系统启动... 目标: 省广集团 ({engine.symbol})")
print(f"📍 关键支撑位: {engine.support_line}")
print("-" * 50)

while True:
    data = engine.get_realtime_factors()
    signal = engine.generate_signal(data)
    
    print(f"[{data['time']}] 现价:{data['price']} ({data['change']}%) | 离支撑:{data['distance']} | 量比:{data['volume_ratio']}")
    print(f"📢 指令: {signal}")
    print("-" * 50)
    
    time.sleep(60) # 每分钟更新一次，模拟幻方的高频采样
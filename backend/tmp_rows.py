import sqlite3

c = sqlite3.connect(r"C:\Users\Ral\OneDrive - PESUNIVERSITY\Documents\PlayGround\Tradely\data\tradely.sqlite3")
c.row_factory = sqlite3.Row
for r in c.execute(
    "SELECT instrument_id,interval,candle_count,length(payload) AS bytes,generated_at "
    "FROM market_analytics_snapshots WHERE status='READY' ORDER BY interval"
):
    print(dict(r))

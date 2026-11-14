from pathlib import Path
import tempfile

from app.core.config import Settings
from app.core.database import Database
from app.instruments.resolver import InstrumentResolver

tmp = Path(tempfile.mkdtemp()) / "t.sqlite3"
db = Database(tmp)
r = InstrumentResolver(Settings(database_path=str(tmp)), db)
r.ensure_catalogue()
for q in [
    "RELIANCE", "reliance", "TCS", "INFY", "AAPL", "aapl", "MSFT",
    "BTCUSDT", "ethusdt", "Apple", "Microsoft", "Reli", "Micros", "Bit",
    "Ethereum", "Nvidia", "BTCUSD", "XYZ", "  reliance  ", "ETHBTC",
]:
    out = r.resolve(q)
    iid = out["instrument"]["instrument_id"] if out.get("instrument") else None
    print(q, "=>", out["status"], iid, out.get("message"),
          [c["instrument_id"] for c in out.get("candidates", [])[:4]])
print("count", db.catalogue_count())
print("cap", r.capabilities("crypto:BINANCE:BTCUSDT")["supported_intervals"][:3],
      r.capabilities("india:NSE:RELIANCE")["backtesting_eligible"])

"""Inspect aggregate analytics cache sizes in an explicitly selected SQLite file."""
import argparse
import sqlite3
from contextlib import closing
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    path = parser.parse_args().database.resolve(strict=True)
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        for interval, count, candles, size in connection.execute(
            "SELECT interval, COUNT(*), SUM(candle_count), SUM(length(payload)) "
            "FROM market_analytics_snapshots WHERE status='READY' GROUP BY interval ORDER BY interval"
        ):
            print(f"{interval}: {count} snapshots, {candles} candles, {size} compressed bytes")


if __name__ == "__main__":
    main()

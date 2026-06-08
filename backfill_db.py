#!/usr/bin/env python3
"""
Backfill script to populate hyperliquid_stats.db from existing markdown logs.
Parses logs/YYYY-MM-DD.md files and extracts metrics into the database.
"""

import re
from pathlib import Path
from db import init_db, upsert_daily


def parse_markdown_log(file_path: Path) -> dict:
    """Parse a markdown log file and extract metrics."""
    with open(file_path, 'r') as f:
        content = f.read()

    # Extract date from filename
    date = file_path.stem  # YYYY-MM-DD

    record = {'date': date}

    # Parse BTC data - try new format first (with 1d, 7d, 30d changes)
    btc_match = re.search(r'\*\*\$BTC\*\*\s*\|\s*\$([0-9,]+)\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%', content)
    if btc_match:
        record['btc_price'] = float(btc_match.group(1).replace(',', ''))
        record['btc_1d_chg'] = float(btc_match.group(2))
        record['btc_7d_chg'] = float(btc_match.group(3))
        record['btc_30d_chg'] = float(btc_match.group(4))
    else:
        # Try format with only 1d and 7d changes
        btc_short_match = re.search(r'\*\*\$BTC\*\*\s*\|\s*\$([0-9,]+)\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%', content)
        if btc_short_match:
            record['btc_price'] = float(btc_short_match.group(1).replace(',', ''))
            record['btc_1d_chg'] = float(btc_short_match.group(2))
            record['btc_7d_chg'] = float(btc_short_match.group(3))
        else:
            # Try old format (7d and 30d with prices)
            btc_old_match = re.search(r'\*\*\$BTC\*\*\s*\|\s*\$([0-9,]+)\s*\|\s*\$[0-9,]+\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*\$[0-9,]+\s*\|\s*([+-]?[0-9.]+)%', content)
            if btc_old_match:
                record['btc_price'] = float(btc_old_match.group(1).replace(',', ''))
                record['btc_7d_chg'] = float(btc_old_match.group(2))
                record['btc_30d_chg'] = float(btc_old_match.group(3))

    # Parse HYPE data - try new format first (with 1d, 7d, 30d changes)
    hype_match = re.search(r'\*\*\$HYPE\*\*\s*\|\s*\$([0-9.]+)\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%', content)
    if hype_match:
        record['hype_price'] = float(hype_match.group(1))
        record['hype_1d_chg'] = float(hype_match.group(2))
        record['hype_7d_chg'] = float(hype_match.group(3))
        record['hype_30d_chg'] = float(hype_match.group(4))
    else:
        # Try format with only 1d and 7d changes
        hype_short_match = re.search(r'\*\*\$HYPE\*\*\s*\|\s*\$([0-9.]+)\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*([+-]?[0-9.]+)%', content)
        if hype_short_match:
            record['hype_price'] = float(hype_short_match.group(1))
            record['hype_1d_chg'] = float(hype_short_match.group(2))
            record['hype_7d_chg'] = float(hype_short_match.group(3))
        else:
            # Try old format (7d and 30d with prices)
            hype_old_match = re.search(r'\*\*\$HYPE\*\*\s*\|\s*\$([0-9.]+)\s*\|\s*\$[0-9.]+\s*\|\s*([+-]?[0-9.]+)%\s*\|\s*\$[0-9.]+\s*\|\s*([+-]?[0-9.]+)%', content)
            if hype_old_match:
                record['hype_price'] = float(hype_old_match.group(1))
                record['hype_7d_chg'] = float(hype_old_match.group(2))
                record['hype_30d_chg'] = float(hype_old_match.group(3))

    # Parse Revenue data
    today_match = re.search(r'\|\s*Today\s*\|\s*\$([0-9,]+)', content)
    if today_match:
        record['revenue_daily'] = float(today_match.group(1).replace(',', ''))

    avg_7d_match = re.search(r'\|\s*7d avg\s*\|\s*\$([0-9,]+)', content)
    if avg_7d_match:
        record['revenue_7d_avg'] = float(avg_7d_match.group(1).replace(',', ''))

    avg_30d_match = re.search(r'\|\s*30d avg\s*\|\s*\$([0-9,]+)', content)
    if avg_30d_match:
        record['revenue_30d_avg'] = float(avg_30d_match.group(1).replace(',', ''))

    vs_match = re.search(r'\|\s*7d vs 30d\s*\|\s*([+-]?[0-9.]+)%', content)
    if vs_match:
        record['revenue_7d_vs_30d'] = float(vs_match.group(1))

    return record


def main():
    script_dir = Path(__file__).parent
    db_path = script_dir / "hyperliquid_stats.db"
    logs_dir = script_dir / "logs"

    # Initialize database
    init_db(db_path)
    print(f"Database initialized: {db_path}")

    # Find all markdown log files
    log_files = sorted(logs_dir.glob("*.md"))
    print(f"Found {len(log_files)} log files to process\n")

    inserted = 0
    skipped = 0

    for log_file in log_files:
        try:
            record = parse_markdown_log(log_file)

            # Check if we have at least some data
            if len(record) > 1:  # More than just 'date'
                upsert_daily(db_path, record)
                print(f"✓ {record['date']}: Inserted {len(record)-1} metrics")
                inserted += 1
            else:
                print(f"✗ {record['date']}: No data found, skipped")
                skipped += 1
        except Exception as e:
            print(f"✗ {log_file.name}: Error - {e}")
            skipped += 1

    print(f"\n{'='*50}")
    print(f"Backfill complete!")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped:  {skipped}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()

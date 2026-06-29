"""
HistData.com からダウンロードしたCSVデータの読み込み

HistData は登録不要で無料の1分足データを提供している。
http://www.histdata.com/download-free-forex-data/

ダウンロード後、以下のように使う:
  python data/load_histdata.py --dir data/histdata_usdjpy/ --output data/USD_JPY_H1.csv

HistData のCSV形式:
  - ASCII形式: DateTime;Open;High;Low;Close;Volume (セミコロン区切り)
  - MS Excel形式: YYYYMMDD HHMMSS,Open,High,Low,Close,Volume (カンマ区切り)
  いずれも1分足(M1)

このスクリプトは M1 を H1 にリサンプルしてバックテスト用に出力する。
"""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd
import glob


def read_histdata_file(filepath: str) -> pd.DataFrame:
    """1つのHistDataファイルを読む（形式自動判定）"""
    with open(filepath, "r") as f:
        first = f.readline().strip()

    # セミコロン区切り (ASCII形式)
    if ";" in first:
        df = pd.read_csv(filepath, sep=";", header=None,
                         names=["datetime", "open", "high", "low", "close", "volume"])
    else:
        # カンマ区切り
        df = pd.read_csv(filepath, header=None)
        if len(df.columns) == 6:
            df.columns = ["datetime", "open", "high", "low", "close", "volume"]
        elif len(df.columns) == 7:
            df.columns = ["date", "time", "open", "high", "low", "close", "volume"]
            df["datetime"] = df["date"].astype(str) + " " + df["time"].astype(str)
            df = df.drop(columns=["date", "time"])
        else:
            raise ValueError(f"Unexpected column count: {len(df.columns)} in {filepath}")

    df["datetime"] = pd.to_datetime(df["datetime"], format="mixed")
    df = df.set_index("datetime")
    df = df[["open", "high", "low", "close"]].astype(float)
    return df


def resample_m1_to_h1(df: pd.DataFrame) -> pd.DataFrame:
    """1分足を1時間足にリサンプル"""
    h1 = df.resample("1h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }).dropna()
    return h1


def main():
    parser = argparse.ArgumentParser(description="Load HistData CSVs and resample to H1")
    parser.add_argument("--dir", required=True, help="HistData CSVファイルのディレクトリ")
    parser.add_argument("--output", default="data/USD_JPY_H1.csv", help="出力ファイルパス")
    parser.add_argument("--pattern", default="*.csv", help="ファイルパターン")
    args = parser.parse_args()

    files = sorted(glob.glob(str(Path(args.dir) / args.pattern)))
    if not files:
        print(f"No CSV files found in {args.dir}")
        return

    print(f"Found {len(files)} files")
    all_dfs = []
    for f in files:
        try:
            df = read_histdata_file(f)
            all_dfs.append(df)
            print(f"  {Path(f).name}: {len(df):,} rows, {df.index[0]} ~ {df.index[-1]}")
        except Exception as e:
            print(f"  {Path(f).name}: SKIP ({e})")

    if not all_dfs:
        print("No data loaded")
        return

    combined = pd.concat(all_dfs).sort_index()
    combined = combined[~combined.index.duplicated(keep="last")]
    print(f"\nCombined M1: {len(combined):,} rows")
    print(f"  Period: {combined.index[0]} ~ {combined.index[-1]}")

    # H1にリサンプル
    h1 = resample_m1_to_h1(combined)
    h1.index = h1.index.tz_localize("UTC")

    # 保存
    output_path = Path(args.output)
    output_path.parent.mkdir(exist_ok=True)
    h1.to_csv(str(output_path))
    print(f"\nSaved H1: {output_path}")
    print(f"  Rows: {len(h1):,}")
    print(f"  Period: {h1.index[0]} ~ {h1.index[-1]}")


if __name__ == "__main__":
    main()

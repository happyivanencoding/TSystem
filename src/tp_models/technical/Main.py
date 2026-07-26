import pandas as pd
import os
import sys
from pathlib import Path
import warnings

from tp_core.data_sources import RETURNS_PATH as CANONICAL_RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH

from .utils import *

warnings.filterwarnings("ignore")

if sys.platform.startswith("win"):
    UNC_ROOT = Path(r"\\groupe-ufg.com\Commun")  
    BASE_ING_FI = UNC_ROOT  / "Prive" / "GestionAM" / "Ingenierie_Financiere" 

else: 
    # UNC_ROOT = Path(rf"/mnt") 
    BASE_ING_FI = Path(rf"/mnt/Ingenierie_Financiere")  

BASE_ING_FI = Path(os.environ.get("TA_BASE_DIR", str(BASE_ING_FI)))

def resolve_path(env_name, default_path):
    return Path(os.environ.get(env_name, str(default_path)))

path_returns = resolve_path("TA_RETURNS_PATH", CANONICAL_RETURNS_PATH)
path_screen = resolve_path("TA_SCREEN_PATH", SCREEN_AGGREGATE_PATH)
path_output_pattern = resolve_path("TA_OUTPUT_PATH", BASE_ING_FI / "PROD" / "_EQUITY"/ "0_RETURNS"/ "patterns.parquet")

if __name__ == "__main__":
    print("LOAD DATA")
    returns = pd.read_parquet(path_returns) 
    screen_agg = pd.read_parquet(path_screen)

    filter_univ = (screen_agg["Weight in SP500"]>0) | (screen_agg["Weight in STOXX EUROPE 600"]>0)
    # filter_univ = (screen_agg["Weight in SP500"]>0)
    isin_to_compute = screen_agg[filter_univ]['Company SEDOL'].dropna().unique()
    try:
        print("Date max du screen_agg :" , screen_agg["Date"].max())

    except Exception as e:
        print("Erreur ignorée :", e)

    valid_cols = [
                    col for col in isin_to_compute
                    if col                     # enlève None, '', False
                    and str(col).lower() != "none"
                    and col in returns.columns
                ]
    print("DETECTION PATTERN")
    patterns=detect_pattern_(returns[valid_cols])
    patterns=patterns.stack(level=0)

    try:
        print("Date max du df :" , patterns["Date"].max())
    except Exception as e:
        print("Erreur ignorée :", e)

    print("DETECTION BOUGIE PATTERN")
    patterns_candle=detect_pattern_(returns[valid_cols],library='candlestick')
    patterns_candle = patterns_candle.loc[:,~patterns_candle.columns.get_level_values(1).isin(['low','open','close','high'])].stack(level=0)
    patterns_inter=pd.concat([patterns,patterns_candle.loc[patterns.index]],axis=1)

    try:
        print("Date max du df :" , patterns_inter["Date"].max())
    except Exception as e:
        print("Erreur ignorée :", e)
    
    patterns_inter.index = patterns_inter.index.reorder_levels([1,0])
    patterns_inter.index.names = ['Company SEDOL', 'Date']

    indicator=patterns_inter[['Open','High','Low','Close']].groupby(level=0,axis=0).apply(calcul_indicator).droplevel(0)
    patterns_total = pd.concat([patterns_inter,indicator.iloc[:,4:]],axis=1)

    patterns_total = patterns_total.reset_index()
    patterns_total = add_period_availability_columns(patterns_total, returns.index, date_col="Date", period="week")
    patterns_total.set_index("Company SEDOL", inplace = True, drop = True)


    try:
        print("Date max du df :" , patterns_total["Date"].max())
    except Exception as e:
        print("Erreur ignorée :", e)

    print("EXPORT DATA")
    patterns_total.to_parquet(path_output_pattern)


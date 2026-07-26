import pandas as pd
import numpy as np
import datetime
from dateutil import relativedelta
from typing import Tuple, Dict, Any, Iterable, Optional, Sequence
from pathlib import Path

from tp_core.data_contract import drop_deprecated_screen_columns
from .technicals import *
from collections import Counter
import os

# Exchange to Country mapping dictionary
exchange_country_dict = {
    'ARGENTINA MARKET VALUES (MERV': 'UNITED STATES',
    'AUSTRALIA ASX ALL ORDINARIES': 'AUSTRALIA',
    'AUSTRIA ATX': 'AUSTRIA',
    'BELGIUM BEL-20': 'BELGIUM',
    'BRAZIL IBOVESPA': 'BRAZIL',
    'CANADA S&P/TSX COMPOSITE': 'CANADA',
    'CHILE IPSA': 'CHILE',
    'CHINA SHANGHAI COMPOSITE': 'CHINA',
    'COLOMBIA GENERAL': 'COLOMBIA',
    'CZECH(REP OF) PX': 'CZECH REPUBLIC',
    'DENMARK OMXC 20': 'DENMARK',
    'EGYPT EGX 30': 'EGYPT',
    'FINLAND OMXH': 'FINLAND',
    'FRANCE CAC 40': 'FRANCE',
    'FTSE BURSA MALAYSI KLCI': 'MALAYSIA',
    'FTSE DIFX UAE 20(USD)': 'UNITED ARAB EMIRATES',
    'FTSE ITALIA MIB': 'ITALY',
    'FTSE ST STRAITS TIMES INDEX': 'SINGAPORE',
    'FTSE UK ALL-SHARE(GBP)': 'UNITED KINGDOM',
    'FTSE/JSE AFRICA ALL SHARE': 'SOUTH AFRICA',
    'GERMANY DAX(TR)': 'GERMANY',
    'GREECE ATHEX COMPOSITE': 'GREECE',
    'HONG KONG HANG SENG': 'HONG KONG',
    'HUNGARY BUX': 'HUNGARY',
    'INDIA BOMBAY BSE SENSEX(BSE30)': 'INDIA',
    'INDONESIA IDX COMPOSITE': 'INDONESIA',
    'IRELAND ISEQ ALL-SHARE': 'IRELAND',
    'ISRAEL TA 125 (TRG)': 'ISRAEL',
    'JAPAN TOPIX': 'JAPAN',
    'KAZAKHSTAN KASE': 'UNITED KINGDOM',
    'KOREA KOSPI COMPOSITE': 'SOUTH KOREA',
    'KUWAIT (STATE OF) MARKET IXP': 'KUWAIT',
    'LUXEMBOURG SEL FD LUXX': 'FRANCE',
    'MEXICO(UTD MEX ST) IPC': 'MEXICO',
    'MOROCCO MASI': 'MOROCCO',
    'NETHERLANDS AEX INDEX': 'NETHERLANDS',
    'NEW ZEALAND S&P/NZX 50(TRG)': 'NEW ZEALAND',
    'NORWAY OBX (TR)': 'NORWAY',
    'PAKISTAN(REP OF) KSE 100 (TR)': 'PAKISTAN',
    'PERU BVL GENERAL': 'UNITED STATES',
    'PHILIPPINES PSEI': 'PHILIPPINES',
    'POLAND WIG(TR)': 'POLAND',
    'PORTUGAL PSI GENERAL': 'PORTUGAL',
    'QATAR QE INDEX': 'QATAR',
    'RUSSIA RTS': 'RUSSIA',
    'S&P 500 Index': 'UNITED STATES',
    'SAUDI ARABIA TADAWUL ALL SHARE I': 'SAUDI ARABIA',
    'SPAIN IBEX 35': 'SPAIN',
    'SWEDEN OMXS 30': 'SWEDEN',
    'SWITZERLAND SMI': 'SWITZERLAND',
    'TAIWAN TAIEX': 'TAIWAN',
    'THAILAND SET': 'THAILAND',
    'TURKEY NATIONAL 100': 'TURKEY'
}

# List of columns to fill with secondary data when main row has missing values
columns_to_fill = [
    "Benchmark ICB Industry", "Benchmark ICB Supersector", 'ESG_E',
    'ESG_S', 'ESG_G', 'ESG_ANALYST_SCORE', 'CARBON_IMPACT_SCORE',
    'CarbonIntensity_Sales', 'CarbonIntensity_EV', 'Decile_CarbIntensity',
    'Dividend Avg Percentile', 'Value Avg Percentile', 'Quality Avg Percentile',
    'Mom Avg Percentile', 'Size Avg Percentile', 'LowVol Avg Percentile',
    'Growth Avg Percentile', 'Total Return', 'TTR_Fwd1M',
    'Constituent Weight SOM', 'PMOM 12M1M', 'PCT MOM 12M1M',
    'EPS Med NTM -3M', 'EPS Med NTM 0', 'EPS NTM 3M Growth',
    'PCT EPSM3M', 'EPS Revision Ratio', 'PCT ERR', 'MOM Score',
    'PCT MOM Score', 'PE LTM', 'PE FY1', 'PCT PE LTM', 'PCT PE FY1',
    'PB LTM', 'Price to Book FY1', 'PTangibleBook LTM',
    'PB / PTangibleBook LTM', 'PB / PTangibleBook NTM', 'PCT PB LTM',
    'PCT PB FY1', 'PFCF LTM', 'Price to FreeCF FY1', 'PCT PFCF LTM',
    'PCT PFCF FY1', 'EV To EBITDA LTM', 'EV To EBITDA FY1',
    'PCT EVEBITDA LTM', 'PCT EVEBITDA FY1', 'EV to Ebit FY1',
    'PCT EVEBIT NTM', 'EV to Sales FY1', 'PCT EV to Sales FY1',
    'EV to Sales LTM', 'PCT EV to Sales LTM', 'Value_Forward Avg Percentile',
    'Value_Spot_Avg Percentile', 'ROE avg FY0', 'PCT ROE',
    'NetDebt to EBITDA exFIN', 'PCT NBEBITDA', 'Oper Margin',
    'PCT OM FY0', 'Asset TO exFIN', 'PCT Asset TO', 'TIER1 Ratio FY0',
    'PCT TIER1', 'ROTE avg FY1', 'PCT ROTE', 'Combined Ratio FY1',
    'PCT CombinedRatio', 'DVD Yield FY0', 'DVD Payout FY0',
    'DVD Yield FY1', 'DPS 1Y Growth Forecast', 'DPS FY1',
    'D_DPS TrendStab', 'PCT Payout Ratio', 'PCT DPS 1YGR',
    'PCT DvdYield FY1', 'Earns Yield FY0', 'Earns Yield FY1',
    'Sales Growth FY1', 'PCT Sales Growth', 'Gross Income Growth FY1',
    'PCT Gross Income Growth', 'EPS Growth FY1', 'PCT EPS Growth FY1',
    '5Y_Hist EPS TrendStab', 'PCT Hist EPS', '5Y_Hist GrossInc TrendStab',
    'PCT Hist GrossInc', '5Y_Hist Sales TrendStab', 'PCT Hist Sales',
    'Growth_Forward_Avg Percentile', 'Growth_Historical_Avg Percentile',
    'Daily Vol 60J', 'PCT DVol 60J', 'Daily Vol 90J', 'PCT DVol 90J',
    'Daily Vol 260J', 'PCT DVol 260J', 'PCT Sales FY0', 'PCT Assets FY0',
    'PCT Mkt Value', 'Weight in DJ BROOKFIELD', 'Weight in GLOBAL INFRA',
    'Weight in GLOBAL REIT', 'Weight in MSCI ACWI', 'Weight in MSCI EM',
    'Weight in MSCI EUR SMALL', 'Weight in NIKKEI', 'Weight in NMX',
    'Weight in SP500', 'Weight in STOXX EUROPE 600', 'Weight in MSCI EUR',
    'Weight in MSCI WORLD', 'Weight in CAC40', 'Weight in EUROSTOXX50',
    'Weight in MSCI EMU', 'Weight in NASDAQ COMP', 'Weight in RUSSELL 2000'
]

PERF_WINDOWS = {
    "Perf5D": 5,
    "Perf1M": 20,
    "Perf3M": 60,
    "Perf6M": 120,
}

RISK_COLUMN_MAPPING = {
    'volatility': 'Volatilite Rolling ewma 250D',
    'var': 'VaR 1% Rolling 250D',
    'max_drawdown': 'Maximum Drawdown Rolling 250D',
    'beta': 'Beta vs SXXP (Rolling ewma 250D)',
    'regional_beta': 'Beta vs Regional Benchmark (Rolling ewma 250D)',
    'beta_up': 'Beta Up vs SXXP (252D)',
    'beta_down': 'Beta Down vs SXXP (252D)',
}

def drop_deprecated_em_cluster_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible alias for the shared screen data contract cleanup."""
    return drop_deprecated_screen_columns(df)


def is_empty_value(value):
    """
    Check if a value should be considered as empty/missing
    """
    return pd.isna(value) or value == ''


def get_latest_modified_file(
    directory_name: str,
    suffixes: Optional[Sequence[str]] = None,
    excluded_names: Optional[Sequence[str]] = None,
) -> str:
    """返回目录中最新修改的候选文件。"""
    directory = Path(directory_name)
    if not directory.exists():
        raise FileNotFoundError(f"目录不存在: {directory}")

    excluded = {name.lower() for name in (excluded_names or [])}
    normalized_suffixes = None
    if suffixes is not None:
        normalized_suffixes = {suffix.lower() for suffix in suffixes}

    candidates = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        if path.name.lower() in excluded:
            continue
        if normalized_suffixes is not None and path.suffix.lower() not in normalized_suffixes:
            continue
        candidates.append(path)

    if not candidates:
        raise FileNotFoundError(f"目录中未找到可用文件: {directory}")

    return str(max(candidates, key=lambda item: item.stat().st_mtime))

def get_last_item(directory_name):
    last_item = ""
    try:
        # Liste les fichiers dans le dossier spécifié
        for file_name in os.listdir(directory_name):
            file_path = os.path.join(directory_name, file_name)
            if os.path.isfile(file_path) and file_name != ".Rhistory":
                last_item = file_path  # Ecrasé à chaque itération : on garde le dernier
    except Exception as e:
        raise RuntimeError(f"Erreur lors de la lecture du dossier '{directory_name}': {e}")
    return last_item


def consolidate_duplicate_isin_with_tracking(df):
    """
    Consolidate duplicate ISIN data by selecting main row and filling missing values with secondary row data.
    Also tracks which columns were changed during consolidation.
    
    Parameters:
    df (pandas.DataFrame): Input dataframe with potential duplicate ISINs
    
    Returns:
    tuple: (consolidated_dataframe, changes_log)
    """
    # Create list to store consolidated rows and changes log
    consolidated_rows = []
    changes_log = {}
    
    # Group by ISIN to process each group separately
    grouped = df.groupby('ISIN')
    
    for isin, group in grouped:
        if len(group) == 1:
            # Single row case: keep as is, no changes
            consolidated_rows.append(group.iloc[0])
            changes_log[isin] = {'main_exchange': group.iloc[0]['Company Main Exchange'], 
                                'columns_changed': [], 'had_duplicates': False}
        else:
            # Multiple rows case: need to consolidate
            main_row = None
            secondary_rows = []
            
            # Find the main row based on exchange-country mapping
            for idx, row in group.iterrows():
                company_exchange = row['Company Main Exchange']
                country_name = row['Exchange Country Name']
                
                # Check if this row matches the expected country for this exchange
                if (company_exchange in exchange_country_dict and 
                    exchange_country_dict[company_exchange] == country_name):
                    main_row = row.copy()
                else:
                    secondary_rows.append(row)
            
            # If no matching main row found, use the first row as main row
            if main_row is None:
                main_row = group.iloc[0].copy()
                secondary_rows = [row for idx, row in group.iterrows() if idx != group.index[0]]
            
            # Track changes for this ISIN
            columns_changed = []
            
            # Fill missing values in main row with data from secondary rows
            for secondary_row in secondary_rows:
                for col in columns_to_fill:
                    # Check if column exists in the dataframe
                    if col in main_row.index:
                        # Store original value for comparison
                        original_value = main_row[col]
                        
                        # If main row has missing/empty value, fill with secondary row's value
                        if is_empty_value(main_row[col]):
                            # Only fill if secondary row has a valid (non-empty, non-zero) value
                            if not is_empty_value(secondary_row[col]):
                                main_row[col] = secondary_row[col]
                                columns_changed.append({
                                    'column': col,
                                    'original_value': original_value,
                                    'new_value': secondary_row[col],
                                    'source_exchange': secondary_row['Company Main Exchange']
                                })
            
            # Add the consolidated main row to results
            consolidated_rows.append(main_row)
            changes_log[isin] = {
                'main_exchange': main_row['Company Main Exchange'],
                'columns_changed': columns_changed,
                'had_duplicates': True,
                'num_secondary_rows': len(secondary_rows),
                'secondary_exchanges': [row['Company Main Exchange'] for row in secondary_rows]
            }
    
    # Create new dataframe from consolidated rows
    result_df = pd.DataFrame(consolidated_rows).reset_index()
    return result_df, changes_log

def display_consolidation_summary(original_df, consolidated_df, changes_log, 
                                show_basic_stats=True, 
                                show_consolidation_examples=True, 
                                show_complemented_examples=True,
                                max_examples=5,
                                max_top_columns=10):
    """
    Display detailed summary and examples of the ISIN consolidation process.
    
    Parameters:
    original_df (pandas.DataFrame): Original dataframe before consolidation
    consolidated_df (pandas.DataFrame): Dataframe after consolidation
    changes_log (dict): Log of changes made during consolidation
    show_basic_stats (bool): Whether to show basic consolidation statistics
    show_consolidation_examples (bool): Whether to show examples of consolidation
    show_complemented_examples (bool): Whether to show examples where secondary rows provided data
    max_examples (int): Maximum number of examples to show
    max_top_columns (int): Maximum number of top columns to show in summary
    """
    
    if show_basic_stats:
        print("="*80)
        print("CONSOLIDATION SUMMARY STATISTICS")
        print("="*80)
        print(f"Original number of rows: {len(original_df)}")
        print(f"Consolidated number of rows: {len(consolidated_df)}")
        print(f"Number of duplicate ISINs removed: {len(original_df) - len(consolidated_df)}")
        
        # Verify results (check if there are still duplicate ISINs)
        duplicate_check = consolidated_df.groupby('ISIN').size()
        print(f"Remaining duplicate ISINs after consolidation: {(duplicate_check > 1).sum()}")
    
    if show_consolidation_examples:
        print("\n" + "="*80)
        print("CONSOLIDATION EXAMPLES (Original Duplicates)")
        print("="*80)
        duplicate_isins = original_df.groupby('ISIN').size()
        example_isins = duplicate_isins[duplicate_isins > 1].head(max_examples).index.tolist()

        if example_isins:
            for i, isin in enumerate(example_isins, 1):
                print(f"\nExample {i} - ISIN: {isin}")
                print("Original rows:")
                print(original_df[original_df['ISIN'] == isin][['Company Main Exchange', 'Exchange Country Name']].to_string())
                print("Consolidated to:")
                print(consolidated_df[consolidated_df['ISIN'] == isin][['Company Main Exchange', 'Exchange Country Name']].to_string())
        else:
            print("No duplicate ISINs found in the original data.")
    
    if show_complemented_examples:
        print("\n" + "="*80)
        print("EXAMPLES WHERE SECONDARY ROWS COMPLEMENTED MAIN ROWS")
        print("="*80)

        # Find ISINs where actual changes were made
        complemented_isins = {isin: log for isin, log in changes_log.items() 
                            if log['had_duplicates'] and len(log['columns_changed']) > 0}

        if complemented_isins:
            print(f"\nFound {len(complemented_isins)} ISINs where secondary rows provided complementary data:")
            
            # Show examples (limited by max_examples)
            for i, (isin, log) in enumerate(list(complemented_isins.items())[:max_examples]):
                print(f"\n{'-'*60}")
                print(f"EXAMPLE {i+1}: ISIN = {isin}")
                print(f"Number of columns complemented: {len(log['columns_changed'])}")
                
                print(f"\nColumns that were filled from secondary row(s):")
                for change in log['columns_changed']:
                    print(f"  • {change['column']}: {change['original_value']} → {change['new_value']} (from {change['source_exchange']})")
                
                # Show the original and consolidated rows for comparison
                print(f"\nOriginal rows for this ISIN:")
                original_rows = original_df[original_df['ISIN'] == isin][['Company Main Exchange', 'Exchange Country Name'] + 
                                                        [change['column'] for change in log['columns_changed']]]
                print(original_rows.to_string(index=False))
                
                print(f"\nConsolidated row:")
                consolidated_row = consolidated_df[consolidated_df['ISIN'] == isin][['Company Main Exchange', 'Exchange Country Name'] + 
                                                                                [change['column'] for change in log['columns_changed']]]
                print(consolidated_row.to_string(index=False))

            # Summary of most frequently complemented columns
            all_changed_columns = []
            for log in complemented_isins.values():
                all_changed_columns.extend([change['column'] for change in log['columns_changed']])
            
            if all_changed_columns:
                column_counts = Counter(all_changed_columns)
                
                print(f"\n{'-'*60}")
                print("MOST FREQUENTLY COMPLEMENTED COLUMNS:")
                for col, count in column_counts.most_common(max_top_columns):
                    print(f"  {col}: {count} times")

        else:
            print("\nNo examples found where secondary rows provided complementary data.")
            print("This could mean:")
            print("- No duplicate ISINs had complementary data")
            print("- The specified columns don't exist in your dataframe")
            print("- All values in the target columns were already filled in main rows")




class ScreenProcessor:
    """Classe pour traiter les données de screening financier de manière modulaire"""
    
    def __init__(self, param_mapping_excel: str, path_returns: str):
        self.param_mapping_excel = param_mapping_excel
        self.path_returns = path_returns
        self.icb_supersectors_mapping = {  
            1: "Auto & Parts", 
            2: "Banks", 
            3: "Basic Resources", 
            4: "Chemicals",
            5: "Construction", 
            6: "Financial Services", 
            7: "Food, Beverage & Tobacco",
            8: "Health Care", 
            9: "Industrial Goods & Services", 
            10: "Insurance",
            11: "Media", 
            12: "Energy", 
            13: "Personal & Household Goods",
            14: "Real Estate", 
            15: "Retail", 
            16: "Technology",
            17: "Telecommunications", 
            18: "Travel & Leisure", 
            19: "Utilities"
        }

    def normalize_benchmark_market_value_column(self, df: pd.DataFrame) -> pd.DataFrame:
        """统一市值列命名并用 BK 列回填空值。"""
        base_col = "Benchmark Market Value Millions in EUR"
        legacy_col = "Benchmark Market Value Millions in EUR "
        bk_col = "Benchmark Market Value Millions in EUR BK"

        temp = self._ensure_isin_column(df).copy()
        if "Date" in temp.columns:
            temp["Date"] = pd.to_datetime(temp["Date"], errors="coerce")
            temp = temp.set_index(["ISIN", "Date"], drop=False)

        if legacy_col in temp.columns:
            if base_col in temp.columns:
                temp[base_col] = temp[base_col].combine_first(temp[legacy_col])
                temp = temp.drop(columns=[legacy_col])
            else:
                temp = temp.rename(columns={legacy_col: base_col})

        if bk_col in temp.columns:
            if base_col not in temp.columns:
                temp[base_col] = np.nan
            temp[base_col] = temp[base_col].combine_first(temp[bk_col])

        if isinstance(temp.index, pd.MultiIndex) and temp.index.names == ["ISIN", "Date"]:
            temp = temp.reset_index(drop=True)

        if "ISIN" not in df.columns and df.index.name == "ISIN":
            temp = temp.set_index("ISIN")
        return temp
    
    def read_new_FS_screen(self, screen_excel: str) -> pd.DataFrame:
        """
        Traite le fichier Excel de screening et applique les mappings ICB.
        """


        # Lecture du fichier Excel principal
        df = pd.read_excel(
            screen_excel, 
            header=0, 
            index_col=4, 
            skiprows=[0,1,2,3,5], 
            na_values=["@NA", "#N/A"]
        )
        
        df = self.normalize_benchmark_market_value_column(df)
            
        # Nettoyage des données
        # df = df[~df.index.duplicated(keep='first')]
        # df = df.loc[df.index.notna()]
        df = df.reset_index()
        
        consolidated_df, changes_log = consolidate_duplicate_isin_with_tracking(df)
        display_consolidation_summary(df, consolidated_df, changes_log)

        df = consolidated_df.loc[consolidated_df.index.notna()]
        return df

    def FactSet_ICB_Mapping(self, df: pd.DataFrame) -> pd.DataFrame:
        msg = ""
        exit = False
        df = df.loc[(pd.isna(df['FactSet Ind']) == False)].copy()
        
        # Sauvegarde des colonnes originales
        df['ICB11 Industry'] = df[' Benchmark ICB Industry ']
        df['ICB20 Supersector'] = df[' Benchmark ICB Supersector ']
        
        # Lecture du fichier de mapping
        df_mapping = pd.read_excel(
            self.param_mapping_excel, 
            sheet_name='Mapping', 
            header=0, 
            na_values="@NA"
        )
        
        # Renommage des colonnes de mapping
        df_mapping.rename(columns={
            'Benchmark ICB Supersector 19': ' Benchmark ICB Supersector ',
            'Benchmark ICB Industry 11': ' Benchmark ICB Industry '
        }, inplace=True)

        # Préparation des DataFrames de mapping
        df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']].copy()
        df_FS_ICB.rename(columns={'Transco_ICB_19': 'ICB19'}, inplace=True)

        df_ICB_19_to_11 = df_mapping[['ICB_19_mapping', 'Transco_ICB_11']].copy()
        df_ICB_19_to_11.rename(columns={'Transco_ICB_11': 'ICB11'}, inplace=True)

        df_ICB_19_num = df_mapping.loc[
            df_mapping['ICB19_ID'].notna(),
            [' Benchmark ICB Supersector ', 'ICB19_ID']
        ].copy()
        
        df_ICB_11_num = df_mapping.loc[
            df_mapping['ICB11_ID'].notna(),
            [' Benchmark ICB Industry ', 'ICB11_ID']
        ].copy()

        # Validation des données
        if not set(df[' Benchmark ICB Supersector '].astype(str)).issubset(
            set(df_ICB_19_num[' Benchmark ICB Supersector '].astype(str))
        ):
            missing_icb19 = set(df[' Benchmark ICB Supersector ']) - set(df_ICB_19_num[' Benchmark ICB Supersector '])
            msg += f'ICB19 manquants : {"-".join(map(str, tuple(missing_icb19)))}. '
            exit = True
            
        if not set(df['FactSet Ind'].astype(str)).issubset(
            set(df_FS_ICB['FactSet Ind'].astype(str))
        ):
            missing_factset = set(df['FactSet Ind']) - set(df_FS_ICB['FactSet Ind'])
            msg += f'FactSet Ind manquants : {"-".join(map(str, tuple(missing_factset)))}. '
            exit = True
            
        if exit:
            raise ValueError(msg)

        # Application des mappings ICB19
        df = df.reset_index().merge(
            df_ICB_19_num, 
            how='left', 
            on=' Benchmark ICB Supersector '
        ).set_index('ISIN')
        
        df[' Benchmark ICB Supersector '] = df['ICB19_ID']
        
        df = df.reset_index().merge(
            df_FS_ICB, 
            how='left', 
            on='FactSet Ind'
        ).set_index('ISIN')
        
        df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = \
            df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values

        # Application des mappings ICB11
        df = df.reset_index().merge(
            df_ICB_11_num, 
            how='left', 
            on=' Benchmark ICB Industry '
        ).set_index('ISIN')
        
        df[' Benchmark ICB Industry '] = df['ICB11_ID']
        
        df = df.reset_index().merge(
            df_ICB_19_to_11, 
            how='left', 
            left_on=' Benchmark ICB Supersector ', 
            right_on="ICB_19_mapping"
        ).set_index('ISIN')
        
        df.loc[df[' Benchmark ICB Industry '] == 0, ' Benchmark ICB Industry '] = \
            df.loc[df[' Benchmark ICB Industry '] == 0, 'ICB11'].values

        # Nettoyage des colonnes temporaires
        df.drop(columns=['ICB19', 'ICB19_ID', 'ICB11', 'ICB11_ID', 'ICB_19_mapping'], inplace=True)

        # Conversion de la date
        df['Date'] = pd.to_datetime(df['Date'])
        df['Date'] = df['Date'] + pd.offsets.MonthBegin(1)              # 先转换为第二个月的第一天
        df['Date'] = df['Date'] + pd.offsets.MonthEnd(-1)   
        # Harmoniser les ICB19 Sector Names dans le screen
        df['ICB19 Supersector'] = df[' Benchmark ICB Supersector '].map(self.icb_supersectors_mapping)

        if "level_0" in df.columns:
            df = df.drop(columns="level_0")

        if "index" in df.columns:
            df = df.drop(columns="index")

        return df
    
    def create_backup(self, screen_agg: str, operation: str = "monthly_update") -> str:
        """Crée une sauvegarde de l'ancienne base"""
        old_base = pd.read_parquet(screen_agg)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_operation = "".join(
            char if char.isalnum() else "_" for char in operation.strip().lower()
        ).strip("_") or "backup"
        screen_path = Path(screen_agg)
        backup_path = (
            screen_path.parent
            / "backups"
            / screen_path.stem
            / f"{screen_path.stem}_{timestamp}_{safe_operation}{screen_path.suffix}"
        )
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        if 'Symbol' in old_base.columns:
            old_base['Symbol'] = old_base['Symbol'].astype("str")
        old_base.to_parquet(backup_path)
        return str(backup_path)

    @staticmethod
    def _ensure_isin_column(df: pd.DataFrame) -> pd.DataFrame:
        """统一把 ISIN 放回列中，便于后续按键校验和合并。"""
        if 'ISIN' in df.columns:
            return df.copy()
        if df.index.name == 'ISIN':
            return df.reset_index()
        raise ValueError("DataFrame 缺少 ISIN 列或 ISIN 索引")

    def validate_unique_keys(
        self,
        df: pd.DataFrame,
        key_columns: Sequence[str] = ('ISIN', 'Date'),
    ) -> None:
        """校验逻辑主键唯一。"""
        temp_df = self._ensure_isin_column(df)
        missing_columns = [column for column in key_columns if column not in temp_df.columns]
        if missing_columns:
            raise ValueError(f"缺少主键列: {missing_columns}")

        temp_df = temp_df.copy()
        if 'Date' in key_columns:
            temp_df['Date'] = pd.to_datetime(temp_df['Date'])

        duplicates = temp_df.duplicated(subset=list(key_columns), keep=False)
        if duplicates.any():
            sample = temp_df.loc[duplicates, list(key_columns)].head(5).to_dict('records')
            raise ValueError(f"发现重复主键 {tuple(key_columns)}: {sample}")

    def merge_returns_history(
        self,
        returns_history: pd.DataFrame,
        returns_delta: pd.DataFrame,
    ) -> pd.DataFrame:
        """按日期增量合并 returns，并保留每个交易日最后一版数据。"""
        history = returns_history.copy()
        delta = returns_delta.copy()

        history.index = pd.to_datetime(history.index)
        delta.index = pd.to_datetime(delta.index)

        merged = pd.concat([history, delta], axis=0, sort=False)
        merged = merged.sort_index()
        merged = merged.groupby(level=0, sort=True).last()
        merged.index.name = history.index.name or delta.index.name
        return merged

    def merge_monthly_snapshot(
        self,
        old_base: pd.DataFrame,
        new_base: pd.DataFrame,
    ) -> pd.DataFrame:
        """用新月度切片替换历史中相同月份的数据。"""
        old_df = self._ensure_isin_column(old_base)
        new_df = self._ensure_isin_column(new_base)

        old_df['Date'] = pd.to_datetime(old_df['Date'])
        new_df['Date'] = pd.to_datetime(new_df['Date'])

        target_dates = pd.Index(new_df['Date'].dropna().unique())
        if target_dates.empty:
            raise ValueError("new_base 中缺少有效 Date")

        old_df = old_df.loc[~old_df['Date'].isin(target_dates)]
        merged = pd.concat([old_df, new_df], ignore_index=True, sort=False)
        merged = merged.sort_values(['Date', 'ISIN']).drop_duplicates(
            subset=['ISIN', 'Date'],
            keep='last'
        )
        merged = merged.set_index('ISIN')
        self.validate_unique_keys(merged)
        return merged
    
    def add_score_multifacteur(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute les variables techniques à la base de données"""
        df = df.copy()
        
        # Multi Avg Percentile
        df['Multi Avg Percentile'] = df[[
            "Growth Avg Percentile", "LowVol Avg Percentile", 
            "Mom Avg Percentile", "Quality Avg Percentile", "Value Avg Percentile"
        ]].mean(axis=1)
        
        df['Multi Avg Percentile'] = df.groupby([
            'Date', ' Benchmark ICB Supersector ', 'Exchange Country Region'
        ])['Multi Avg Percentile'].transform(lambda x: x.rank(pct=True) * 10)
        
        return df
    
    def rebalance_weight_sum_to_1(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pour que la somme des poids des indices égale à 1 au lieu de 100
        """
        df[['Weight in DJ BROOKFIELD', 'Weight in GLOBAL INFRA',
        'Weight in GLOBAL REIT', 'Weight in MSCI ACWI', 'Weight in MSCI EM',
        'Weight in MSCI EUR SMALL', 'Weight in NIKKEI', 'Weight in NMX',
        'Weight in SP500', 'Weight in STOXX EUROPE 600', 'Weight in MSCI WORLD',
        'Weight in MSCI EUR', 'Weight in CAC40', 'Weight in EUROSTOXX50',
        'Weight in MSCI EMU', 'Weight in NASDAQ COMP', 'Weight in RUSSELL 2000',
        'Weight in MSCI EUR HIGH DIV']] = df.groupby("Date")[['Weight in DJ BROOKFIELD', 'Weight in GLOBAL INFRA',
                                                                                        'Weight in GLOBAL REIT', 'Weight in MSCI ACWI', 'Weight in MSCI EM',
                                                                                        'Weight in MSCI EUR SMALL', 'Weight in NIKKEI', 'Weight in NMX',
                                                                                        'Weight in SP500', 'Weight in STOXX EUROPE 600', 'Weight in MSCI WORLD',
                                                                                        'Weight in MSCI EUR', 'Weight in CAC40', 'Weight in EUROSTOXX50',
                                                                                        'Weight in MSCI EMU', 'Weight in NASDAQ COMP', 'Weight in RUSSELL 2000',
                                                                                        'Weight in MSCI EUR HIGH DIV']].transform(lambda x : x/x.sum())
        
        return df

    def add_univ_ml(self, screen):
        """
        基于 SP500 / STOXX EUROPE 600 / MSCI WORLD 构建 ML universes，并按日期归一化。
        """
        screen = screen.copy()
        world_weight = screen['Weight in MSCI WORLD'].where(screen['Weight in MSCI WORLD'] > 0)
        sp500_weight = screen['Weight in SP500'].where(screen['Weight in SP500'] > 0)
        stoxx_weight = screen['Weight in STOXX EUROPE 600'].where(screen['Weight in STOXX EUROPE 600'] > 0)

        mask_us_world = world_weight.notna() & (screen['Exchange Country Name'] == 'UNITED STATES')
        mask_eu_world = world_weight.notna() & (screen['Exchange Country Region'] == 'West Europe')
        mask_other_world = world_weight.notna() & ~mask_us_world & ~mask_eu_world

        print("Adding Univ ML EU......")
        screen['Weight in Univ ML EU'] = stoxx_weight.combine_first(world_weight.where(mask_eu_world))

        print("Adding Univ ML US......")
        screen['Weight in Univ ML US'] = sp500_weight.combine_first(world_weight.where(mask_us_world))

        print("Adding Univ ML OTHER......")
        screen['Weight in Univ ML OTHER'] = world_weight.where(mask_other_world)

        for column in ['Weight in Univ ML EU', 'Weight in Univ ML US', 'Weight in Univ ML OTHER']:
            total_weight = screen.groupby('Date')[column].transform('sum').replace(0, np.nan)
            screen[column] = screen[column] / total_weight

        return screen


    def calculate_risk_metrics(
        self,
        df_aggregate: pd.DataFrame,
        returns_df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Calcule toutes les métriques de risque"""
        df_returns = returns_df.copy() if returns_df is not None else pd.read_parquet(self.path_returns)
        df_returns_all = add_regional_benchmark_returns(df_returns, df_aggregate)
        df_returns_last = df_returns.iloc[-280:, :]
        
        risk_metrics = {
            'volatility': ewma_vol_window_rolling(df_returns_last),
            'var': df_returns_last.apply(calculate_rolling_var, axis=0).dropna(how="all"),
            'max_drawdown': calculate_rolling_max_drawdown_series(df_returns),
            'beta': beta(df_returns_all),
            'regional_beta': regional_beta(df_returns_all, df_aggregate),
            'beta_up': beta_up(df_returns_all),
            'beta_down': beta_down(df_returns_all)
        }
        
        return risk_metrics
    
    def prepare_risk_data_for_merge(self, risk_metrics: Dict[str, pd.DataFrame], 
                                    date_last: Any) -> Dict[str, pd.DataFrame]:
        """Prépare les données de risque pour la fusion"""
        risk_data = {}
        target_date = pd.Timestamp(date_last)
        
        for metric_name, df in risk_metrics.items():
            if metric_name not in RISK_COLUMN_MAPPING:
                raise KeyError(f"未知风险指标: {metric_name}")

            df_reset = df.reset_index().rename(columns={"index": "Date"})
            df_reset["Date"] = pd.to_datetime(df_reset["Date"])
            value_vars = [x for x in df_reset.columns if x != "Date"]
            
            df_melted = df_reset.melt(
                id_vars=["Date"], 
                value_vars=value_vars, 
                var_name="Company SEDOL"
            )
            
            df_melted = df_melted.rename(columns={"value": RISK_COLUMN_MAPPING[metric_name]})
            available_dates = df_melted["Date"].dropna()
            available_dates = available_dates[available_dates <= target_date]
            if available_dates.empty:
                risk_data[metric_name] = df_melted.iloc[0:0].copy()
                continue

            effective_date = available_dates.max()
            metric_slice = df_melted[df_melted["Date"] == effective_date].copy()
            metric_slice["Date"] = target_date
            risk_data[metric_name] = metric_slice
        
        return risk_data
    
    def merge_risk_data(self, df_aggregate: pd.DataFrame, 
                        risk_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """按目标月份键更新风险指标，避免对全量历史面板反复 merge。"""
        df_combined = df_aggregate.copy()
        index_agg = df_combined.index

        required_columns = ["Date", "Company SEDOL"]
        missing_columns = [column for column in required_columns if column not in df_combined.columns]
        if missing_columns:
            raise KeyError(f"主表缺少风险合并键: {missing_columns}")

        for column_name in RISK_COLUMN_MAPPING.values():
            if column_name not in df_combined.columns:
                df_combined[column_name] = np.nan

        screen_dates = pd.to_datetime(df_combined["Date"])
        screen_sedol = df_combined["Company SEDOL"].astype("string").str.strip()

        for metric_name, df_risk in risk_data.items():
            column_name = RISK_COLUMN_MAPPING.get(metric_name)
            if column_name is None:
                if df_risk.empty:
                    continue
                column_name = df_risk.columns[-1]

            if df_risk.empty:
                continue

            value_column = column_name if column_name in df_risk.columns else df_risk.columns[-1]
            risk_slice = df_risk[["Date", "Company SEDOL", value_column]].copy()
            risk_slice["Date"] = pd.to_datetime(risk_slice["Date"])
            risk_slice["Company SEDOL"] = risk_slice["Company SEDOL"].astype("string").str.strip()
            risk_slice = risk_slice.dropna(subset=["Date", "Company SEDOL"])
            if risk_slice.empty:
                continue

            risk_slice = risk_slice.drop_duplicates(subset=["Date", "Company SEDOL"], keep="last")
            target_dates = pd.DatetimeIndex(risk_slice["Date"].dropna().unique())
            target_mask = screen_dates.isin(target_dates).to_numpy()
            if not target_mask.any():
                continue

            lookup = risk_slice.set_index(["Date", "Company SEDOL"])[value_column]
            target_index = pd.MultiIndex.from_arrays(
                [screen_dates[target_mask].to_numpy(), screen_sedol[target_mask].to_numpy()],
                names=["Date", "Company SEDOL"],
            )
            mapped_values = lookup.reindex(target_index).to_numpy()
            existing_values = df_combined.loc[target_mask, column_name].to_numpy()
            use_new = pd.notna(mapped_values)
            existing_values[use_new] = mapped_values[use_new]
            df_combined.loc[target_mask, column_name] = existing_values

        df_combined.index = index_agg
        return df_combined
    
    def save_results(self, df_combined: pd.DataFrame, screen_agg: str):
        """Sauvegarde tous les résultats"""
        screen_path = Path(screen_agg)
        screen_path.parent.mkdir(parents=True, exist_ok=True)
        df_combined = drop_deprecated_em_cluster_columns(df_combined)
        if 'Weight in MSCI US' in df_combined.columns:
            df_combined = df_combined.drop(columns=['Weight in MSCI US'])
        if 'Symbol' in df_combined.columns:
            df_combined['Symbol'] = df_combined['Symbol'].astype("str")
        # Screen agrégé principal
        df_combined.to_parquet(screen_path)
        # Screen 5Y
        date_screen_5y = df_combined['Date'].max() + relativedelta.relativedelta(years=-5)
        screen_5y = df_combined[df_combined['Date'] >= date_screen_5y]
        screen_5y.to_parquet(screen_path.with_name(f"{screen_path.stem}_5Y{screen_path.suffix}"))
        # Daily weights
        # self._update_daily_weights(new_base, path_daily)
    
    def _update_daily_weights(self, new_base: pd.DataFrame, path_daily: str):
        """Met à jour les poids journaliers"""
        daily_weights = pd.read_parquet(path_daily)
        new_base.reset_index(inplace=True)
        new_base_wo_na = new_base.loc[
            (new_base['Company SEDOL'].notna()) * (new_base['ISIN'].notna())
        ]
        
        date_ = new_base_wo_na['Date'].iloc[0]
        daily_weights = daily_weights[daily_weights.index < date_]
        new_base_wo_na = new_base_wo_na[['Date'] + list(daily_weights.columns)].set_index('Date')
        
        daily_weights = pd.concat([daily_weights, new_base_wo_na], axis=0, ignore_index=False)
        daily_weights.to_parquet(path_daily)
        # daily_weights['Symbol'] = daily_weights['Symbol'].astype("str")

    def _build_perf_frame(
        self,
        returns_df: pd.DataFrame,
        target_dates: Iterable[pd.Timestamp],
    ) -> pd.DataFrame:
        """只为目标月度日期生成收益表现列。"""
        target_index = pd.DatetimeIndex(pd.to_datetime(list(target_dates))).dropna().unique().sort_values()
        if len(target_index) == 0:
            return pd.DataFrame(columns=['Date', 'Company SEDOL', *PERF_WINDOWS.keys()])

        returns = returns_df.copy()
        returns.index = pd.to_datetime(returns.index)
        returns = returns.sort_index()
        returns.columns = returns.columns.astype(str)

        nav = (1 + returns).cumprod()
        current_nav = nav.reindex(target_index, method='ffill')

        perf_frames = []
        for column_name, lag in PERF_WINDOWS.items():
            lagged_nav = nav.shift(lag).reindex(target_index, method='ffill')
            perf_wide = current_nav.div(lagged_nav).sub(1)
            perf_long = (
                perf_wide.reset_index()
                .rename(columns={'index': 'Date'})
                .melt(id_vars='Date', var_name='Company SEDOL', value_name=column_name)
            )
            perf_frames.append(perf_long)

        perf_data = perf_frames[0]
        for frame in perf_frames[1:]:
            perf_data = perf_data.merge(frame, on=['Date', 'Company SEDOL'], how='outer')

        perf_data['Company SEDOL'] = perf_data['Company SEDOL'].astype(str)
        return perf_data

    def add_perf(
        self,
        screen_histo,
        target_dates: Optional[Iterable[pd.Timestamp]] = None,
        returns_df: Optional[pd.DataFrame] = None,
    ):
        """
        cette fonction va ajouter les perf de 5D, 1M, 3M, 6M dans screen_agg
        """
        screenFS2 = self._ensure_isin_column(screen_histo)
        screenFS2['Date'] = pd.to_datetime(screenFS2['Date'])
        screenFS2['Company SEDOL'] = screenFS2['Company SEDOL'].astype(str)

        if target_dates is None:
            target_index = pd.DatetimeIndex(screenFS2['Date'].dropna().unique()).sort_values()
        else:
            target_index = pd.DatetimeIndex(pd.to_datetime(list(target_dates))).dropna().unique().sort_values()

        if len(target_index) == 0:
            screenFS2.set_index('ISIN', inplace=True)
            return screenFS2

        returns = returns_df.copy() if returns_df is not None else pd.read_parquet(self.path_returns)
        perf_data = self._build_perf_frame(returns, target_index)
        if perf_data.empty:
            screenFS2.set_index('ISIN', inplace=True)
            return screenFS2

        for column_name in PERF_WINDOWS:
            if column_name not in screenFS2.columns:
                screenFS2[column_name] = np.nan

        screenFS2 = screenFS2.merge(
            perf_data,
            on=['Date', 'Company SEDOL'],
            how='left',
            suffixes=('', '_new')
        )

        for column_name in PERF_WINDOWS:
            new_column = f'{column_name}_new'
            if new_column in screenFS2.columns:
                screenFS2[column_name] = screenFS2[new_column].combine_first(screenFS2[column_name])
                screenFS2 = screenFS2.drop(columns=[new_column])

        screenFS2.set_index("ISIN", inplace=True)
        return screenFS2







def get_bench_weight(new_screen_excel, region, output_dir, param_mapping_excel):

    df_mapping = pd.read_excel(param_mapping_excel, sheet_name='Mapping', header = 0, na_values="@NA")
    df_mapping.rename(columns={'Benchmark ICB Supersector 19' : ' Benchmark ICB Supersector '}, inplace= True)
    df_FS_ICB = df_mapping[['FactSet Ind', 'Transco_ICB_19']]
    df_FS_ICB.rename(columns={'Transco_ICB_19' : 'ICB19'}, inplace= True)
    df_ICB_num = df_mapping.loc[df_mapping['ICB19_ID'].notna(),[' Benchmark ICB Supersector ','ICB19_ID']]

    df = pd.read_excel(new_screen_excel, header = 0, skiprows=[0,1,2,3,5], index_col = 4, na_values=["@NA", "#N/A"])

    if 'Benchmark Market Value Millions in EUR ' not in df.columns :
        df = df.rename(columns = {'Benchmark Market Value Millions in EUR' : "Benchmark Market Value Millions in EUR "})


    df = df[~df.index.duplicated(keep='first')]
    df = df.loc[df.index.notna()]
    df = df.loc[(df['Weight in MSCI ACWI'] > 0) & (pd.isna(df['FactSet Ind']) == False)] 
    date = pd.to_datetime(df['Date']).iloc[0] + relativedelta.relativedelta(months=1,day=1)
    
    fit = np.polyfit(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']) == False, 'Weight in MSCI ACWI'],df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']) == False, 'Benchmark Market Value Millions in EUR '], deg = 1)
    func = np.poly1d(fit)
    df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']),'Benchmark Market Value Millions in EUR '] = func(df.loc[pd.isna(df['Benchmark Market Value Millions in EUR ']),'Weight in MSCI ACWI'])

    if region == 'Europe':
        df = df.loc[(df['Weight in STOXX EUROPE 600'] > 0)]
        output_file = output_dir + "/Bench EU.xlsx"
    elif region == 'US':
        df = df.loc[df["Exchange Country Name"] == 'UNITED STATES']
        output_file = output_dir +"/Bench US.xlsx"
    elif region == 'Japan':
        df = df.loc[df["Exchange Country Name"] == 'JAPAN']
        output_file = output_dir + "/Bench JP.xlsx"

    df = df.reset_index().merge(df_ICB_num, how='left', on = ' Benchmark ICB Supersector ').set_index('ISIN')
    df[' Benchmark ICB Supersector '] = df['ICB19_ID']
    df = df.reset_index().merge(df_FS_ICB, how='left', on = 'FactSet Ind').set_index('ISIN')
    df.loc[df[' Benchmark ICB Supersector '] == 0, ' Benchmark ICB Supersector '] = df.loc[df[' Benchmark ICB Supersector '] == 0, 'ICB19'].values
    weight_secto_bench = (df.groupby(' Benchmark ICB Supersector ')['Weight in MSCI ACWI'].sum() / df['Weight in MSCI ACWI'].sum())

    header = ['Automobiles & Parts', 'Banks', 'Basic Resources', 'Chemicals', 'Construction & Materials', 'Financial Services', 'Food & Beverage', 'Health Care',
            'Industrial Goods & Services', 'Insurance', 'Media', 'Energy', 'Personal & Household Goods', 'Real Estate', 'Retail', 'Technology', 'Telecommunications',
            'Travel & Leisure', 'Utilities']
    return_df = weight_secto_bench.reset_index()
    return_df['Weight in MSCI ACWI'] = weight_secto_bench.values
    return_df.columns = [' Benchmark ICB Supersector ', date]
    return_df = return_df.set_index(return_df[' Benchmark ICB Supersector '].values.reshape(-1))[date].to_frame().transpose()
    return_df.columns = header

    old_bench = pd.read_excel(output_file, index_col=0, header = 0)
    with pd.ExcelWriter(output_file,datetime_format = 'dd/mm/yyyy', date_format = 'dd/mm/yyyy') as writer:
        pd.concat([old_bench, return_df]).to_excel(writer,index = True)


def maj_all_bench(new_screen_excel, output_dir, param_mapping_excel):

    get_bench_weight(new_screen_excel, 'Europe', output_dir, param_mapping_excel)
    get_bench_weight(new_screen_excel, 'US', output_dir, param_mapping_excel)
    get_bench_weight(new_screen_excel, 'Japan', output_dir, param_mapping_excel)



def check_missing_values(last_screen, 
                        screen, 
                        window_histo=3):


    # --- 1) Copie + Date en datetime (granularité jour) ---
    df = screen.copy()
    df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.normalize()

    # (Optionnel) considérer certaines chaînes comme manquantes
    # df = df.replace({'': np.nan, ' ': np.nan})

    # --- 2) % de valeurs manquantes par Date et par colonne ---
    cols = [c for c in last_screen.columns if c not in ('Date', 
                                                        'Benchmark Market Value Millions in EUR', 
                                                        'Benchmark Identifier -  SEDOLCHK', 
                                                        'Benchmark Country English',
                                                        'Constituent Weight SOM',
                                                        )]

    miss_pct_daily = (
        df[cols]
        .isna()
        .groupby(df['Date'])   # NaT dans 'Date' exclus automatiquement
        .mean()                # True=1, False=0 -> moyenne = part de manquants
        .sort_index()
    )

    # --- 3) Fenêtre historique: 5 ans glissants avant la dernière date (exclue) ---
    last_date = miss_pct_daily.index.max()
    window_start = last_date - pd.DateOffset(years=window_histo)

    hist = miss_pct_daily.loc[
        (miss_pct_daily.index >= window_start) &
        (miss_pct_daily.index < last_date)
    ]


    # --- 4) Calculs (toutes colonnes) ---
    hist_mean = hist.mean(axis=0)           # moyenne historique (0–1)
    last_pct  = miss_pct_daily.loc[last_date]  # % manquants dernière date (0–1)

    comp_nan = pd.DataFrame({
        'pct_manq_hist_%'       : hist_mean * 100,
        'pct_manq_dern_date_%'  : last_pct * 100
    })

    # Écart en points de pourcentage
    comp_nan['ecart_pts'] = comp_nan['pct_manq_dern_date_%'] - comp_nan['pct_manq_hist_%']

    # Tri par variation en points de %
    comp_nan = comp_nan.sort_values('ecart_pts', ascending=False)

    seuil = 5  # points de %
    comp_nan_aff = comp_nan.round({
        'pct_manq_hist_%'      : 2,
        'pct_manq_dern_date_%' : 2,
        'ecart_pts'            : 2
    })

    comp_nan_aff = comp_nan_aff.head(10) # Garder seulement les top 10 manquants pour l'affichage

    def style_souligner_lignes(row):
        # row est une Series (une ligne)
        if row['ecart_pts'] > seuil:
            # underline + gras + léger fond
            return ['text-decoration: underline; font-weight: 700; background-color: #fff3cd'] * len(row)
        return [''] * len(row)

    styled = (
        comp_nan_aff
        .style
        .apply(style_souligner_lignes, axis=1)
        .format('{:.2f}')
        .set_caption(f"Lignes soulignées si écart > {seuil} points de pourcentage")
    )

    # En notebook:
    display(styled)



    # --- 5) Affichage ---
    effective_start = hist.index.min()
    effective_end   = hist.index.max()  # dernière date de la fenêtre (exclut last_date)

    print(f"Comparaison des % de valeurs manquantes (dernière date vs historique {window_histo} ans) :")
    print(
        f"Dernière date analysée : {last_date.date()} | "
        f"Période historique utilisée : [{effective_start.date()} ; {effective_end.date()}] "
        f"({hist.shape[0]} dates distinctes)"
    )



def check_screen_index_in_returns_columns(screen, returns):
    # sedols = pd.Index(screen["Company SEDOL"].dropna().unique())
    missing = sedols.difference(returns.columns)
    if missing.empty:
        print("All SEDOL in the last date of screen are in returns")
        return
    else:
        print("SEDOL in screen but no existing in returns")
        print(f"SEDOL List : {missing}")
        return missing












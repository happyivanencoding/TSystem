import pandas as pd
from pathlib import Path


def _config_base_dir(config_module):
    config_file = getattr(config_module, "__file__", None)
    if config_file:
        return Path(config_file).resolve().parents[1]
    return Path.cwd()


def _resolve_config_path(config_module, primary_key, fallback_key=None):
    params = config_module.params_principal
    keys = [primary_key]
    if fallback_key:
        keys.append(fallback_key)
    checked = []
    base_dir = _config_base_dir(config_module)
    for key in keys:
        raw = params.get(key)
        if not raw:
            continue
        path = Path(raw)
        if not path.is_absolute():
            path = base_dir / path
        checked.append(str(path))
        if path.exists():
            return path
    raise FileNotFoundError(f"Aucun fichier ML disponible pour {primary_key}; chemins testes: {checked}")

################ FOR EXCEL SHAP ################
def combine_score_shap(config_EU, config_US):
    
    score_EU = pd.read_parquet(_resolve_config_path(config_EU, 'score_ml_path', 'score_ml_backtest_path'))
    score_US = pd.read_parquet(_resolve_config_path(config_US, 'score_ml_path', 'score_ml_backtest_path'))
    # score_OTHER = pd.read_parquet(config_OTHER.params_principal['score_ml_path'])

    shap_EU = pd.read_parquet(_resolve_config_path(config_EU, 'shap_path', 'shap_backtest_path'))
    shap_US = pd.read_parquet(_resolve_config_path(config_US, 'shap_path', 'shap_backtest_path'))
    # shap_OTHER = pd.read_parquet(config_OTHER.params_principal['shap_path'])


    # for being sure that EU == US == OTHER
    # Collect the maximum dates from each DataFrame
    max_dates = {
        score_EU['Date'].max(),
        score_US['Date'].max(),
        # score_OTHER['Date'].max(),
        shap_EU['Date'].max(),
        shap_US['Date'].max(),
        # shap_OTHER['Date'].max(),
    }

    # All max dates are equal iff the set has only one element 
    if len(max_dates) == 1:
        print("All max dates are identical")
    else:
        return('Max dates are not identical, please check')

    # Choisir seulement la dernière date pour le sscreen
    last_date = shap_EU['Date'].max() 

    shap_EU = shap_EU[shap_EU['Date'] == last_date]
    shap_US = shap_US[shap_US['Date'] == last_date]
    # shap_OTHER = shap_OTHER[shap_OTHER['Date'] == last_date]

    score_EU = score_EU[score_EU['Date'] == last_date]
    score_US = score_US[score_US['Date'] == last_date]
    # score_OTHER = score_OTHER[score_OTHER['Date'] == last_date]

    # Ajout les labels dans dataframe shap values
    shap_US = shap_US.merge(score_US[["3.0M y_pred", "6.0M y_pred", "3.0M y_pred_scaled", "6.0M y_pred_scaled", "average_prediction", "Score ML"]], how="left", left_on="ISIN", right_on="ISIN")
    shap_EU = shap_EU.merge(score_EU[["3.0M y_pred", "6.0M y_pred", "3.0M y_pred_scaled", "6.0M y_pred_scaled", "average_prediction", "Score ML"]], how="left", left_on="ISIN", right_on="ISIN")
    # shap_OTHER = shap_OTHER.merge(score_OTHER[["3.0M y_pred", "6.0M y_pred", "3.0M y_pred_scaled", "6.0M y_pred_scaled", "average_prediction", "Score ML"]], how="left", left_on="ISIN", right_on="ISIN")

    shap_total = pd.concat([shap_US, shap_EU], axis=0)

    # Extrait le 3/6 dans 3M/6M, car plus tard, on utilise ces chiffres pour calculer un return 1M
    shap_total['period'] = shap_total['period'].str.replace('M', '', regex=False)
    shap_total['period'] = shap_total['period'].astype(float).astype(int)

    # Les cols de contribution qui vont être divisés 
    shap_cols = ['Dividend Avg Percentile',
                'Value Avg Percentile', 'Quality Avg Percentile', 'Mom Avg Percentile',
                'LowVol Avg Percentile', 'Growth Avg Percentile',
                'Value Avg Percentile_change_1M', 'Quality Avg Percentile_change_1M',
                'Growth Avg Percentile_change_1M', 'Value Avg Percentile_change_3M',
                'Quality Avg Percentile_change_3M', 'Growth Avg Percentile_change_3M',
                'Value Avg Percentile_change_6M', 'Quality Avg Percentile_change_6M',
                'Growth Avg Percentile_change_6M', 'Value Avg Percentile_change_12M',
                'Quality Avg Percentile_change_12M', 'Growth Avg Percentile_change_12M',
                'Sector 1', 'Sector 2', 'Sector 3', 'Sector 4', 'Sector 5', 'Sector 6',
                'Sector 7', 'Sector 8', 'Sector 9', 'Sector 10', 'Sector 11',
                'Sector 12', 'Sector 13', 'Sector 14', 'Sector 15', 'Sector 16',
                'Sector 17', 'Sector 18', 'Sector 19']

    shap_total[shap_cols] = shap_total[shap_cols].div(shap_total['period'], axis=0)


    agg_dict = {col: 'mean' for col in shap_cols}          # average for the SHAP columns

    for col in shap_total.columns:
        if col not in shap_cols and col != 'ISIN':         # exclude the grouping key
            agg_dict[col] = 'first'

    shap_grouped = shap_total.groupby('ISIN').agg(agg_dict)
    shap_grouped['Sum Shap'] = shap_grouped[shap_cols].sum(axis=1)
    shap_grouped[shap_cols] = shap_grouped[shap_cols].div(shap_grouped['Sum Shap'], axis=0).mul(shap_grouped['average_prediction'], axis=0) # Contrib features
    shap_grouped = shap_grouped.reset_index(drop=False)
    return shap_grouped

def process_outlier_rows_only(df: pd.DataFrame, columns: list, sum_col: str):
    soft_mltiplier = 7.5
    hard_mltiplier = 10
    # --- calculer les seuils ---
    thresholds = {}
    for col in columns:
        Q1 = df[col].quantile(0.25)
        Q3 = df[col].quantile(0.75)
        IQR = Q3 - Q1
        thresholds[col] = {
            'soft_lower': Q1 - soft_mltiplier * IQR,
            'soft_upper': Q3 + soft_mltiplier * IQR,
            'hard_lower': Q1 - hard_mltiplier * IQR,
            'hard_upper': Q3 + hard_mltiplier * IQR,
        }

    # list pour sauvegarder le result final
    final_rows = []

    # --- filter par ligne et transformation ---
    for idx, row in df.iterrows():
        current_values = row[columns].to_dict()
        
        # --- voir si c'est une ligne abnormale ---
        is_outlier_row = False
        for col in columns:
            val = current_values[col]
            if val < thresholds[col]['soft_lower'] or val > thresholds[col]['soft_upper']:
                is_outlier_row = True
                break # des qu'il y a une valeur abnormale, c'est taggé comme abnormal

        # --- application de diminiation ---
        if not is_outlier_row:
            # pour les lignes normales, garder les valeurs originales
            final_rows.append(current_values)
            continue # treat la prochaine ligne
        
        # pour les lignes abnormales, transformation - diminuation
        # 1. diminuation en gardant la ratio entre les columns
        k_factors = []
        for col in columns:
            val = current_values[col]
            soft_lower, soft_upper = thresholds[col]['soft_lower'], thresholds[col]['soft_upper']
            if val < soft_lower or val > soft_upper:
                if abs(val) < 1e-9: continue # pour ne pas diviser par 0
                limit = soft_upper if val > soft_upper else soft_lower
                k_factors.append(limit / val)  # exemple, outlier = 300, soft_upper=100, k_factor = 100/300 = 0.33333, toutes les columns doivent être divisées par 3 
        
        k_row = min(k_factors) if k_factors else 1.0
        corrected_values = {c: v * k_row for c, v in current_values.items()}
        
        # 2. check le delta pour la somme des variables (Y_predit)
        y_original = row[sum_col]
        delta = y_original - sum(corrected_values.values())
        
        # 3. itteration
        for _ in range(10):
            if abs(delta) < 1e-9: break # pour ne pas diviser par 0
            

            adjustable_cols = [c for c, v in corrected_values.items() if (delta > 0 and v < thresholds[c]['hard_upper']) or (delta < 0 and v > thresholds[c]['hard_lower'])]
            if not adjustable_cols: break

            abs_sum = sum(abs(corrected_values[c]) for c in adjustable_cols)
            weights = {c: (abs(corrected_values[c]) / abs_sum) if abs_sum > 1e-9 else (1.0 / len(adjustable_cols)) for c in adjustable_cols}

            total_actual_adjustment = 0
            for col in adjustable_cols:
                proposed_adj = delta * weights[col]
                if delta > 0:
                    room = thresholds[col]['hard_upper'] - corrected_values[col] # ce que on peut ajuster au max
                    actual_adj = min(proposed_adj, room) # réel ajustement
                else:
                    room = thresholds[col]['hard_lower'] - corrected_values[col]
                    actual_adj = max(proposed_adj, room)
                
                corrected_values[col] += actual_adj
                total_actual_adjustment += actual_adj

            delta -= total_actual_adjustment
            
        final_rows.append(corrected_values)

    # créer un nouveau df pour sauvegarder le resultat
    result_df = df.copy()
    result_df[columns] = pd.DataFrame(final_rows, index=df.index)
        
    return result_df


def closest_date_in_df(target_date, df, date_col="Date"):
    df = df.reset_index()
    df_dates = pd.to_datetime(df[date_col])
    target_ts = pd.to_datetime(target_date)
    idx = (df_dates - target_ts).abs().idxmin()
    return df.loc[idx, date_col]

def add_reco_analyst_multi_facteur(path_screen, path_ciq, last_date):
    screen = pd.read_parquet(path_screen)
    date = closest_date_in_df(last_date, screen)
    screen = screen[screen['Date'] == date]

    ciq = pd.read_parquet(path_ciq)
    if ciq.index.name != "ISIN":
        ciq = ciq.set_index('ISIN')
    ciq = ciq[ciq['Date'] == date]

    # Nettoyer le column, garder seulement "BUY" "SELL"...
    ciq['Reco Analyst'] = ciq['Reco Analyst'].str.split('(',expand=True)[0]
    ciq['Reco Analyst'] = ciq['Reco Analyst'].str.strip()

    screen_new = screen.merge(ciq['Reco Analyst'],
                how ="left",
                left_index=True, right_index=True)

    df_screen = screen_new[['Weight in MSCI WORLD', 'ICB19 Supersector', "Name", 
                            "Exchange Country Region", "Exchange Country Name", 
                            "ESG_ANALYST_SCORE", "Reco Analyst", 'Multi Avg Percentile', 
                            'PE LTM', 'EPS Growth FY1', 'ROE avg FY0', 
                            'Oper Margin', 
                            'DVD Yield FY0', 'Earns Yield FY0', 'CarbonIntensity_Sales']]
    df_screen['Weight in MSCI WORLD'] = df_screen['Weight in MSCI WORLD']/100
    df_screen = df_screen.reset_index()
    df_screen = df_screen[df_screen['Weight in MSCI WORLD'] > 0]

    return df_screen

def add_raison_repechage(df, path_ptf_world):
    ptf = pd.read_parquet(path_ptf_world)
    ptf = ptf[ptf["Date"] == ptf["Date"].max()]

    df = df.merge(ptf[["PTF", "ISIN", "Weight", "Raison Repechage"]],                                 
                                how="left",
                                left_on="ISIN",
                                right_on="ISIN"
                                )
                                
    return df

def rename_cols_1(df_total):
    rename_map = {
        "Exchange Country Region": 'Region',
        'Exchange Country Name': 'Country',
        'ICB19 Supersector':          'Sector',
        "ESG_ANALYST_SCORE":       "Score ESG",
        'DVD Yield FY0' : 'DVD Yield',
        'Earns Yield FY0' : 'Earnings Yield',
        'ROE avg FY0' : 'ROE',
        'PE LTM' : 'PE',
        'CarbonIntensity_Sales' : 'Carbon Intensity',
        'average_prediction':         'Predicted Forward Return 1M',
        'Multi Avg Percentile' : "Multi Score"
    }

    df_total = df_total.rename(columns=rename_map)

    return df_total

def rename_cols_2(df_total):
    rename_map = {}

    for col in df_total.columns:
        if 'Avg Percentile_change_' in col:
            # e.g.  "Dividend Avg Percentile_change_1M" → "Dividend Change_1M"
            new_col = col.replace('Avg Percentile_change_', 'Change_')
            rename_map[col] = new_col

        elif 'Avg Percentile' in col:
            # e.g.  "Dividend Avg Percentile" → "Dividend Contrib"
            new_col = col.replace(' Avg Percentile', ' Contrib')
            rename_map[col] = new_col

    df_total = df_total.rename(columns=rename_map)

    return df_total


def get_factos():
    from Config import config_EU, config_US, config_OTHER
    cols_list_original_data = [
        'Value Avg Percentile',
        'Value Avg Percentile_change_1M',
        'Value Avg Percentile_change_3M',
        'Value Avg Percentile_change_6M',
        'Value Avg Percentile_change_12M',

        'Quality Avg Percentile',
        'Quality Avg Percentile_change_1M',
        'Quality Avg Percentile_change_3M',
        'Quality Avg Percentile_change_6M',
        'Quality Avg Percentile_change_12M',

        'Growth Avg Percentile',
        'Growth Avg Percentile_change_1M',
        'Growth Avg Percentile_change_3M',
        'Growth Avg Percentile_change_6M',
        'Growth Avg Percentile_change_12M',
        
        'Dividend Avg Percentile',
        'Mom Avg Percentile',
        'LowVol Avg Percentile'
        ]

    screen_EU = pd.read_parquet(_resolve_config_path(config_EU, 'df_features_path', 'df_features_backtest_path'))
    screen_US = pd.read_parquet(_resolve_config_path(config_US, 'df_features_path', 'df_features_backtest_path'))
    # screen_OTHER = pd.read_parquet(config_OTHER.params_principal.get('df_features_path'))

    # ------------------------------------------------------------------
    # EUROPE
    # ------------------------------------------------------------------
    screen_EU = screen_EU.reset_index()
    screen_EU = screen_EU[screen_EU['Date'] == screen_EU['Date'].max()]
    screen_EU = screen_EU.set_index("ISIN")
    screen_EU = screen_EU[cols_list_original_data]

    # ------------------------------------------------------------------
    # US
    # ------------------------------------------------------------------
    screen_US = screen_US.reset_index()                      # make the current index a column
    screen_US = screen_US[screen_US['Date'] == screen_US['Date'].max()]  # keep only the most recent date
    screen_US = screen_US.set_index("ISIN")                 # set ISIN as the new index
    screen_US = screen_US[cols_list_original_data]          # keep only the original columns

    # ------------------------------------------------------------------
    # OTHER
    # ------------------------------------------------------------------
    # screen_OTHER = screen_OTHER.reset_index()
    # screen_OTHER = screen_OTHER[screen_OTHER['Date'] == screen_OTHER['Date'].max()]
    # screen_OTHER = screen_OTHER.set_index("ISIN")
    # screen_OTHER = screen_OTHER[cols_list_original_data]


    screen_original_data = pd.concat([screen_EU, screen_US], axis=0)
    return screen_original_data


def rename_cols_3(df):

    rename_map = {}
    for col in df.columns:
        if 'Avg Percentile_change_' in col:
            # e.g.  "Dividend Avg Percentile_change_1M" → "Dividend Change_1M"
            new_col = col.replace('Avg Percentile_change_', 'Score Change_')
            rename_map[col] = new_col

        elif 'Avg Percentile' in col:
            # e.g.  "Dividend Avg Percentile" → "Dividend Score"
            new_col = col.replace('Avg Percentile', 'Score')
            rename_map[col] = new_col

    df = df.rename(columns=rename_map)
    df = df.reset_index()

    return df


def add_esg_list_noire(path_list_noire, df):
    from Codes.BacktestEngine import read_liste_noire
    
    liste_noire = read_liste_noire(path_list_noire, [], [])
    df['Blacklisted'] = df['ISIN'].isin(liste_noire)
    print(f"il y a en total {df['Blacklisted'].sum()} titres dans la liste d'exclusion du groupe.")
    return df

def get_list_exclusion():
    from Config import config_EU, config_US, config_OTHER
    list_exclu_EU = pd.read_parquet(_resolve_config_path(config_EU, 'list_exclusion_path'))
    list_exclu_US = pd.read_parquet(_resolve_config_path(config_US, 'list_exclusion_path'))
    # list_exclu_OTHER = pd.read_parquet(config_OTHER.params_principal['list_exclusion_path'])

    last_date = list_exclu_EU['Date'].max()
    
    list_exclu_EU = list_exclu_EU[list_exclu_EU['Date'] == last_date]
    list_exclu_US = list_exclu_US[list_exclu_US['Date'] == last_date]
    # list_exclu_OTHER = list_exclu_OTHER[list_exclu_OTHER['Date'] == last_date]

    list_exclu_total = pd.concat([list_exclu_EU, list_exclu_US], axis=0)
    return list_exclu_total



################ FOR MATRICES DE CONFUSION ################
from sklearn.metrics import confusion_matrix
import plotly.graph_objects as go
def assign_quantiles(group, n_quantiles, labels, columns_to_quantile):
    """Assigns quantile labels to selected columns in a date group."""
    quantile_map = {
        'Score ML': 'ML_Quantile',
        'Multi Avg Percentile': 'Multi_Quantile',
        'Weighted 1.0M return': 'Return_Quantile'
    }

    for col in columns_to_quantile:
        if col in quantile_map:
            group[quantile_map[col]] = pd.qcut(group[col], q=n_quantiles, labels=labels, duplicates='drop')

    return group



def calculate_monitoring_metrics(group, labels):
    """Calculates monitoring metrics from a single date group."""
    n_quantiles = len(labels)
    # Calculate the raw count confusion matrix (non-normalized)
    cm_raw = confusion_matrix(group['Multi_Quantile'], group['ML_Quantile'], labels=labels)
    total_stocks = cm_raw.sum()
    if total_stocks == 0:
        return None

    # Metric 1: Overall Hit Rate (Diagonal Strength)
    hit_k0 = np.diag(cm_raw, k=0).sum()
    hit_k1 = np.diag(cm_raw, k=1).sum()
    hit_k_minus_1 = np.diag(cm_raw, k=-1).sum()
    expanded_hit_sum = hit_k0 + hit_k1 + hit_k_minus_1

    overall_hit_rate = expanded_hit_sum / total_stocks


    return pd.Series({
        'overall_hit_rate': overall_hit_rate
    })

def transform_return_data(historical_data, return_col_chosen="Weighted 1.0M return", market_cap_adjusted=False):
    # Weighted Transformation (region et sector neutral + return absolu (ttr est calculé basé sur return absolu))
    historical_data["Relative 1.0M return"] = (historical_data['Relative 3.0M return'].div(3) + historical_data['Relative 6.0M return'].div(6)).div(2)

    if market_cap_adjusted:
        # Region et Secto Neutre
        historical_data["Weighted 1.0M return"] = historical_data["Stock 1.0M return"].mul(historical_data.groupby(["Date", " Benchmark ICB Supersector "])['Weight in MSCI WORLD'].transform(lambda x: x/x.sum()))
        historical_data["Weighted 3.0M return"] = historical_data["Stock 3.0M return"].mul(historical_data.groupby(["Date", " Benchmark ICB Supersector "])['Weight in MSCI WORLD'].transform(lambda x: x/x.sum()))
        historical_data["Weighted 6.0M return"] = historical_data["Stock 6.0M return"].mul(historical_data.groupby(["Date", " Benchmark ICB Supersector "])['Weight in MSCI WORLD'].transform(lambda x: x/x.sum()))
    else:
        # Non Neutralisation
        historical_data["Weighted 1.0M return"] = historical_data["Relative 1.0M return"]
        historical_data["Weighted 3.0M return"] = historical_data["Relative 3.0M return"]
        historical_data["Weighted 6.0M return"] = historical_data["Relative 6.0M return"]

    historical_data = historical_data.dropna(subset=return_col_chosen)
    historical_data = historical_data[historical_data[return_col_chosen] != 0]
    return historical_data

def system_alert_hit_rate(historical_metrics, latest_classified, LABELS):
    # Calculate the historical baseline (mean and standard deviation)
    baseline_mean = historical_metrics.mean()
    baseline_std = historical_metrics.std()

    # Define thresholds
    std_threshold = 2
    thresholds = {
        'overall_hit_rate': baseline_mean['overall_hit_rate'] - std_threshold * baseline_std['overall_hit_rate']
    }

    # Calculate metrics for the latest date
    latest_metrics = calculate_monitoring_metrics(latest_classified, LABELS)

    # Check if any alerts are triggered
    alerts = []
    if latest_metrics['overall_hit_rate'] < thresholds['overall_hit_rate']:
        alerts.append(f"🔴 ALERT: [Overall Hit Rate] is too low! "
                    f"Current value: {latest_metrics['overall_hit_rate']:.2%}, "
                    f"below threshold: {thresholds['overall_hit_rate']:.2%}")


    # --- 5. Output Alerts and Visualization ---
    latest_date = latest_classified['Date'][0]
    print("="*65)
    print(f"Model Monitoring Alert System - Date: {latest_date.date()}")
    print("="*65)
    if not alerts:
        print("✅ System Status Normal: All metrics are within their thresholds.")
    else:
        for alert in alerts:
            print(alert)
    print("-"*65)
    print("Detailed Metric Comparison:")
    print(f" - Overall Hit Rate: Current {latest_metrics['overall_hit_rate']:.2%} vs. Historical Avg {baseline_mean['overall_hit_rate']:.2%}")
    print("="*65)


def heatmap_trace(z, labels, title, cmap, zmin=None, zmax=None, zmid=None, fmt=":.2%"):
    """
    Parameters
    ----------
    z     : 2‑D array, the matrix to plot
    labels: list of tick labels (same length as the matrix)
    title : subplot title
    cmap  : Plotly color‑scale name (e.g. 'Blues', 'RdBu')
    zmin/zmax : optional limits for the color scale
    zmid   : optional center (for diverging scales)
    fmt    : format string for the annotations (default: percent)
    """
    # Convert the matrix into a *text* matrix that Plotly will show in each cell
    #  → we use `texttemplate` to format the values.
    #  The string inside `{x}` will be replaced by the actual cell value.
    texttemplate = f"%{{z{fmt}}}"

    trace = go.Heatmap(
        z=z,
        x=labels,
        y=labels,
        colorscale=cmap,
        zmin=zmin,
        zmax=zmax,
        zmid=zmid,
        showscale=True,
        colorbar=dict(title=""),
        text=z,                     # keep the raw values for formatting
        hovertemplate="X=%{x}<br>Y=%{y}<br>Value=%{z:.2%}<extra></extra>",
        texttemplate=texttemplate,  # annotation format
        textfont=dict(size=12, color="black"),
        # hide the default colorbar title (the title is set per subplot later)
        # use `colorbar` dict to tweak the bar
    )

    return trace












################ FOR GRAPH OF MAIL ################
import pandas as pd
from pathlib import Path
import dataframe_image as dfi
import textwrap
import numpy as np
try:
    from xbbg import blp
except ImportError:
    blp = None
from datetime import datetime, timedelta
import matplotlib.pyplot as plt

def get_bloom_security_data(ticker, start_date='2022-01-01', flds=['last_price'], end_date=datetime.now().date()):
    """
    Retrieve historical data for a Bloomberg security.

    This function fetches historical data for a specified Bloomberg security (ticker)
    over a given date range, using the Bloomberg Data History (BDH) function.
    """
    if blp is None:
        raise ImportError("Bloomberg/xbbg is not available in this Python environment.")
    data = blp.bdh(tickers=ticker, flds=flds, start_date=start_date, end_date=end_date)
    data = data[ticker].rename(columns={flds[0]: ticker})
    return data


def plot_price(*args, start_date, output=None, figsize=(7, 4)):
    """
    Plot the performance of multiple financial series, normalized to 100 at the start date.

    Parameters:
    -----------
    *args : pandas.DataFrame or pandas.Series
        Any number of DataFrames or Series containing the financial data to be plotted.
        If a DataFrame is provided, all columns will be plotted.
        If a Series is provided, it will be plotted as a single line.
        Each series should have a datetime index and numeric values.

    start_date : str or datetime-like
        The start date for the plot. Data before this date will be excluded.
        This should be in a format that can be parsed by pandas.to_datetime().

    output : str, optional (default=None)
        If provided, the path where the plot should be saved as an image file.
        If None, the plot will only be displayed and not saved.

    Returns:
    --------
    None
        This function does not return any value. It displays (and optionally saves) a plot.

    Displays:
    ---------
    A matplotlib plot showing the normalized performance of all input series.
    Each series starts at 100 on the start date and shows relative performance over time.
    The final value of each series is annotated on the plot.

    Raises:
    -------
    ValueError
        If any of the input arguments are not pandas DataFrames or Series.
    """

    plt.figure(figsize=figsize)
    
    for data in args:
        if isinstance(data, pd.DataFrame):
            # If it's a DataFrame, use all columns
            for column in data.columns:
                plot_series(data[column], start_date)
        elif isinstance(data, pd.Series):
            plot_series(data, start_date)
        else:
            raise ValueError("Input must be DataFrames or Series")
    
    plt.title('Performance Comparison (Initialized to 100)')
    plt.xlabel('Date')
    plt.ylabel('Performance')
    plt.legend(loc='center left', bbox_to_anchor=(1, 0.5))
    plt.grid(True)
    plt.box(False)
    
    plt.xticks(rotation=45)
    plt.tight_layout()

    if output is not None:
        plt.savefig(output, bbox_inches='tight')
    
    plt.show()

def plot_series(series, start_date):
    # Convert index to datetime if it's not already
    series.index = pd.to_datetime(series.index)
    
    # Filter data based on start_date
    series = series[series.index >= pd.to_datetime(start_date)]
    
    # Normalize the series
    normalized_series = series / series.iloc[0] * 100
    
    # Plot the normalized series
    line, = plt.plot(normalized_series.index, normalized_series.values, label=series.name)
    
    # Get the last point
    last_date = normalized_series.index[-1]
    last_value = normalized_series.values[-1]
    
    # Add an annotation for the last point
    plt.annotate(f'{last_value:.2f}', 
                (last_date, last_value),
                xytext=(5, 5), 
                textcoords='offset points',
                ha='left',
                va='bottom',
                fontweight='bold',
                color=line.get_color())
    

def calculate_performance(df):
    current_price = df.iloc[-1, 0]
    
    # Calculate performance for different periods
    perf_1w = (current_price / df.iloc[-5, 0] - 1) * 100  # Assuming 5 trading days in a week
    perf_1m = (current_price / df.iloc[-22, 0] - 1) * 100  # Assuming 22 trading days in a month
    perf_3m = (current_price / df.iloc[-66, 0] - 1) * 100  # Assuming 66 trading days in 3 months
    perf_6m = (current_price / df.iloc[-132, 0] - 1) * 100  # Assuming 132 trading days in 6 months
    perf_1y = (current_price / df.iloc[-252, 0] - 1) * 100  # Assuming 252 trading days in a year
    
    # Calculate YTD performance
    start_of_year = pd.Timestamp(df.index[-1].year, 1, 1)
    ytd_start_price = df.loc[df.index >= start_of_year].iloc[0, 0]
    perf_ytd = (current_price / ytd_start_price - 1) * 100
    
    return pd.Series({
        '1 Week': perf_1w,
        '1 Month': perf_1m,
        '3 Months': perf_3m,
        '6 Months': perf_6m,
        '1 Year': perf_1y,
        'YTD': perf_ytd
    })

import pandas as pd
from pathlib import Path
import dataframe_image as dfi
import textwrap

def save_dataframe_as_image(df, filename, color, max_rows=None, max_cols=None, col_width=8, font_size=9):
    """
    Save a pandas DataFrame as an image file with custom styling and smaller font size.

    Parameters:
    -----------
    df : pandas.DataFrame
        The DataFrame to be saved as an image.
    filename : str
        The name of the output image file. Should include the file extension (e.g., '.png').
    max_rows : int, optional (default=None)
        The maximum number of rows to include in the image. If None, all rows are included.
    max_cols : int, optional (default=None)
        The maximum number of columns to include in the image. If None, all columns are included.
    col_width : int, optional (default=8)
        The maximum width of text in each column before wrapping occurs.
    font_size : int, optional (default=8)
        The font size to use for the table content.

    Returns:
    --------
    None
        This function does not return any value. It saves the DataFrame as an image file.
    """

    # Optionally limit the number of rows and columns
    if max_rows is not None:
        df = df.head(max_rows)
    if max_cols is not None:
        df = df.iloc[:, :max_cols]
    
    # Function to wrap text
    def wrap_text(text, width=col_width):
        return '<br>'.join(textwrap.wrap(str(text), width=width))
    
    # Wrap column names
    df.columns = [wrap_text(col) for col in df.columns]
    
    # Format numbers to two decimal places and handle NaN values
    def format_value(val):
        if pd.isna(val):
            return ''  # Return empty string for NaN values
        elif isinstance(val, (int, float)):
            return f'{val:.2f}'
        return val

    df_formatted = df.applymap(format_value)
    
    # Style the dataframe
    def style_nan(val):
        if val == '':  # Empty string represents NaN
            return 'background-color: white'
        return ''

    styled_df = df_formatted.style.applymap(style_nan)
    
    # Set table styles with smaller font size
    styled_df.set_table_styles([
        {'selector': 'th', 'props': [('background-color', color), 
                                    ('color', 'white'),
                                    ('font-weight', 'bold'),
                                    ('border', '1px solid black'),
                                    ('font-size', f'{font_size}pt'),
                                    ('padding', '2px')]},
        {'selector': 'td', 'props': [('border', '1px solid black'),
                                    ('font-size', f'{font_size}pt'),
                                    ('padding', '2px')]},
        {'selector': '', 'props': [('border-collapse', 'collapse'),
                                ('border', '1px solid black')]}
    ])
    
    # Center-align all cells
    styled_df.set_properties(**{'text-align': 'center'})
    
    # Save as image
    dfi.export(styled_df, filename, max_rows=100, table_conversion="chrome")
    print(f"DataFrame saved as {filename}")



def calculate_multiple_performances(*args, periods={'1w': 5, '1m': 22, '3m': 66, '6m': 132, '1y': 252, '3y': 756, '5y': 1260}):
    results = {}

    for arg in args:
        if isinstance(arg, pd.Series):
            arg = arg.to_frame()
        elif not isinstance(arg, pd.DataFrame):
            raise ValueError("Input must be pandas Series or DataFrame")

        for column in arg.columns:
            data = arg[column]
            current_price = data.iloc[-1]
            perf = {}

            # Calculate performance for specified periods
            for period_name, days in periods.items():
                if len(data) >= days:
                    perf[period_name] = (current_price / data.iloc[-days] - 1) * 100
                else:
                    # If not enough data, calculate from the earliest available date
                    perf[period_name] = (current_price / data.iloc[0] - 1) * 100
                    # Optionally, you might want to set it to None instead:
                    # perf[period_name] = None

            # Calculate YTD performance
            current_year = data.index[-1].year
            start_of_year = pd.Timestamp(f"{current_year}-01-01")
            
            # Make sure the index is datetime
            data.index = pd.to_datetime(data.index)
            
            # Get YTD data
            ytd_data = data[data.index >= start_of_year]
            if not ytd_data.empty:
                ytd_start_price = ytd_data.iloc[0]
                perf['YTD'] = (current_price / ytd_start_price - 1) * 100
            else:
                perf['YTD'] = None

            results[column] = perf

    # Create DataFrame and sort columns for better readability
    df_results = pd.DataFrame(results)
    
    # Define the preferred order of rows
    preferred_order = ['1w', '1m', '3m', '6m', 'YTD', '1y', '3y', '5y']
    
    # Reorder the index based on available periods
    available_periods = [p for p in preferred_order if p in df_results.index]
    df_results = df_results.reindex(available_periods)

    return df_results

def create_reverse_sector_dict(sector_dict = {
                                                "Basic Materials": 1.0,
                                                "Consumer Discretionary": 2.0,
                                                "Consumer Staples": 3.0,
                                                "Energy": 4.0,
                                                "Financials": 5.0,
                                                "Health Care": 6.0,
                                                "Industrials": 7.0,
                                                "Real Estate": 8.0,
                                                "Technology": 9.0,
                                                "Telecommunications": 10.0,
                                                "Utilities": 11.0
                                            }):
    return {v: k for k, v in sector_dict.items()}


def calculate_portfolio_metrics(portfolio, benchmark, annualization_factor=252):
    # Ensure input is DataFrame
    if isinstance(portfolio, pd.Series):
        portfolio = portfolio.to_frame(name='Portfolio')
    if isinstance(benchmark, pd.Series):
        benchmark = benchmark.to_frame(name='Benchmark')

    # Align the data and calculate returns
    aligned_data = pd.concat([portfolio, benchmark], axis=1, join='inner')
    aligned_data.columns = ['Portfolio', 'Benchmark']
    returns = aligned_data.pct_change().dropna()

    # Calculate Tracking Error
    tracking_error = np.sqrt(((returns['Portfolio'] - returns['Benchmark'])**2).mean()) * np.sqrt(annualization_factor)

    # Calculate Beta
    covariance = returns.cov().iloc[0, 1]
    benchmark_variance = returns['Benchmark'].var()
    beta = covariance / benchmark_variance

    # Calculate R-squared
    correlation = returns.corr().iloc[0, 1]
    r_squared = correlation ** 2

    return {
        'tracking_error': tracking_error,
        'beta': beta,
        'r_squared': r_squared
    }


def calculate_weighted_sums(*dataframes, columns_to_sum, weight_column='Weight'):
    """
    Calculate weighted sums for specified columns across multiple dataframes.

    This function takes any number of dataframes, normalizes the weights,
    and calculates the weighted sum for specified columns.

    Parameters:
    -----------
    *dataframes : pandas.DataFrame
        Any number of dataframes to process. Each dataframe should contain
        the columns specified in 'columns_to_sum' and the weight column.
    columns_to_sum : list
        List of column names to calculate weighted sums for.
    weight_column : str, optional (default='Weight')
        Name of the column containing weights in each dataframe.

    Returns:
    --------
    pandas.DataFrame
        A dataframe containing the weighted sums for each input dataframe.
        Columns represent the specified columns to sum, and rows represent each input dataframe.

    Examples:
    ---------
    >>> df1 = pd.DataFrame({'A': [1, 2], 'B': [3, 4], 'Weight': [0.4, 0.6]})
    >>> df2 = pd.DataFrame({'A': [5, 6], 'B': [7, 8], 'Weight': [0.3, 0.7]})
    >>> result = calculate_weighted_sums(df1, df2, columns_to_sum=['A', 'B'])
    >>> print(result)
    """
    def calculate_single_weighted_sum(df):
        # Ensure weights sum to 1
        df[weight_column] = df[weight_column] / df[weight_column].sum()
        
        return (df[columns_to_sum].multiply(df[weight_column], axis=0)).sum()

    results = []
    for i, df in enumerate(dataframes):
        weighted_sum = calculate_single_weighted_sum(df)
        weighted_sum.name = f'DataFrame_{i+1}'
        results.append(weighted_sum)

    result_df = pd.concat(results, axis=1).T
    result_df.index = [f'DataFrame_{i+1}' for i in range(len(dataframes))]

    return result_df


def calculate_periodic_returns(df, columns=None, start_date=None, end_date=None):
    # Convert index to datetime if it's not already
    df.index = pd.to_datetime(df.index)
    
    # Filter the DataFrame based on start and end dates if provided
    if start_date:
        df = df[df.index >= pd.to_datetime(start_date)]
    if end_date:
        df = df[df.index <= pd.to_datetime(end_date)]
    
    # Use all columns if none specified
    if columns is None:
        columns = df.columns
    else:
        # Filter out columns that are not in the DataFrame
        columns = [col for col in columns if col in df.columns]
        if not columns:
            raise ValueError("None of the specified columns are in the DataFrame")
    
    # Define the offsets for each period
    offsets = {
        '1 Week Return': 5,
        '1 Month Return': 22,
        '3 Month Return': 66,
        '6 Month Return': 132,
        '1 Year Return': 252
    }
    
    results = {}
    
    for period, offset in offsets.items():
        if len(df) > offset:
            # Calculate cumulative return over the period
            cumulative_return = (1 + df[columns].iloc[-offset:]).prod() - 1
            results[period] = cumulative_return * 100  # Convert to percentage
        else:
            results[period] = pd.Series(np.nan, index=columns)
    
    # Combine results
    result = pd.DataFrame(results)
    
    return result



def create_bar_plot(*args, ylabel, title, save_path, labels=None, figsize=(10, 4), rotation=80, ylim=None):
    # Create figure and axis
    fig, ax1 = plt.subplots(figsize=figsize)

    # Prepare data
    all_data = []
    for data in args:
        if isinstance(data, pd.Series):
            all_data.append(data.to_frame())
        elif isinstance(data, pd.DataFrame):
            all_data.append(data)
        else:
            raise ValueError("Input data must be pandas Series or DataFrame")

    # Set width of bars and positions
    num_datasets = len(all_data)
    bar_width = 0.9 / (sum(len(data.columns) for data in all_data))
    indices = np.arange(len(all_data[0].index))

    # Create bars for each dataset
    start = 0
    for i, data in enumerate(all_data):
        for j, column in enumerate(data.columns):
            positions = indices + (start + j) * bar_width
            bars = ax1.bar(positions, data[column], width=bar_width, 
                           label=f"{labels[i] if labels else f'Dataset {i+1}'} - {column}")
            add_value_labels(ax1, bars)
        start += len(data.columns)

    # Customize the plot
    ax1.set_ylabel(ylabel)
    ax1.set_title(title)
    ax1.set_xticks(indices + bar_width * (sum(len(data.columns) for data in all_data) - 1) / 2)
    ax1.set_xticklabels(all_data[0].index, rotation=rotation, ha='right')

    # Set y-axis limits if provided
    if ylim:
        ax1.set_ylim(ylim)

    # Add legends
    ax1.legend(loc='upper left', bbox_to_anchor=(1, 1))

    # Add gridlines
    ax1.grid(axis='y', linestyle='--', alpha=0.7)

    plt.box(False)

    # Adjust layout
    plt.tight_layout()

    # Save the figure
    plt.savefig(save_path, bbox_inches='tight')

    # Display the plot
    plt.show()

def add_value_labels(ax, rects, fontsize=8):
    for rect in rects:
        height = rect.get_height()
        ax.annotate(f'{height:.2f}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom',
                    fontsize=fontsize)
        



def calculate_sector_returns(returns, asset_list, start_date, end_date, periods=None):
    if periods is None:
        periods = ['1 Week', '1 Month', '3 Month', '6 Month', '1 Year']
    
    # Calculate periodic returns
    periodic_returns = calculate_periodic_returns(
        returns, 
        columns=asset_list['Company SEDOL'].unique().tolist(), 
        start_date=start_date, 
        end_date=end_date
    )

    # Merge periodic returns with asset information
    results = periodic_returns.merge(
        asset_list[['Company SEDOL', 'Name', 'Sector', 'Weight']], 
        left_index=True, 
        right_on='Company SEDOL'
    )

    # Calculate weighted returns for each period
    for period in periods:
        results[f'{period} Rdt Weighted'] = results[f'{period} Return'] * results['Weight']

    # Group by sector and sum weighted returns for each period
    returns_sector = results.groupby('Sector')[
        [f'{period} Rdt Weighted' for period in periods]
    ].sum()

    return returns_sector


def get_ptf_perf(ptf_ticker, bench_ticker,  ptf_worst_ticker=None, start_date="2015-01-01", source="Bloom"):
    if source!="Bloom": # on a également option de récupérer les perf à partir des fichers backtest
        ptf = pd.read_parquet(ptf_ticker).to_frame()
        ptf.rename(columns={"ptf" : "TOP ML"}, inplace=True)
    else: # Sinon on récupérer directement de bloom
        ptf = get_bloom_security_data(ptf_ticker, start_date='2015-01-01')
        ptf.rename(columns={ptf_ticker : "TOP ML"}, inplace=True)

    bench = get_bloom_security_data(bench_ticker, start_date='2015-01-01')
    bench.rename(columns={bench_ticker : "Bench"}, inplace=True)

    if ptf_worst_ticker: # seulement si on veut regarder également le worst, mais pour ml world, le worst n'existe pas pour moment
        worst = get_bloom_security_data(ptf_worst_ticker, start_date=start_date)
        worst = worst.rename(columns={ptf_worst_ticker: "WORST ML"})
        result = pd.concat([ptf, bench, worst], axis=1)
    else:
        result = pd.concat([ptf, bench], axis=1)

    result = result.dropna()
    result = result.sort_index()
    return result.div(result.iloc[0]) * 100 # Rebalancer pour avoir 100 au début de date

def get_bench_cols(screen_path, univ):
    screen = pd.read_parquet(screen_path)
    screen_last = screen[screen['Date'] == screen['Date'].max()]
    bench_list = screen_last.dropna(subset=f'Weight in {univ}')
    bench_list = screen_last.dropna(subset=f'Weight in {univ}')
    bench_list = bench_list.rename(columns={  "Exchange Country Name" : "Country",
                                    f'Weight in {univ}' : 'Weight',
                                    ' Benchmark ICB Industry ' : "Sector",
                                    "Exchange Country Region" : "Region",
                                    "Benchmark Market Value Millions in EUR ": "Mkt Cap",
                                    'ESG_ANALYST_SCORE' : 'ESG Score',
                                    'DVD Yield FY0' : 'DVD Yield',
                                    'Earns Yield FY0' : 'Earnings Yield',
                                    'ROE avg FY0' : 'ROE',
                                    'PE LTM' : 'PE',
                                    'CarbonIntensity_Sales' : 'Carbon Intensity',
                                    'Dividend Avg Percentile' : 'Div Score', 
                                    'Value Avg Percentile' : 'Value Score',
                                    'Quality Avg Percentile' : 'Quality Score', 
                                    'Mom Avg Percentile' : 'Mom Score', 
                                    'Growth Avg Percentile' : 'Growth Score',
                                    'LowVol Avg Percentile' : 'LowVol Score'})
    columns_ordered_bench = ['Name', 'Weight', 'Country', 'Region', 'Sector', 'Company SEDOL', 'Mkt Cap', 'Score ML',
                            #  'ESG Score', 'Carbon Intensity', 'Div Score', 
                            'PE', 'EPS Growth FY1', 'LowVol Score', 
                            'ROE', 
                            'Oper Margin', 
                            'DVD Yield', 'Earnings Yield',
                            'Value Score', 'Quality Score',
                            'Mom Score', 'Growth Score']
    bench_list = bench_list[columns_ordered_bench]
    # Transform sector code into sector name
    reverse_sector_dict = create_reverse_sector_dict()
    bench_list['Sector'] = bench_list['Sector'].map(reverse_sector_dict)
    return bench_list

def calculate_ratio_vs_bench(ptf, bench, metrics):
    columns_to_sum = ['PE', 'ROE', 
                    'Oper Margin', 
                    'Earnings Yield', 'Value Score', 'Quality Score', 'Mom Score', 
                    'Growth Score', 'Score ML']

    ratio_basket_bench = calculate_weighted_sums(ptf, bench, columns_to_sum=columns_to_sum)
    ratio_basket_bench.index = ['Top', 'Bench']
    ratio_basket_bench = ratio_basket_bench.T


    result_df_2 = ratio_basket_bench.copy(deep=True)
    result_df_2.loc['TE', "Top"] = metrics['tracking_error']
    result_df_2.loc['Beta', "Top"] = metrics['beta']
    result_df_2.loc['R_squared', "Top"] = metrics['r_squared']

    result_df_2.loc['Nb Titres', "Top"] = len(ptf)
    result_df_2.loc['Nb Titres', "Bench"] = len(bench)

    result_df_2 = result_df_2.round(2)

    # FORCAGE BENCH
    result_df_2.loc['TE', "Bench"] = 0
    result_df_2.loc['Beta', "Bench"] = 1
    result_df_2.loc['R_squared', "Bench"]=1

    ratio_top = result_df_2.copy(deep=True)
    return ratio_top

def top_worst_performers(returns_path, basket, n=25):
    returns = pd.read_parquet(returns_path)

    end_date = pd.Timestamp.today().strftime('%Y-%m-%d')
    periodic_returns = calculate_periodic_returns(returns, columns=basket['Company SEDOL'].unique().tolist(), start_date='2023-01-01', end_date=end_date)

    results_rtd_screen = periodic_returns.merge(basket[['Company SEDOL', 'Name', 'Sector', 'Weight']], left_index=True, right_on='Company SEDOL')
    top_25_weekly = results_rtd_screen.sort_values('1 Week Return', ascending=False)[['Name', 'Sector', 'Weight', '1 Week Return']].head(n)
    top_25_weekly['Weight'] = top_25_weekly['Weight'] * 100
    top_25_weekly = top_25_weekly.round(2)
    worst_25_weekly = results_rtd_screen.sort_values('1 Week Return', ascending=True)[['Name', 'Sector', 'Weight', '1 Week Return']].head(n)
    worst_25_weekly['Weight'] = worst_25_weekly['Weight'] * 100
    worst_25_weekly = worst_25_weekly.round(2)
    return top_25_weekly, worst_25_weekly


def map_19_to_11(basket):
    secto_map = {'Banks': 'Financials', 
            'Energy': 'Energy', 
            'Basic Resources': 'Basic Materials', 
            'Industrial Goods & Services': 'Industrials', 
            'Travel & Leisure': 'Consumer Discretionary', 
            'Insurance': 'Financials', 
            'Real Estate': 'Real Estate', 
            'Retail': 'Consumer Discretionary', 
            'Health Care': 'Health Care', 
            'Technology': 'Technology', 
            'Construction': 'Industrials', 
            'Utilities': 'Utilities', 
            'Personal & Household Goods': 'Consumer Staples', 
            'Food, Beverage & Tobacco': 'Consumer Staples', 
            'Financial Services': 'Financials', 
            'Telecommunications': 'Telecommunications', 
            'Media': 'Consumer Discretionary', 
            'Auto & Parts': 'Consumer Discretionary', 
            'Chemicals': 'Basic Materials'}
            
    basket['Sector'] = basket['Sector'].map(secto_map)
    return basket

def create_sector_weight_comp_plot(basket, bench_list, save_path=r'output_mail\weight_comparison_secto.png'):
    basket_secto_weight = basket.reset_index().groupby('Sector').agg({'ISIN': 'count', 'Weight': 'sum'}).rename(columns={'ISIN': 'Nb titres',
                                                                                                                    'Weight': 'Weight Ptf'})
    bench_secto_wieght = bench_list.groupby('Sector').agg({'Weight': 'sum'}).rename(columns={'Weight': 'Weight Bench'})  # addition tous les boites dans le secteur
    secto_weight = pd.concat([basket_secto_weight, bench_secto_wieght], axis=1)
    secto_weight['Pct +/-'] = (secto_weight['Weight Ptf'] - secto_weight['Weight Bench']) * 100

    create_bar_plot(secto_weight[['Weight Ptf', 'Weight Bench']], 
                ylabel='Weight', 
                title='Weight Comparison', 
                save_path=save_path, 
                labels=[''],
                figsize=(10, 5),
                ylim=(0, 0.35),
                rotation=30)

def create_sector_return_comp_plot(basket, bench_list, returns_path, ylim=(-0.15, 0.45), save_path=r'output_mail\rdt_comparaison_secto.png'):
    returns = pd.read_parquet(returns_path)
    # Usage for portfolio
    returns_sector_portfolio = calculate_sector_returns(
        returns, 
        basket, 
        start_date='2023-01-01', 
        end_date='2025-01-02',
        periods=['1 Week', '1 Month', '3 Month', '6 Month', '1 Year']
    )

    # Usage for benchmark
    returns_sector_benchmark = calculate_sector_returns(
        returns, 
        bench_list, 
        start_date='2023-01-01', 
        end_date='2025-01-02',
        periods=['1 Week', '1 Month', '3 Month', '6 Month', '1 Year']
    )

    returns_sector_benchmark = returns_sector_benchmark.add_suffix(' Bench')
    combined_returns = pd.concat([returns_sector_portfolio, returns_sector_benchmark], axis=1)

    combined_returns['+/-'] = combined_returns['1 Week Rdt Weighted'] - combined_returns['1 Week Rdt Weighted Bench']

    create_bar_plot(combined_returns[['1 Week Rdt Weighted', '1 Week Rdt Weighted Bench']], 
                    ylabel='Returns', 
                    title='Returns Ptf vs Returns Bench', 
                    save_path=save_path, 
                    labels=[''],
                    figsize=(10, 5),
                    ylim=ylim,
                    rotation=30)
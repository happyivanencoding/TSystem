import numpy as np
import pandas as pd
from Codes.BacktestEngine import OfficialPortfolioBacktest

def handle_missing_values(df, columns, group_cols=[' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']):
    for col in columns:
        df[col] = df[col].fillna(df.groupby(group_cols)[col].transform('median'))
    return df

def neutralize_score(df, score_col, higher_is_better, group_cols=[' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']):
    # Calcul du rang centile au sein de chaque groupe et multiplication par 10
    # pct=True transforme le rang en valeur entre 0 et 1
    df[f"{score_col}"] = (
        df.groupby(group_cols)[score_col]
        .rank(pct=True, ascending= higher_is_better) * 10
    )
    return df


def build_factor_component(screen, var_name, config):
    """
    Calculates contribution based on flexible flags: Level, Pct Change, or Diff.
    """
    if var_name not in screen.columns:
        print(f"Warning: {var_name} missing from data. Skipping.")
        return screen, 0
    
    contribution = 0
    # Ensure sorting once per variable for all time-series operations
    screen = screen.sort_values(['ISIN', 'Date'])
    
    # --- A. Level Logic ---
    if config.get('use_level', False):
        temp_col = f"{var_name}_score"
        screen[temp_col] = screen[var_name]
        screen = neutralize_score(screen, temp_col, higher_is_better=config['higher_is_better'])
        contribution += screen[temp_col] * config['weight_level']
        screen = screen.drop(columns=[temp_col])

    # --- B. Pct Change Logic (Relative: (New-Old)/Old) ---
    if config.get('use_pct', False):
        pct_col = f"{var_name}_pct"
        temp_score_col = f"{var_name}_pct_score"
        
        screen[pct_col] = screen.groupby('ISIN')[var_name].pct_change().replace([np.inf, -np.inf], np.nan)
        screen[temp_score_col] = screen[pct_col]
        
        screen = neutralize_score(screen, temp_score_col, higher_is_better=config['higher_is_better'])
        contribution += screen[temp_score_col] * config['weight_pct']
        screen = screen.drop(columns=[temp_score_col])

    # --- C. Difference Logic (Absolute: New - Old) ---
    if config.get('use_diff', False):
        diff_col = f"{var_name}_diff"
        temp_score_col = f"{var_name}_diff_score"
        
        screen[diff_col] = screen.groupby('ISIN')[var_name].diff().replace([np.inf, -np.inf], np.nan)
        screen[temp_score_col] = screen[diff_col]
        
        screen = neutralize_score(screen, temp_score_col, higher_is_better=config['higher_is_better'])
        contribution += screen[temp_score_col] * config['weight_diff']
        screen = screen.drop(columns=[temp_score_col])

    return screen, contribution

def calculate_quality_score(screen, col_name, QUALITY_CONFIG):
    """Iterates through CONFIG and sums all enabled components."""
    total_q_score = 0
    for var_name, config in QUALITY_CONFIG.items():
        screen, contribution = build_factor_component(screen, var_name, config)
        total_q_score += contribution

    screen[col_name] = total_q_score
    screen = neutralize_score(screen, col_name, higher_is_better=True)
    return screen


def backtest_factors(screen, returns, bench, list_noire_path, test_variables):
    """
    Exécute le backtest et génère des graphiques de comparaison pour les facteurs spécifiés.
    """
    for v in test_variables:
        print(f"Testing factor: {v}")
        builder_top = OfficialPortfolioBacktest(screen, returns, ptf_name=f"{v}_top", 
                                bench=bench, percentile=0.2, esg_exclusion=0, 
                                liste_noire=list_noire_path, metrics=v, Top=True)
        builder_bottom = OfficialPortfolioBacktest(screen, returns, ptf_name=f"{v}_bottom", 
                                bench=bench, percentile=0.2, esg_exclusion=0, 
                                liste_noire=list_noire_path, metrics=v, Top=False)
        for b in [builder_top, builder_bottom]:
            b.start_date = "2010-01-01"
            b.freq_rebal = 1
            b.fill_method = "copy"
        builder_top.plot_top_vs_bottom(
            builder_bottom=builder_bottom, 
            title=f"Factor Analysis: {v}", 
            save_path=f"{v}_comparison.html",
            show_plot=True
        )

# ===========================================================================
# 3. RUN FACTOR PIPELINE
# ===========================================================================

def run_factor_pipeline(screen, returns, col_name, QUALITY_CONFIG, list_noire_path):
    print("Step 1: Calculating flexible quality scores...")
    screen = calculate_quality_score(screen, col_name, QUALITY_CONFIG)
    
    # Appel de la fonction de backtest indépendante
    test_variables = [col_name] 
    bench="STOXX EUROPE 600"
    backtest_factors(screen, returns, bench, list_noire_path, test_variables)
    
    return screen



def test_unitary_factors(screen, returns, UNITARY_QUALITY_VARS, list_noire_path):
    """
    Pipeline pour tester chaque variable de qualité individuellement selon trois dimensions: 
    Niveau, Variation Absolue et Variation Pourcentage.
    """
    import numpy as np
    # Copie du dataframe et tri indispensable pour le calcul des variations
    df_test = screen.copy().sort_values(['ISIN', 'Date'])

    for var_name, is_positive in UNITARY_QUALITY_VARS.items():
        # --- Définition des dimensions de test ---
        # Calcul préalable des variations pour éviter les répétitions dans la boucle interne
        df_test[f"{var_name}_change"] = df_test.groupby('ISIN')[var_name].diff()
        df_test[f"{var_name}_pct_change"] = df_test.groupby('ISIN')[var_name].pct_change()
        
        # Remplacement des valeurs infinies par NaN (spécifique au pct_change)
        df_test[f"{var_name}_pct_change"] = df_test[f"{var_name}_pct_change"].replace([np.inf, -np.inf], np.nan)

        dimensions = {
            "LEVEL": var_name, 
            "CHANGE": f"{var_name}_change",
            "CHANGE_PCT": f"{var_name}_pct_change"
        }

        for dim_label, col_to_test in dimensions.items():
            print(f"Testing Unitary Factor: {var_name} | Dimension: {dim_label} (Direction: {'Positive' if is_positive else 'Negative'})")
            
            # 1. Traitement des valeurs manquantes pour cette variable spécifique
            df_test = handle_missing_values(df_test, [col_to_test])
            
            # 2. Création d'une colonne temporaire neutralisée pour le test
            temp_col = f"UNITARY_{dim_label}_{var_name}"
            df_test[temp_col] = df_test[col_to_test] 
            
            # Neutralisation : on transforme la valeur brute en score 0-10
            df_test = neutralize_score(df_test, temp_col, higher_is_better=is_positive)
            
            # 3. Exécution du Backtest via OfficialPortfolioBacktest
            try:
                builder_top = OfficialPortfolioBacktest(df_test, returns, ptf_name=f"{temp_col}_top", 
                                        bench="STOXX EUROPE 600", percentile=0.2, esg_exclusion=0, 
                                        liste_noire=list_noire_path, metrics=temp_col, Top=True)
                builder_bottom = OfficialPortfolioBacktest(df_test, returns, ptf_name=f"{temp_col}_bottom", 
                                            bench="STOXX EUROPE 600", percentile=0.2, esg_exclusion=0, 
                                            liste_noire=list_noire_path, metrics=temp_col, Top=False)
                
                for b in [builder_top, builder_bottom]:
                    b.start_date = "2010-01-01"
                    b.freq_rebal = 1
                    b.fill_method = "copy"
                
                builder_top.plot_top_vs_bottom(
                    builder_bottom=builder_bottom, 
                    title=f"Unitary Analysis: {var_name} ({dim_label})", 
                    save_path=f"{temp_col}_comparison.html",
                    show_plot=True 
                )
            except Exception as e:
                print(f"Error testing {var_name} {dim_label}: {e}")

    return df_test






def handle_missing_values(df, columns, group_cols=[' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']):
    for col in columns:
        if col in df.columns:
            df[col] = df[col].fillna(df.groupby(group_cols)[col].transform('median'))
    return df

def neutralize_score(df, score_col, higher_is_better, group_cols=[' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']):
    df[f"{score_col}"] = (
        df.groupby(group_cols)[score_col]
        .rank(pct=True, ascending=not higher_is_better) * 10 # Fixed: rank logic for higher_is_better
    )
    return df

def transform_absolute_values(df, abs_vars, group_cols=[' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']):
    """
    Transform absolute values into relative ratios.
    Transforme les valeurs absolues en ratios relatifs.
    """
    normalization_map = {
        'R&D Expense CIQ': 'Sales', 
        'Capex CIQ': 'Sales',
        'Interest expense CIQ': 'Ebitda',
        'Sales FY1': 'Sales',
    }
    
    new_cols = []
    for var in abs_vars:
        if var not in df.columns: continue
        
        denominator = normalization_map.get(var)
        new_col_name = f"{var}_Intensity" if denominator else f"{var}_Relative"
        
        if denominator and denominator in df.columns:
            df[new_col_name] = df[var] / df[denominator]
        else:
            df[new_col_name] = df.groupby(group_cols)[var].transform(lambda x: x / x.median())
        
        new_cols.append(new_col_name)
    return df, new_cols

# ==========================================
# 3. Production Pipeline Integration
# ==========================================

def run_growth_factor_pipeline(df):
    """
    Main entry point for the growth factor processing pipeline.
    Point d'entrée principal pour le pipeline de traitement du facteur de croissance.
    """
    group_cols = [' Benchmark ICB Supersector ', 'Date', 'Exchange Country Region']
    
    # Step 1: Transform Absolute Values -> Ratios
    # Étape 1 : Transformation des valeurs absolues en ratios
    df, transformed_abs_cols = transform_absolute_values(df, abs_vars, group_cols)
    
    # Combine all columns that need to be processed (Ratios + Transformed Absolutes)
    # Combinaison de toutes les colonnes à traiter
    final_feature_list = ratio_vars + transformed_abs_cols
    
    # Step 2: Clean Infinity values (result of division by zero)
    # Étape 2 : Nettoyage des valeurs infinies (résultat d'une division par zéro)
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    
    # Step 3: Handle Missing Values
    # Étape 3 : Gestion des valeurs manquantes
    df = handle_missing_values(df, final_feature_list, group_cols)
    
    # Step 4: Neutralize Scores (Rank-based normalization)
    # Étape 4 : Neutralisation des scores (Normalisation basée sur le rang)
    for col in final_feature_list:
        if col in df.columns:
            # For growth factors, generally higher is better
            # Pour les facteurs de croissance, généralement plus c'est élevé, mieux c'est
            df = neutralize_score(df, col, higher_is_better=True, group_cols=group_cols)
            
    return df





# --- Configuration des variables unitaires de Qualité ---
# On définit les variables et leur direction (True: plus c'est haut, mieux c'est / False: inverse)
UNITARY_GROWTH_VARS = {
    # Intensité et Dépenses (Plus bas = Meilleur)
    'R&D Expense CIQ_Intensity': False,
    'Capex CIQ_Intensity': False,
    'Sales FY1_Intensity': False,
    'Interest expense CIQ_Intensity': False,
    
    # Solvabilité (Plus bas = Meilleur)
    'Net Debt to Ebit': False,
    'Net Debt to Tot Equity': False,
    
    # Croissance et Stabilité (Plus haut = Meilleur)
    'CFO 5Y CAGR': True,
    'FCF Conversion': True,
    'Gross Profit 5Y CAGR': True,
    'Const Earning 5Y CAGR': True,
    'Revenue 5Y CAGR': True,
    'Sales Growth FY1 CIQ': True,
    'Ebitda 5Y CAGR': True,
    'EBITDA Growth FY1 CIQ': True,
    'Ebit 5Y CAGR': True,
    'EPS Growth FY1 CIQ': True,
    'SP Est 5Y EPS Gr CIQ': True,
    
    # Profitabilité (Plus haut = Meilleur)
    'Gross Margin': True,
    'Ebitda Margin': True
}


def test_unitary_factors(screen, returns, UNITARY_QUALITY_VARS, list_noire_path):
    """
    Pipeline pour tester chaque variable de qualité individuellement selon trois dimensions: 
    Niveau, Variation Absolue et Variation Pourcentage.
    """
    import numpy as np
    # Copie du dataframe et tri indispensable pour le calcul des variations
    df_test = screen.copy().sort_values(['ISIN', 'Date'])

    for var_name, is_positive in UNITARY_QUALITY_VARS.items():
        # --- Définition des dimensions de test ---
        # Calcul préalable des variations pour éviter les répétitions dans la boucle interne
        df_test[f"{var_name}_change"] = df_test.groupby('ISIN')[var_name].diff()
        df_test[f"{var_name}_pct_change"] = df_test.groupby('ISIN')[var_name].pct_change()
        
        # Remplacement des valeurs infinies par NaN (spécifique au pct_change)
        df_test[f"{var_name}_pct_change"] = df_test[f"{var_name}_pct_change"].replace([np.inf, -np.inf], np.nan)

        dimensions = {
            "LEVEL": var_name, 
            "CHANGE": f"{var_name}_change",
            "CHANGE_PCT": f"{var_name}_pct_change"
        }

        for dim_label, col_to_test in dimensions.items():
            print(f"Testing Unitary Factor: {var_name} | Dimension: {dim_label} (Direction: {'Positive' if is_positive else 'Negative'})")
            
            # 1. Traitement des valeurs manquantes pour cette variable spécifique
            df_test = handle_missing_values(df_test, [col_to_test])
            
            # 2. Création d'une colonne temporaire neutralisée pour le test
            temp_col = f"UNITARY_{dim_label}_{var_name}"
            df_test[temp_col] = df_test[col_to_test] 
            
            # Neutralisation : on transforme la valeur brute en score 0-10
            df_test = neutralize_score(df_test, temp_col, higher_is_better=is_positive)
            
            # 3. Exécution du Backtest via OfficialPortfolioBacktest
            try:
                builder_top = OfficialPortfolioBacktest(df_test, returns, ptf_name=f"{temp_col}_top", 
                                        bench="STOXX EUROPE 600", percentile=0.2, esg_exclusion=0, 
                                        liste_noire=list_noire_path, metrics=temp_col, Top=True)
                builder_bottom = OfficialPortfolioBacktest(df_test, returns, ptf_name=f"{temp_col}_bottom", 
                                            bench="STOXX EUROPE 600", percentile=0.2, esg_exclusion=0, 
                                            liste_noire=list_noire_path, metrics=temp_col, Top=False)
                
                for b in [builder_top, builder_bottom]:
                    b.start_date = "2010-01-01"
                    b.freq_rebal = 1
                    b.fill_method = "copy"
                
                builder_top.plot_top_vs_bottom(
                    builder_bottom=builder_bottom, 
                    title=f"Unitary Analysis: {var_name} ({dim_label})", 
                    save_path=f"{temp_col}_comparison.html",
                    show_plot=True 
                )
            except Exception as e:
                print(f"Error testing {var_name} {dim_label}: {e}")

    return df_test



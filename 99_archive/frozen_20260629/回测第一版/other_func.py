from sec_list_generation import generic_histo_seclist, sec_list_spot, sec_list_spot_worst
from backtest import backtest
from dateutil import relativedelta
import pandas as pd
import plotly.graph_objects as go

import warnings
warnings.filterwarnings("ignore")

def generate_top_worst_ptf(params):
    screen, returns, liste_noire, metrics, percentile, bench, output_dir, cut_mkt_cap, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, start_date = params
    # Generate Bench
    indice_ref = screen[(screen['Date']>start_date)*(screen['Weight in '+bench]>0)].reset_index()[['Date','ISIN']]
    indice_ref["Date"]=indice_ref["Date"].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1))
    
    # Generate Top and Worst
    ptf_top = generic_histo_seclist(sec_list_spot, start_date, screen, bench, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire)
    
    ptf_worst = generic_histo_seclist(sec_list_spot_worst, start_date, screen, bench, output_dir, percentile, cut_mkt_cap, metrics, ptf_name, score_neutral, weight_neutral, ponderation, esg_exclusion, liste_noire)
    
    return indice_ref, ptf_top, ptf_worst

def generate_top_worst_perf(indice_ref, ptf_top, ptf_worst, bench, screen,returns):
    perf_bench, indice = backtest(indice_ref, bench, screen,returns)
    perf_ptf_top, buy_list = backtest(ptf_top, bench, screen, returns)
    perf_ptf_worst, buy_list = backtest(ptf_worst, bench, screen, returns)
    return perf_bench, perf_ptf_top, perf_ptf_worst

########################  PLOT   ############################
def plot_top_worst(perf_bench, perf_ptf_top, perf_ptf_worst, bench_name, percentile, metrics):

    perf = pd.concat([perf_bench, perf_ptf_top, perf_ptf_worst],axis=1)
    perf.columns=['Perf Bench', 'Perf Top', 'Perf Worst']

    # Create traces
    trace_top = go.Scatter(x=perf.index, y=perf['Perf Top'], mode='lines', name='Perf Top', line=dict(color='#1EAD37'))
    trace_worst = go.Scatter(x=perf.index, y=perf['Perf Worst'], mode='lines', name='Perf Worst', line=dict(color='#E6514A'))
    trace_bench = go.Scatter(x=perf.index, y=perf['Perf Bench'], mode='lines', name=bench_name, line=dict(color='#4890E6'))

    # Create the figure
    fig = go.Figure()

    # Add traces to the figure
    fig.add_trace(trace_top)
    fig.add_trace(trace_worst)
    fig.add_trace(trace_bench)

    # Update layout
    fig.update_layout(
        title=f"Top and Worst {int(percentile*100)}% ptf based on Score {str(metrics.split(' ')[0])}",
        xaxis_title='Date',
        yaxis_title='Performance',
        legend_title='Portfolio',
        template='plotly',
        height = 350,
        width = 800,
        margin=dict(l=30, r=30, t=50, b=20)
    )

    # Show the figure
    fig.show()

    ############################## Metrics #########################################
import numpy as np
def calculate_metrics(prices, bench, is_bench=False):
    def calculate_annual_returns(prices):
        total_return = prices.iloc[-1] / prices.iloc[0] - 1
        num_years = (prices.index[-1] - prices.index[0]).days / 365
        cagr = (1 + total_return) ** (1 / num_years) - 1
        return cagr

    def calculate_volatility(prices):
        returns = prices.pct_change().dropna()
        volatility = returns.std() * np.sqrt(252) 
        return volatility

    def calculate_sharpe_ratio(prices, risk_free_rate=0):
        returns = prices.pct_change().dropna()
        excess_returns = returns - risk_free_rate / 252
        avg_excess_returns = excess_returns.mean()
        std_excess_returns = excess_returns.std()
        sharpe_ratio = avg_excess_returns / std_excess_returns * np.sqrt(252)
        return sharpe_ratio

    def calculate_max_drawdown(prices):
        cumulative_returns = prices / prices.iloc[0]
        cumulative_max = cumulative_returns.cummax()
        drawdown = cumulative_returns / cumulative_max - 1
        max_drawdown = drawdown.min()
        return max_drawdown

    def calculate_tracking_error(prices, bench):
        returns = prices.pct_change().dropna()
        benchmark_returns = bench.pct_change().dropna()
        tracking_error = np.std(returns - benchmark_returns) * np.sqrt(252)
        return tracking_error

    # Calculate metrics for benchmark
    annual_return = calculate_annual_returns(prices)
    max_drawdown = calculate_max_drawdown(prices)
    volatility = calculate_volatility(prices)
    sharpe_ratio = annual_return/volatility
    if is_bench == False:
        tracking_error = calculate_tracking_error(prices, bench)
    else:
        tracking_error = 0.0

    return annual_return, volatility, max_drawdown, tracking_error

def calculate_metrics_top_worst_ptf(perf_bench, perf_ptf_top, perf_ptf_worst):
    bench_annual_return, bench_volatility, bench_max_drawdown, bench_tracking_error = calculate_metrics(perf_bench, perf_bench, is_bench=True)
    top_annual_return, top_volatility, top_max_drawdown, top_tracking_error = calculate_metrics(perf_ptf_top, perf_bench)
    worst_annual_return, worst_volatility, worst_max_drawdown, worst_tracking_error = calculate_metrics(perf_ptf_worst, perf_bench)

    # # Print results
    # print(f"Benchmark - Annual Return: {bench_annual_return:.2%}, Sharpe Ratio: {bench_sharpe_ratio:.2f}, Max Drawdown: {bench_max_drawdown:.2%}, Volatility: {bench_volatility:.2%}")
    # print(f"Top Portfolio - Annual Return: {top_annual_return:.2%}, Sharpe Ratio: {top_sharpe_ratio:.2f}, Max Drawdown: {top_max_drawdown:.2%}, Tracking Error: {top_tracking_error:.2%}, Volatility: {top_volatility:.2%}")
    # print(f"Worst Portfolio - Annual Return: {worst_annual_return:.2%}, Sharpe Ratio: {worst_sharpe_ratio:.2f}, Max Drawdown: {worst_max_drawdown:.2%}, Tracking Error: {worst_tracking_error:.2%}, Volatility: {worst_volatility:.2%}")

    # Create a dictionary of metrics
    metrics_dict = {
        'Benchmark': {
            'Annual Return': bench_annual_return,
            'Max Drawdown': bench_max_drawdown,
            'Volatility': bench_volatility,
        },
        'Top Ptf': {
            'Annual Return': top_annual_return,
            'Max Drawdown': top_max_drawdown,
            'Tracking Error': top_tracking_error,
            'Volatility': top_volatility,
        },
        'Worst Ptf': {
            'Annual Return': worst_annual_return,
            'Max Drawdown': worst_max_drawdown,
            'Tracking Error': worst_tracking_error,
            'Volatility': worst_volatility,  
        }
    }

    # Convert the dictionary to a DataFrame
    metrics_df = pd.DataFrame(metrics_dict).T
    metrics_df[['Annual Return', 'Max Drawdown', 'Volatility', 'Tracking Error']] *= 100
    metrics_df[['Annual Return', 'Max Drawdown', 'Volatility', 'Tracking Error']] = metrics_df[['Annual Return', 'Max Drawdown', 'Volatility', 'Tracking Error']].applymap(lambda x: f'{x:.2f}%' if pd.notna(x) else x)

    # Display the DataFrame
    print(metrics_df.T)
    return metrics_df.T




def get_bench_perf(screen, bench, start_date, returns):
    # Generate Bench list 
    indice_ref = screen[(screen['Date']>start_date)*(screen['Weight in '+bench]>0)].reset_index()[['Date','ISIN']]
    # indice_ref["Date"]=indice_ref["Date"].apply(lambda x: x + relativedelta.relativedelta(months=1,day=1)) OLD ONE
    indice_ref["Date"] = pd.to_datetime(indice_ref["Date"])
    indice_ref["Date"] = indice_ref["Date"] + pd.offsets.MonthBegin(1) # NEW ONE
    
    perf_bench, indice = backtest(indice_ref, bench, screen, returns)
    return perf_bench


def plot_ptf_bench(*args, title=None):
    import pandas as pd
    import matplotlib
    matplotlib.use('Agg')  # Set backend before importing pyplot
    import matplotlib.pyplot as plt
    
    # Create figure and plot
    plt.figure(figsize=(7, 4))
    
    # Concatenate dataframes
    df_plot = pd.concat([*args], axis=1)
    
    # Create the plot
    for i, col in enumerate(df_plot.columns):
        label = 'Perf PTF' if i == 0 else 'Perf Bench'
        line = plt.plot(df_plot.iloc[:, i], label=label)[0]
        
        # Annotate last value
        last_x = df_plot.index[-1]
        last_y = df_plot.iloc[:, i].iloc[-1]  # Convert to float
        plt.annotate(f'{last_y:.2f}', 
                    xy=(last_x, last_y), 
                    xytext=(5, 0),
                    textcoords='offset points', 
                    fontsize=10, 
                    color=line.get_color())
    
    # Customize plot
    if title:
        plt.title(title)
    plt.grid(True)
    plt.box(False)
    plt.legend()
    plt.show()
    
    # Save plot
    if title:
        plt.savefig(f"{title}.png", bbox_inches='tight', dpi=300)
    else:
        plt.savefig("plot.png", bbox_inches='tight', dpi=300)




def calculate_portfolio_metrics(portfolio, benchmark, annualization_factor=252):
    """
    Calculate key portfolio metrics including Annual Return, Max Drawdown, Volatility,
    Tracking Error, Beta, and R-squared.

    Parameters:
    -----------
    portfolio : pandas.Series or pandas.DataFrame
        Time series of portfolio values or returns.
    benchmark : pandas.Series or pandas.DataFrame
        Time series of benchmark values or returns.
    annualization_factor : int, optional (default=252)
        Number of periods in a year. Default is 252 (trading days).

    Returns:
    --------
    dict
        Dictionary containing the calculated metrics:
        - 'annual_return': Annualized portfolio return
        - 'max_drawdown': Maximum peak-to-trough decline
        - 'volatility': Annualized volatility
        - 'tracking_error': Annualized tracking error
        - 'beta': Portfolio beta relative to the benchmark
        - 'r_squared': R-squared (coefficient of determination)
    """
    
    import numpy as np
    import pandas as pd
    
    # Ensure input is DataFrame
    if isinstance(portfolio, pd.Series):
        portfolio = portfolio.to_frame(name='Portfolio')
    if isinstance(benchmark, pd.Series):
        benchmark = benchmark.to_frame(name='Benchmark')

    # Align the data and calculate returns
    aligned_data = pd.concat([portfolio, benchmark], axis=1, join='inner')
    aligned_data.columns = ['Portfolio', 'Benchmark']
    returns = aligned_data.pct_change().dropna()

    # Calculate Annual Return
    total_return = (1 + returns['Portfolio']).prod()
    time_period = len(returns) / annualization_factor
    annual_return = (total_return ** (1/time_period)) - 1

    # Calculate Max Drawdown
    cumulative_returns = (1 + returns['Portfolio']).cumprod()
    rolling_max = cumulative_returns.expanding().max()
    drawdowns = cumulative_returns / rolling_max - 1
    max_drawdown = drawdowns.min()

    # Calculate Volatility (annualized)
    volatility = returns['Portfolio'].std() * np.sqrt(annualization_factor)

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
        'annual_return': annual_return,
        'max_drawdown': max_drawdown,
        'volatility': volatility,
        'tracking_error': tracking_error,
        'beta': beta,
        'r_squared': r_squared
    }


def add_multiple_offset_data(screen, offset_months_list, columns_to_add):
    """
    Add offset data to the screen dataframe for multiple offsets.
    
    :param screen: Original dataframe, frequency of index of the df should be monthly.
    :param offset_months_list: List of number of months to offset (can be negative for past data)
    :param columns_to_add: List of column names to add with offset
    :return: DataFrame with added offset columns
    """
    # Ensure 'Date' is datetime
    # screen['Date'] = pd.to_datetime(screen['Date'])
    
    # Sort the dataframe
    screen = screen.sort_values(['ISIN', 'Date'])
    
    # Get unique sorted dates
    unique_dates = screen['Date'].sort_values().unique()
    
    result = screen.copy()
    
    for offset_months in offset_months_list:
        # Create a dictionary mapping each date to its offset date
        offset_map = {}
        for i, date in enumerate(unique_dates):
            offset_index = i - offset_months
            if 0 <= offset_index < len(unique_dates):
                offset_map[date] = unique_dates[offset_index]
        
        # Function to get the offset date
        def get_offset_date(date):
            return offset_map.get(date, pd.NaT)
        
        # Create a copy of the dataframe for offset data
        screen_offset = screen[['ISIN', 'Date'] + columns_to_add].copy()
        screen_offset['Date'] = screen_offset['Date'].map(get_offset_date)
        
        # Rename columns for offset data
        screen_offset.columns = ['ISIN', 'Date'] + [f'{col}_offset_{offset_months}M' for col in columns_to_add]
        
        # Merge original data with offset data
        result = pd.merge(result, screen_offset, 
                          left_on=['ISIN', 'Date'],
                          right_on=['ISIN', 'Date'],
                          how='left')
    
    return result

def process_columns(screen, columns_to_test, offset_months=-3):
    # Convert string input to list if needed
    if isinstance(columns_to_test, str):
        columns_to_test = [columns_to_test]
        
    # Rest of the function remains the same
    screen = screen.copy()
    screen = screen.reset_index()
    
    for col in screen.select_dtypes(include=['float64']).columns:
        screen[col] = screen[col].astype('float32')
    
    groups = ['Exchange Country Region', ' Benchmark ICB Industry ']
    
    for column in columns_to_test:
        base_name = column.split()[0]
        
        screen[base_name] = (screen.groupby(groups)[column]
                           .transform(lambda x: (x.rank(pct=True) - x.rank(pct=True).min()) / 
                                    (x.rank(pct=True).max() - x.rank(pct=True).min())))
        
        screen = add_multiple_offset_data(screen, 
                                        offset_months_list=[offset_months],
                                        columns_to_add=[base_name])
        
        offset_column = f"{base_name}_offset_{offset_months}M"
        screen[offset_column].fillna(0, inplace=True)
        
        change_column = f"{base_name}_change_{abs(offset_months)}M"
        screen[change_column] = screen[base_name] - screen[offset_column]
        
        screen[change_column] = (screen.groupby(groups)[change_column]
                               .transform(lambda x: ((x.rank(pct=True) - x.rank(pct=True).min()) / 
                                                   (x.rank(pct=True).max() - x.rank(pct=True).min())) * 10))
        
        if offset_column not in columns_to_test:
            screen.drop(columns=[offset_column], inplace=True)
    
    return screen.set_index('ISIN')

# %matplotlib inline
from typing import Optional, Tuple, Union
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime
def plot_relative_performance(
    price_ptf: pd.Series, 
    price_bench: pd.Series, 
    start_date: Optional[Union[str, datetime]] = None, 
    window: int = 126, 
    figsize: Tuple[int, int] = (12, 4)
) -> plt.Figure:
    """
    Plot relative performance analysis between portfolio and benchmark
    
    Parameters
    ----------
    price_ptf : pd.Series
        Portfolio prices time series with DateTimeIndex
        Values should be float/numeric type
    price_bench : pd.Series
        Benchmark prices time series with DateTimeIndex
        Values should be float/numeric type
    start_date : str or datetime, optional
        Start date for the analysis in format 'YYYY-MM-DD'
        If None, uses entire data series
    window : int, default 252
        Rolling window size for moving average calculation
        Typically 252 for daily data (1 trading year)
    figsize : tuple of int, default (12, 4)
        Figure size in inches (width, height)
    
    Returns
    -------
    matplotlib.figure.Figure
        The generated figure object containing the plot
    
    Examples
    --------
    >>> fig = plot_relative_performance(
    ...     price_ptf=portfolio_series,
    ...     price_bench=benchmark_series,
    ...     start_date='2020-01-01',
    ...     window=252
    ... )
    """
    
    # Filter data from start_date if provided
    if start_date:
        price_ptf = price_ptf[price_ptf.index >= start_date]
        price_bench = price_bench[price_bench.index >= start_date]
    
    # Calculate relative returns and performance metrics
    rel_returns = price_ptf.pct_change() - price_bench.pct_change()
    rolling_rel_performance = rel_returns.rolling(window=window).mean()
    cumul_rel_returns = (1 + rel_returns).cumprod() - 1
    
    # Create the plot
    fig, ax1 = plt.subplots(figsize=figsize)
    
    # Plot rolling relative performance on left axis
    ax1.plot(rolling_rel_performance.index, rolling_rel_performance.values, 
             label='Rolling Relative Performance', color='blue')
    ax1.axhline(y=0, color='black', linestyle='--', alpha=0.3)
    ax1.set_xlabel('Date')
    ax1.set_ylabel('Rolling Relative Performance')
    
    # Create second y-axis and plot cumulative returns
    ax2 = ax1.twinx()
    ax2.plot(cumul_rel_returns.index, cumul_rel_returns.values, 
             label='Cumulative Relative Returns', color='red')
    ax2.set_ylabel('Cumulative Relative Returns')
    
    # Combine legends
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
    
    plt.title('Portfolio Relative Performance Analysis')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    fig.show()

from xbbg import blp
def get_bloom_security_data(ticker, start_date='2022-01-01', flds=['last_price'], end_date=datetime.now().date()):
    """
    Retrieve historical data for a Bloomberg security.

    This function fetches historical data for a specified Bloomberg security (ticker)
    over a given date range, using the Bloomberg Data History (BDH) function.
    """
    data = blp.bdh(tickers=ticker, flds=flds, start_date=start_date, end_date=end_date)
    data = data[ticker].rename(columns={flds[0]: ticker})
    return data



##########################################################################################################################################
##########################################################################################################################################
##########################################################################################################################################

def analyze_strategy_robustness(bench_returns, strat_returns):
    """Analyze the robustness of a strategy."""
    metrics = {
        'total_return': (1 + strat_returns).prod() - 1,
        'annual_return': (1 + strat_returns).prod() ** (252/len(strat_returns)) - 1,
        'volatility': strat_returns.std() * np.sqrt(252),
        'sharpe_ratio': (strat_returns.mean() / strat_returns.std()) * np.sqrt(252),
        'max_drawdown': calculate_max_drawdown((1 + strat_returns).cumprod()),
        'alpha': calculate_alpha(strat_returns, bench_returns),
        'beta': calculate_beta(strat_returns, bench_returns),
        'tracking_error': calculate_tracking_error(strat_returns, bench_returns),
        'information_ratio': calculate_information_ratio(strat_returns, bench_returns),
        'hit_ratio': calculate_hit_ratio(strat_returns, bench_returns),
        'win_loss_ratio': calculate_win_loss_ratio(strat_returns),
        'relative_sortino': calculate_sortino_ratio(strat_returns, bench_returns),
        'calmar': calculate_calmar_ratio(strat_returns)
    }
    return metrics


# def calculate_rolling_metrics(bench_returns, strat_returns, window_size):
#     """Calculate rolling performance metrics."""
#     rolling_metrics = pd.DataFrame(index=strat_returns.index)
    
#     # Original metrics
#     rolling_metrics['returns'] = strat_returns.rolling(window=window_size).mean() * 252
#     rolling_metrics['volatility'] = strat_returns.rolling(window=window_size).std() * np.sqrt(252)
#     rolling_metrics['sharpe'] = (rolling_metrics['returns'] / rolling_metrics['volatility'])
    
#     rolling_cov = strat_returns.rolling(window=window_size).cov(bench_returns)
#     rolling_var = bench_returns.rolling(window=window_size).var()
#     rolling_metrics['beta'] = rolling_cov / rolling_var
#     rolling_metrics['alpha'] = (rolling_metrics['returns'] - 
#                               rolling_metrics['beta'] * bench_returns.rolling(window=window_size).mean() * 252)
#     rolling_metrics['ratio'] = ((1+strat_returns).cumprod()-1)/((1+bench_returns).cumprod()-1)

#     # Additional metrics
#     for t in range(window_size-1, len(strat_returns)):
#         window_strat = strat_returns.iloc[t-window_size+1:t+1]
#         window_bench = bench_returns.iloc[t-window_size+1:t+1]
        
#         # rolling_metrics.loc[strat_returns.index[t], 'total_return'] = (1 + window_strat).prod() - 1
#         rolling_metrics.loc[strat_returns.index[t], 'annual_return'] = (1 + window_strat).prod() ** (252/window_size) - 1
#         rolling_metrics.loc[strat_returns.index[t], 'max_drawdown'] = calculate_max_drawdown((1 + window_strat).cumprod())
#         rolling_metrics.loc[strat_returns.index[t], 'tracking_error'] = calculate_tracking_error(window_strat, window_bench)
#         rolling_metrics.loc[strat_returns.index[t], 'information_ratio'] = calculate_information_ratio(window_strat, window_bench)
#         rolling_metrics.loc[strat_returns.index[t], 'hit_ratio'] = calculate_hit_ratio(window_strat, window_bench)
#         rolling_metrics.loc[strat_returns.index[t], 'win_loss_ratio'] = calculate_win_loss_ratio(window_strat)
#         rolling_metrics.loc[strat_returns.index[t], 'relative_sortino'] = calculate_sortino_ratio(window_strat, window_bench)
#         rolling_metrics.loc[strat_returns.index[t], 'calmar'] = calculate_calmar_ratio(window_strat)
    


#     return rolling_metrics


# def calculate_rolling_metrics(bench_returns, strat_returns, window_size):
#     """
#     Calculate rolling performance metrics using matrix operations.
    
#     Parameters:
#     -----------
#     bench_returns : pd.Series
#         Benchmark returns series
#     strat_returns : pd.Series
#         Strategy returns series
#     window_size : int
#         Size of the rolling window
    
#     Returns:
#     --------
#     pd.DataFrame
#         DataFrame containing rolling metrics
#     """
#     # Convert series to numpy arrays for faster operations
#     bench_arr = bench_returns.values
#     strat_arr = strat_returns.values
    
#     # Create rolling windows using stride tricks
#     bench_rolls = np.lib.stride_tricks.sliding_window_view(bench_arr, window_size)
#     strat_rolls = np.lib.stride_tricks.sliding_window_view(strat_arr, window_size)
    
#     # Initialize DataFrame
#     rolling_metrics = pd.DataFrame(index=strat_returns.index[window_size-1:])
    
#     # Calculate relative returns (strategy returns - benchmark returns)
#     relative_returns = strat_arr - bench_arr
#     relative_rolls = np.lib.stride_tricks.sliding_window_view(relative_returns, window_size)
#     rolling_metrics['relative_returns'] = np.mean(relative_rolls, axis=1) * 252
    
#     # Calculate relative total returns
#     strat_cum_total = np.cumprod(1 + strat_arr)
#     bench_cum_total = np.cumprod(1 + bench_arr)
#     relative_total_returns = (strat_cum_total - bench_cum_total) / bench_cum_total

#     # Create rolling windows for relative total returns that match the index
#     relative_total_rolls = np.lib.stride_tricks.sliding_window_view(relative_total_returns, window_size)
#     rolling_metrics['relative_total_returns'] = np.mean(relative_total_rolls[-len(rolling_metrics.index):], axis=1) * 252
    
#     # Basic metrics using vectorized operations
#     rolling_metrics['returns'] = np.mean(strat_rolls, axis=1) * 252
#     rolling_metrics['volatility'] = np.std(strat_rolls, axis=1, ddof=1) * np.sqrt(252)
#     rolling_metrics['sharpe'] = rolling_metrics['returns'] / rolling_metrics['volatility']
    
#     # Beta calculation using matrix operations
#     cov_matrix = np.array([np.cov(bench_rolls[i], strat_rolls[i])[0,1] 
#                           for i in range(len(bench_rolls))])
#     var_matrix = np.var(bench_rolls, axis=1, ddof=1)
#     rolling_metrics['beta'] = cov_matrix / var_matrix
    
#     # Alpha calculation
#     bench_means = np.mean(bench_rolls, axis=1) * 252
#     rolling_metrics['alpha'] = rolling_metrics['returns'] - (rolling_metrics['beta'] * bench_means)
    
#     # Cumulative returns for ratio calculation
#     strat_cum = np.array([np.prod(1 + strat_rolls[i]) - 1 for i in range(len(strat_rolls))])
#     bench_cum = np.array([np.prod(1 + bench_rolls[i]) - 1 for i in range(len(bench_rolls))])
#     rolling_metrics['ratio'] = (1 + strat_cum) / (1 + bench_cum)
    
#     # Relative cumulative returns
#     relative_cum = np.array([np.prod(1 + relative_rolls[i]) - 1 for i in range(len(relative_rolls))])
#     rolling_metrics['relative_cumulative'] = relative_cum
    
#     # Additional metrics using vectorized operations where possible
#     annual_returns = np.array([(1 + strat_rolls[i]).prod() ** (252/window_size) - 1 
#                               for i in range(len(strat_rolls))])
#     rolling_metrics['annual_return'] = annual_returns
    
#     # Max drawdown calculation
#     max_drawdowns = np.zeros(len(strat_rolls))
#     for i in range(len(strat_rolls)):
#         prices = np.cumprod(1 + strat_rolls[i])
#         peaks = np.maximum.accumulate(prices)
#         drawdowns = (prices - peaks) / peaks
#         max_drawdowns[i] = np.min(drawdowns)
#     rolling_metrics['max_drawdown'] = max_drawdowns
    
#     # Tracking error and information ratio
#     excess_returns = strat_rolls - bench_rolls
#     tracking_error = np.std(excess_returns, axis=1, ddof=1) * np.sqrt(252)
#     rolling_metrics['tracking_error'] = tracking_error
    
#     active_returns = np.mean(excess_returns, axis=1)
#     rolling_metrics['information_ratio'] = (active_returns * 252) / tracking_error
    
#     # Hit ratio
#     hit_ratios = np.array([np.mean(excess_returns[i] > 0) for i in range(len(excess_returns))])
#     rolling_metrics['hit_ratio'] = hit_ratios
    
#     # Win/Loss ratio
#     win_loss_ratios = np.zeros(len(strat_rolls))
#     for i in range(len(strat_rolls)):
#         wins = strat_rolls[i][strat_rolls[i] > 0].mean() if len(strat_rolls[i][strat_rolls[i] > 0]) > 0 else 0
#         losses = abs(strat_rolls[i][strat_rolls[i] < 0].mean()) if len(strat_rolls[i][strat_rolls[i] < 0]) > 0 else float('inf')
#         win_loss_ratios[i] = wins / losses if losses != 0 else float('inf')
#     rolling_metrics['win_loss_ratio'] = win_loss_ratios
    
#     # Relative Sortino ratio
#     sortino_ratios = np.zeros(len(strat_rolls))
#     for i in range(len(strat_rolls)):
#         excess_rets = strat_rolls[i] - bench_rolls[i]
#         downside_returns = excess_rets[excess_rets < 0]
#         downside_std = np.sqrt(np.mean(downside_returns**2)) if len(downside_returns) > 0 else 0
#         sortino_ratios[i] = (np.mean(excess_rets) * 252) / (downside_std * np.sqrt(252)) if downside_std != 0 else 0
#     rolling_metrics['relative_sortino'] = sortino_ratios
    
#     # Calmar ratio
#     calmar_ratios = np.zeros(len(strat_rolls))
#     for i in range(len(strat_rolls)):
#         annual_ret = (1 + strat_rolls[i]).prod() ** (252/window_size) - 1
#         max_dd = abs(max_drawdowns[i])
#         calmar_ratios[i] = annual_ret / max_dd if max_dd != 0 else float('inf')
#     rolling_metrics['calmar'] = calmar_ratios
    
#     return rolling_metrics

def calculate_rolling_metrics(bench_returns, strat_returns, window_size):
    """
    Calculate rolling performance metrics using matrix operations.
    Starting value for total return indices is 100.
    
    Parameters:
    -----------
    bench_returns : pd.Series
        Benchmark returns series
    strat_returns : pd.Series
        Strategy returns series
    window_size : int
        Size of the rolling window
    
    Returns:
    --------
    pd.DataFrame
        DataFrame containing rolling metrics
    """
    # Convert series to numpy arrays for faster operations
    bench_arr = bench_returns.values
    strat_arr = strat_returns.values
    
    # Create rolling windows using stride tricks
    bench_rolls = np.lib.stride_tricks.sliding_window_view(bench_arr, window_size)
    strat_rolls = np.lib.stride_tricks.sliding_window_view(strat_arr, window_size)
    
    # Initialize DataFrame
    rolling_metrics = pd.DataFrame(index=strat_returns.index[window_size-1:])
    
    # Calculate total returns starting from 100
    strat_cum_total = 100 * np.cumprod(1 + strat_arr)
    bench_cum_total = 100 * np.cumprod(1 + bench_arr)
    
    # Create rolling windows for total returns
    strat_total_rolls = np.lib.stride_tricks.sliding_window_view(strat_cum_total, window_size)
    bench_total_rolls = np.lib.stride_tricks.sliding_window_view(bench_cum_total, window_size)
    
    # Add total returns to rolling metrics
    rolling_metrics['strategy_ttr'] = strat_cum_total[window_size-1:]
    rolling_metrics['benchmark_ttr'] = bench_cum_total[window_size-1:]
    
    # Calculate relative returns (strategy returns - benchmark returns)
    relative_returns = strat_arr - bench_arr
    relative_rolls = np.lib.stride_tricks.sliding_window_view(relative_returns, window_size)
    rolling_metrics['relative_returns'] = np.mean(relative_rolls, axis=1) * 252
    
    # Calculate relative total returns
    relative_total_returns = (strat_cum_total - bench_cum_total) / bench_cum_total
    relative_total_rolls = np.lib.stride_tricks.sliding_window_view(relative_total_returns, window_size)
    rolling_metrics['relative_total_returns'] = np.mean(relative_total_rolls[-len(rolling_metrics.index):], axis=1) * 252
    
    # Basic metrics using vectorized operations
    rolling_metrics['returns'] = np.mean(strat_rolls, axis=1) * 252
    rolling_metrics['volatility'] = np.std(strat_rolls, axis=1, ddof=1) * np.sqrt(252)
    rolling_metrics['sharpe'] = rolling_metrics['returns'] / rolling_metrics['volatility']
    
    # Beta calculation using matrix operations
    cov_matrix = np.array([np.cov(bench_rolls[i], strat_rolls[i])[0,1] 
                          for i in range(len(bench_rolls))])
    var_matrix = np.var(bench_rolls, axis=1, ddof=1)
    rolling_metrics['beta'] = cov_matrix / var_matrix
    
    # Alpha calculation
    bench_means = np.mean(bench_rolls, axis=1) * 252
    rolling_metrics['alpha'] = rolling_metrics['returns'] - (rolling_metrics['beta'] * bench_means)
    
    # Cumulative returns for ratio calculation
    strat_cum = np.array([np.prod(1 + strat_rolls[i]) - 1 for i in range(len(strat_rolls))])
    bench_cum = np.array([np.prod(1 + bench_rolls[i]) - 1 for i in range(len(bench_rolls))])
    rolling_metrics['ratio'] = (1 + strat_cum) / (1 + bench_cum)
    
    # Relative cumulative returns
    relative_cum = np.array([np.prod(1 + relative_rolls[i]) - 1 for i in range(len(relative_rolls))])
    rolling_metrics['relative_cumulative'] = relative_cum
    
    # Additional metrics using vectorized operations where possible
    annual_returns = np.array([(1 + strat_rolls[i]).prod() ** (252/window_size) - 1 
                              for i in range(len(strat_rolls))])
    rolling_metrics['annual_return'] = annual_returns
    
    # Max drawdown calculation
    max_drawdowns = np.zeros(len(strat_rolls))
    for i in range(len(strat_rolls)):
        prices = np.cumprod(1 + strat_rolls[i])
        peaks = np.maximum.accumulate(prices)
        drawdowns = (prices - peaks) / peaks
        max_drawdowns[i] = np.min(drawdowns)
    rolling_metrics['max_drawdown'] = max_drawdowns
    
    # Tracking error and information ratio
    excess_returns = strat_rolls - bench_rolls
    tracking_error = np.std(excess_returns, axis=1, ddof=1) * np.sqrt(252)
    rolling_metrics['tracking_error'] = tracking_error
    
    active_returns = np.mean(excess_returns, axis=1)
    rolling_metrics['information_ratio'] = (active_returns * 252) / tracking_error
    
    # Hit ratio
    hit_ratios = np.array([np.mean(excess_returns[i] > 0) for i in range(len(excess_returns))])
    rolling_metrics['hit_ratio'] = hit_ratios
    
    # Win/Loss ratio
    win_loss_ratios = np.zeros(len(strat_rolls))
    for i in range(len(strat_rolls)):
        wins = strat_rolls[i][strat_rolls[i] > 0].mean() if len(strat_rolls[i][strat_rolls[i] > 0]) > 0 else 0
        losses = abs(strat_rolls[i][strat_rolls[i] < 0].mean()) if len(strat_rolls[i][strat_rolls[i] < 0]) > 0 else float('inf')
        win_loss_ratios[i] = wins / losses if losses != 0 else float('inf')
    rolling_metrics['win_loss_ratio'] = win_loss_ratios
    
    # Relative Sortino ratio
    sortino_ratios = np.zeros(len(strat_rolls))
    for i in range(len(strat_rolls)):
        excess_rets = strat_rolls[i] - bench_rolls[i]
        downside_returns = excess_rets[excess_rets < 0]
        downside_std = np.sqrt(np.mean(downside_returns**2)) if len(downside_returns) > 0 else 0
        sortino_ratios[i] = (np.mean(excess_rets) * 252) / (downside_std * np.sqrt(252)) if downside_std != 0 else 0
    rolling_metrics['relative_sortino'] = sortino_ratios
    
    # Calmar ratio
    calmar_ratios = np.zeros(len(strat_rolls))
    for i in range(len(strat_rolls)):
        annual_ret = (1 + strat_rolls[i]).prod() ** (252/window_size) - 1
        max_dd = abs(max_drawdowns[i])
        calmar_ratios[i] = annual_ret / max_dd if max_dd != 0 else float('inf')
    rolling_metrics['calmar'] = calmar_ratios
    
    return rolling_metrics

def calculate_max_drawdown(prices):
    """Calculate the maximum drawdown of a price series."""
    peaks = prices.expanding(min_periods=1).max()
    drawdowns = (prices - peaks) / peaks
    return drawdowns.min()

def calculate_alpha(strat_returns, bench_returns):
    """Calculate strategy alpha."""
    beta = calculate_beta(strat_returns, bench_returns)
    alpha = strat_returns.mean() * 252 - beta * (bench_returns.mean() * 252)
    return alpha

def calculate_beta(strat_returns, bench_returns):
    """Calculate strategy beta."""
    covariance = strat_returns.cov(bench_returns)
    variance = bench_returns.var()
    return covariance / variance

def calculate_tracking_error(strat_returns, bench_returns):
    """Calculate tracking error."""
    return (strat_returns - bench_returns).std() * np.sqrt(252)

def calculate_information_ratio(strat_returns, bench_returns):
    """Calculate information ratio."""
    active_return = strat_returns.mean() - bench_returns.mean()
    tracking_error = calculate_tracking_error(strat_returns, bench_returns)
    return (active_return * 252) / tracking_error if tracking_error != 0 else 0

def calculate_hit_ratio(strat_returns, bench_returns):
    """Calculate hit ratio."""
    active_returns = strat_returns - bench_returns
    hits = (active_returns > 0).sum()
    return hits / len(active_returns)

def calculate_win_loss_ratio(returns):
    """Calculate win/loss ratio."""
    wins = returns[returns > 0].mean()
    losses = abs(returns[returns < 0].mean())
    return wins / losses if losses != 0 else float('inf')

def calculate_sortino_ratio(returns, rf):
    """Calculate Sortino ratio."""
    excess_returns = returns - rf
    downside_returns = returns[returns < 0]
    downside_std = np.sqrt(np.mean(downside_returns**2))
    return (excess_returns.mean() * 252) / (downside_std * np.sqrt(252)) if downside_std != 0 else 0

def calculate_calmar_ratio(returns):
    """Calculate Calmar ratio."""
    prices = (1 + returns).cumprod()
    max_dd = abs(calculate_max_drawdown(prices))
    annual_return = (1 + returns).prod() ** (252/len(returns)) - 1
    return annual_return / max_dd if max_dd != 0 else float('inf')



def analyze_strategy_windows(bench_prices, strategy_prices, window_size, start_date=None, stability_analysis=False, plot=False):
    """Analyze strategy performance using rolling windows."""
    # First check if we have any data
    if len(bench_prices) == 0 or len(strategy_prices) == 0:
        raise ValueError("Input price series are empty")
    
    # Filter data from start_date if provided
    if start_date is not None:
        start_date = pd.to_datetime(start_date)
        bench_prices = bench_prices[bench_prices.index >= start_date]
        strategy_prices = strategy_prices[strategy_prices.index >= start_date]

    # Make sure the indices align
    bench_prices = bench_prices.align(strategy_prices)[0]
    strategy_prices = strategy_prices.align(bench_prices)[0]
    
    # Calculate returns
    bench_returns = bench_prices.pct_change().dropna()
    strat_returns = strategy_prices.pct_change().dropna()
    
    # Ensure we still have data after alignment and return calculation
    if len(bench_returns) == 0 or len(strat_returns) == 0:
        raise ValueError("No overlapping data between benchmark and strategy")
    
    # # Print data info for debugging
    # print(f"Length of data: {len(bench_returns)} periods")
    # print(f"Date range: {bench_returns.index[0]} to {bench_returns.index[-1]}")
    
    # Initialize results dictionary
    results = {}

    # Calculate metrics once
    rolling_metrics = calculate_rolling_metrics(bench_returns, strat_returns, window_size)
    results['rolling_metrics'] = rolling_metrics


    if stability_analysis:
        # Generate stability analysis
        stability = pd.DataFrame({
            'mean': rolling_metrics.mean(),
            'std': rolling_metrics.std(),
            'min': rolling_metrics.min(),
            'max': rolling_metrics.max(),
            'stability_ratio': rolling_metrics.mean() / rolling_metrics.std(),
            'skew': rolling_metrics.skew(),
            'kurtosis': rolling_metrics.kurtosis(),
            '5th_percentile': rolling_metrics.quantile(0.05),
            '95th_percentile': rolling_metrics.quantile(0.95)
        })
        results['stability_analysis'] = stability.T

    if plot:
        # Generate plots
        fig, axes = plt.subplots(2, 7, figsize=(22, 8))
        fig.suptitle('Rolling Performance Metrics')
        
        # Flatten axes for easier iteration
        axes_flat = axes.flatten()
        
        # Plot all metrics
        for i, col in enumerate(rolling_metrics.columns):
            if i < len(axes_flat):
                rolling_metrics[col].plot(ax=axes_flat[i], 
                                        title=f'Rolling {col.replace("_", " ").title()}')
                
                # Add reference lines for certain metrics
                if col in ['returns', 'sharpe', 'alpha', 'information_ratio']:
                    axes_flat[i].axhline(y=0, color='r', linestyle='--')
                elif col == 'beta':
                    axes_flat[i].axhline(y=1, color='r', linestyle='--')
        
        # Remove any empty subplots
        for i in range(len(rolling_metrics.columns), len(axes_flat)):
            fig.delaxes(axes_flat[i])
        
        plt.tight_layout()
        results['plot'] = fig
    
    return results


from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
def detect_market_regime(prices, vol_window, trend_window, use_markov=True):
    """
    Detect market regimes using both traditional methods and Markov Switching
    """
    if len(prices) == 0:
        raise ValueError("Input price series is empty")
        
    returns = prices.pct_change().dropna()
    
    if len(returns) < max(vol_window, trend_window):
        raise ValueError(f"Insufficient data. Need at least {max(vol_window, trend_window)} periods")
    
    # Traditional method
    rolling_vol = returns.rolling(window=vol_window).std() * np.sqrt(252)
    vol_regime = pd.qcut(rolling_vol, q=3, labels=['low', 'medium', 'high'])
    
    rolling_returns = returns.rolling(window=trend_window).mean()
    trend = pd.Series(index=returns.index, data='neutral')
    trend[rolling_returns > 0] = 'uptrend'
    trend[rolling_returns < 0] = 'downtrend'
    
    # Markov Switching detection
    if use_markov:
        try:
            # Standardize returns to improve convergence
            returns_standardized = (returns - returns.mean()) / returns.std()
            
            # Try different starting parameters
            best_model = None
            best_aic = np.inf
            
            # Different configurations to try
            configs = [
                {'k_regimes': 2, 'trend': 'c', 'switching_variance': True},
                {'k_regimes': 3, 'trend': 'c', 'switching_variance': True},
                {'k_regimes': 2, 'trend': 'c', 'switching_variance': False},
                {'k_regimes': 3, 'trend': 'c', 'switching_variance': False}
            ]
            
            for config in configs:
                try:
                    mod = MarkovRegression(
                        returns_standardized,
                        **config,
                        switching_trend=True
                    )
                    
                    # Try multiple starting values
                    for _ in range(4):
                        try:
                            res = mod.fit(
                                maxiter=1000,
                                optim_score='harvey',
                                search_reps=20,
                                random_state=np.random.randint(1000)
                            )
                            
                            if res.aic < best_aic:
                                best_model = res
                                best_aic = res.aic
                                
                        except:
                            continue
                            
                except:
                    continue
            
            if best_model is None:
                raise ValueError("No convergent model found")
                
            # Get smoothed probabilities from best model
            smoothed_probs = best_model.smoothed_marginal_probabilities
            
            # Determine regime based on highest probability
            markov_regimes = pd.Series(index=returns.index, data=np.nan)
            for t in range(len(returns)):
                markov_regimes[t] = np.argmax(smoothed_probs[t]) + 1
            
            # Calculate regime characteristics
            regime_stats = {}
            for regime in range(1, len(smoothed_probs[0]) + 1):
                mask = markov_regimes == regime
                if mask.any():
                    regime_stats[regime] = {
                        'mean': returns[mask].mean(),
                        'vol': returns[mask].std() * np.sqrt(252),
                        'count': mask.sum()
                    }
            
            # Label regimes based on characteristics
            # Sort regimes by volatility
            sorted_regimes = sorted(regime_stats.items(), key=lambda x: x[1]['vol'])
            regime_mapping = {}
            
            if len(sorted_regimes) == 2:
                regime_mapping = {
                    sorted_regimes[0][0]: 'low_vol',
                    sorted_regimes[1][0]: 'high_vol'
                }
            else:
                regime_mapping = {
                    sorted_regimes[0][0]: 'low_vol',
                    sorted_regimes[1][0]: 'medium_vol',
                    sorted_regimes[2][0]: 'high_vol'
                }
            
            markov_vol_regime = markov_regimes.map(regime_mapping)
            
            # Sort regimes by returns
            sorted_returns = sorted(regime_stats.items(), key=lambda x: x[1]['mean'])
            regime_mapping_returns = {}
            
            if len(sorted_returns) == 2:
                regime_mapping_returns = {
                    sorted_returns[0][0]: 'bear',
                    sorted_returns[1][0]: 'bull'
                }
            else:
                regime_mapping_returns = {
                    sorted_returns[0][0]: 'bear',
                    sorted_returns[1][0]: 'neutral',
                    sorted_returns[2][0]: 'bull'
                }
            
            markov_trend_regime = markov_regimes.map(regime_mapping_returns)
            
            # Print model diagnostics
            print("\nMarkov Model Diagnostics:")
            print(f"AIC: {best_model.aic:.2f}")
            print(f"BIC: {best_model.bic:.2f}")
            print(f"Log Likelihood: {best_model.llf:.2f}")
            print("\nRegime Statistics:")
            for regime, stats in regime_stats.items():
                print(f"\nRegime {regime}:")
                print(f"Mean Return: {stats['mean']*252:.2%}")
                print(f"Annualized Volatility: {stats['vol']:.2%}")
                print(f"Number of observations: {stats['count']}")
            
        except Exception as e:
            print(f"Warning: Markov switching model failed: {str(e)}")
            print("Using traditional method only.")
            markov_vol_regime = vol_regime
            markov_trend_regime = trend
    if use_markov:
        regimes = pd.DataFrame({
            'volatility': vol_regime,
            'trend': trend,
            'markov_volatility': markov_vol_regime,
            'markov_trend': markov_trend_regime
        }, index=returns.index)
    else:
        regimes = pd.DataFrame({
            'volatility': vol_regime,
            'trend': trend
        }, index=returns.index)
    
    return regimes

def analyze_regime_performance(bench_prices, strategy_prices, regimes):
    if len(bench_prices) == 0 or len(strategy_prices) == 0:
        raise ValueError("Input price series are empty")
    
    bench_prices, strategy_prices = bench_prices.align(strategy_prices)
    bench_returns = bench_prices.pct_change().dropna()
    strat_returns = strategy_prices.pct_change().dropna()
    
    regimes = regimes.reindex(bench_returns.index)
    
    print(f"Number of returns periods: {len(bench_returns)}")
    print(f"Number of regime periods: {len(regimes)}")
    print("\nTraditional Regime distribution:")
    print(regimes['trend'].value_counts())
    print(regimes['volatility'].value_counts())
    
    # Only print Markov regime distribution if they differ from traditional regimes
    if 'markov_trend' in regimes.columns and 'markov_volatility' in regimes.columns:
        print("\nMarkov Regime distribution:")
        print(regimes['markov_trend'].value_counts())
        print(regimes['markov_volatility'].value_counts())
    
    regime_results = []
    
    # Analyze traditional regimes
    for regime_type in ['trend', 'volatility']:
        for regime in regimes[regime_type].unique():
            mask = regimes[regime_type] == regime
            if mask.sum() > 0:
                metrics = analyze_strategy_robustness(
                    bench_returns[mask],
                    strat_returns[mask]
                )
                metrics['regime_type'] = f'traditional_{regime_type}'
                metrics['regime'] = regime
                regime_results.append(metrics)
    
    # Only analyze Markov regimes if the columns exist
    if 'markov_trend' in regimes.columns and 'markov_volatility' in regimes.columns:
        for regime_type in ['markov_trend', 'markov_volatility']:
            for regime in regimes[regime_type].unique():
                mask = regimes[regime_type] == regime
                if mask.sum() > 0:
                    metrics = analyze_strategy_robustness(
                        bench_returns[mask],
                        strat_returns[mask]
                    )
                    metrics['regime_type'] = regime_type
                    metrics['regime'] = regime
                    regime_results.append(metrics)
    
    df_results = pd.DataFrame(regime_results)
    df_results.set_index(['regime_type', 'regime'], inplace=True)
    
    return df_results





# def plot_relative_metrics_plotly(results, title="Relative Performance Metrics"):
#     """
#     Plot relative_total_returns, relative_returns and relative_sortino using plotly
#     with relative_total_returns on primary axis and others on secondary axis
    
#     Parameters:
#     -----------
#     results : dict
#         Results dictionary containing rolling_metrics DataFrame
#     title : str, optional
#         Plot title
    
#     Returns:
#     --------
#     plotly.graph_objects.Figure
#     """
    
#     # Create figure with secondary y-axis
#     fig = go.Figure()

#     # Add reference line at y=0
#     fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.7, yref="y2")

#     # Add relative_total_returns on primary axis
#     fig.add_trace(
#         go.Scatter(
#             x=results['rolling_metrics'].index,
#             y=results['rolling_metrics']['relative_total_returns'],
#             name='Relative Total Returns',
#             line=dict(color='blue')
#         )
#     )

#     # Add relative_returns on secondary axis
#     fig.add_trace(
#         go.Scatter(
#             x=results['rolling_metrics'].index,
#             y=results['rolling_metrics']['relative_returns'] * 20,
#             name='Relative Returns',
#             line=dict(color='red'),
#             yaxis='y2'
#         )
#     )
    
#     # Add relative_sortino on secondary axis
#     fig.add_trace(
#         go.Scatter(
#             x=results['rolling_metrics'].index,
#             y=results['rolling_metrics']['relative_sortino'],
#             name='Relative Sortino',
#             line=dict(color='green'),
#             yaxis='y2'
#         )
#     )
    
#     # Create list of dates for every year
#     date_range = results['rolling_metrics'].index
#     yearly_ticks = pd.date_range(start=date_range[0], end=date_range[-1], freq='Y')

#     # Update layout
#     fig.update_layout(
#         title=title,
#         xaxis=dict(
#             title='Date',
#             showgrid=True,
#             ticktext=[d.strftime('%Y') for d in yearly_ticks],
#             tickvals=yearly_ticks,
#             tickmode='array',
#             tickangle=45
#         ),
#         yaxis=dict(
#             title='Relative Total Returns',
#             titlefont=dict(color='blue'),
#             tickfont=dict(color='blue'),
#             showgrid=True
#         ),
#         yaxis2=dict(
#             title='Relative Returns / Sortino',
#             titlefont=dict(color='red'),
#             tickfont=dict(color='red'),
#             anchor='x',
#             overlaying='y',
#             side='right'
#         ),
#         showlegend=True,
#         legend=dict(
#             x=0,
#             y=1,
#             bgcolor='rgba(255, 255, 255, 0.8)'
#         ),
#         hovermode='x unified',
#         template='plotly_white'
#     )

#     return fig.show()

def plot_relative_metrics_plotly(results, title="Relative Performance Metrics", start_date=None):
    """
    Plot relative_total_returns, relative_returns and relative_sortino using plotly
    with relative_total_returns on primary axis and others on secondary axis
    
    Parameters:
    -----------
    results : dict
        Results dictionary containing rolling_metrics DataFrame
    title : str, optional
        Plot title
    start_date : str or datetime, optional
        Starting date for the plot in format 'YYYY-MM-DD' or datetime object
    
    Returns:
    --------
    plotly.graph_objects.Figure
    """
    
    # Filter data based on start_date if provided
    if start_date:
        if isinstance(start_date, str):
            start_date = pd.to_datetime(start_date)
        rolling_metrics = results['rolling_metrics'][results['rolling_metrics'].index >= start_date]
    else:
        rolling_metrics = results['rolling_metrics']
    
    # Create figure with secondary y-axis
    fig = go.Figure()

    # Add reference line at y=0
    fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.7, yref="y2")

    # Add relative_total_returns on primary axis
    # fig.add_trace(
    #     go.Scatter(
    #         x=rolling_metrics.index,
    #         y=rolling_metrics['relative_total_returns'],
    #         name='Relative Total Returns',
    #         line=dict(color='blue')
    #     )
    # )

    # Add strategy_ttr on primary axis
    fig.add_trace(
        go.Scatter(
            x=rolling_metrics.index,
            y=rolling_metrics['strategy_ttr']/rolling_metrics['strategy_ttr'][0]*100,
            name='Strategy TTR',
            line=dict(color='blue')
        )
    )

    # Add benchmark_ttr on primary axis
    fig.add_trace(
        go.Scatter(
            x=rolling_metrics.index,
            y=rolling_metrics['benchmark_ttr']/rolling_metrics['benchmark_ttr'][0]*100,
            name='Benchmark TTR',
            line=dict(color='gray')
        )
    )

    # Add relative_returns on secondary axis
    fig.add_trace(
        go.Scatter(
            x=rolling_metrics.index,
            y=rolling_metrics['relative_returns'] * 20,
            name='Relative Returns',
            line=dict(color='green'),
            yaxis='y2'
        )
    )
    
    # Add relative_sortino on secondary axis
    fig.add_trace(
        go.Scatter(
            x=rolling_metrics.index,
            y=rolling_metrics['relative_sortino'],
            name='Relative Sortino',
            line=dict(color='red'),
            yaxis='y2'
        )
    )
    
    # Create list of dates for every year
    date_range = rolling_metrics.index
    yearly_ticks = pd.date_range(start=date_range[0], end=date_range[-1], freq='Y')

    # Update layout
    fig.update_layout(
        title=title,
        xaxis=dict(
            title='Date',
            showgrid=True,
            ticktext=[d.strftime('%Y') for d in yearly_ticks],
            tickvals=yearly_ticks,
            tickmode='array',
            tickangle=45
        ),
        yaxis=dict(
            title='Relative Total Returns',
            titlefont=dict(color='blue'),
            tickfont=dict(color='blue'),
            showgrid=True
        ),
        yaxis2=dict(
            title='Relative Returns / Sortino',
            titlefont=dict(color='red'),
            tickfont=dict(color='red'),
            anchor='x',
            overlaying='y',
            side='right'
        ),
        showlegend=True,
        legend=dict(
            x=0,
            y=1,
            bgcolor='rgba(255, 255, 255, 0.8)'
        ),
        hovermode='x unified',
        template='plotly_white'
    )

    return fig.show()


# def plot_relative_metrics_plotly(results, title="Performance Metrics", start_date=None):
#     """
#     Plot strategy_ttr, benchmark_ttr, relative metrics using plotly
#     with TTR on primary axis and relative metrics on secondary axis
    
#     Parameters:
#     -----------
#     results : dict
#         Results dictionary containing rolling_metrics DataFrame
#     title : str, optional
#         Plot title
#     start_date : str or datetime, optional
#         Starting date for the plot in format 'YYYY-MM-DD' or datetime object
#     """
    
#     # Filter data based on start_date if provided
#     if start_date:
#         if isinstance(start_date, str):
#             start_date = pd.to_datetime(start_date)
#         rolling_metrics = results['rolling_metrics'][results['rolling_metrics'].index >= start_date]
#     else:
#         rolling_metrics = results['rolling_metrics']
    
#     # Create figure with secondary y-axis
#     fig = go.Figure()

#     # Add reference line at y=0 for secondary axis
#     fig.add_hline(y=0, line_dash="dash", line_color="grey", opacity=0.7, yref="y2")

#     # Add strategy_ttr on primary axis
#     fig.add_trace(
#         go.Scatter(
#             x=rolling_metrics.index,
#             y=rolling_metrics['strategy_ttr'],
#             name='Strategy TTR',
#             line=dict(color='blue')
#         )
#     )

#     # Add benchmark_ttr on primary axis
#     fig.add_trace(
#         go.Scatter(
#             x=rolling_metrics.index,
#             y=rolling_metrics['benchmark_ttr'],
#             name='Benchmark TTR',
#             line=dict(color='gray')
#         )
#     )

#     # Add relative_returns on secondary axis
#     fig.add_trace(
#         go.Scatter(
#             x=rolling_metrics.index,
#             y=rolling_metrics['relative_returns'],
#             name='Relative Returns',
#             line=dict(color='red'),
#             yaxis='y2'
#         )
#     )
    
#     # Add relative_sortino on secondary axis
#     fig.add_trace(
#         go.Scatter(
#             x=rolling_metrics.index,
#             y=rolling_metrics['relative_sortino'],
#             name='Relative Sortino',
#             line=dict(color='green'),
#             yaxis='y2'
#         )
#     )
    
#     # Create list of dates for every year
#     date_range = rolling_metrics.index
#     yearly_ticks = pd.date_range(start=date_range[0], end=date_range[-1], freq='Y')

#     # Update layout
#     fig.update_layout(
#         title=title,
#         xaxis=dict(
#             title='Date',
#             showgrid=True,
#             ticktext=[d.strftime('%Y') for d in yearly_ticks],
#             tickvals=yearly_ticks,
#             tickmode='array',
#             tickangle=45
#         ),
#         yaxis=dict(
#             title='Total Return Index (Starting at 100)',
#             titlefont=dict(color='black'),
#             tickfont=dict(color='black'),
#             showgrid=True
#         ),
#         yaxis2=dict(
#             title='Relative Metrics',
#             titlefont=dict(color='red'),
#             tickfont=dict(color='red'),
#             anchor='x',
#             overlaying='y',
#             side='right'
#         ),
#         showlegend=True,
#         legend=dict(
#             x=0,
#             y=1,
#             bgcolor='rgba(255, 255, 255, 0.8)'
#         ),
#         hovermode='x unified',
#         template='plotly_white'
#     )

#     return fig.show()
import matplotlib.pyplot as plt
import pandas as pd
import dataframe_image as dfi
import textwrap
import numpy as np
from xbbg import blp
from datetime import datetime, timedelta

def get_bloom_security_data(ticker, start_date='2022-01-01', flds=['last_price'], end_date=datetime.now().date()):
    """
    Retrieve historical data for a Bloomberg security.

    This function fetches historical data for a specified Bloomberg security (ticker)
    over a given date range, using the Bloomberg Data History (BDH) function.
    """
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
import dataframe_image as dfi
import textwrap

def save_dataframe_as_image(df, filename, max_rows=None, max_cols=None, col_width=8, font_size=9):
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
        {'selector': 'th', 'props': [('background-color', '#63a1c7'), 
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
    dfi.export(styled_df, filename)
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
    """
    Create a reverse mapping of sector codes to sector names.

    This function takes a dictionary mapping sector names to sector codes
    and returns a new dictionary with the mappings reversed.

    Parameters:
    -----------
    sector_dict : dict
        A dictionary where keys are sector names (str) and values are sector codes (float or int).

    Returns:
    --------
    dict
        A new dictionary where keys are sector codes (float or int) and values are sector names (str).
    """
    return {v: k for k, v in sector_dict.items()}


def calculate_portfolio_metrics(portfolio, benchmark, annualization_factor=252):
    """
    Calculate key portfolio metrics: Tracking Error, Beta, and R-squared.

    This function takes two pandas Series or DataFrames representing a portfolio
    and its benchmark, aligns their data, and calculates various performance metrics.

    Parameters:
    -----------
    portfolio : pandas.Series or pandas.DataFrame
        Time series of portfolio values or returns.
    benchmark : pandas.Series or pandas.DataFrame
        Time series of benchmark values or returns.
    annualization_factor : int, optional (default=252)
        Number of periods in a year, used for annualizing the tracking error.
        Default is 252 (assuming daily data and 252 trading days in a year).

    Returns:
    --------
    dict
        A dictionary containing the calculated metrics:
        - 'tracking_error': Annualized tracking error
        - 'beta': Portfolio beta relative to the benchmark
        - 'r_squared': R-squared (coefficient of determination)

    Notes:
    ------
    - The function assumes that the input data represents prices or values, not returns.
    - The function will align the data based on shared dates and calculate returns internally.
    - NaN values at the beginning of the returns series (due to pct_change) are dropped.

    Examples:
    ---------
    >>> portfolio = pd.Series([100, 101, 103, 102, 104], index=pd.date_range('2023-01-01', periods=5))
    >>> benchmark = pd.Series([100, 102, 101, 103, 102], index=pd.date_range('2023-01-01', periods=5))
    >>> metrics = calculate_portfolio_metrics(portfolio, benchmark)
    >>> print(metrics)
    """
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
    """
    Calculate periodic returns for specified columns in a DataFrame.

    This function computes returns for various time periods (1 week, 1 month, 3 months, 
    6 months, and 1 year) based on the daily returns provided in the input DataFrame.

    Parameters:
    -----------
    df : pandas.DataFrame
        A DataFrame with a DatetimeIndex and columns representing daily returns.
    columns : list of str, optional
        List of column names to calculate returns for. If None, uses all columns in df.
    start_date : str or datetime, optional
        The start date for calculations. If None, uses the earliest date in df.
    end_date : str or datetime, optional
        The end date for calculations. If None, uses the latest date in df.

    Returns:
    --------
    pandas.DataFrame
        A DataFrame with columns for each time period and rows for each specified column
        in the input DataFrame. Values represent percentage returns.

    Raises:
    -------
    ValueError
        If none of the specified columns are in the DataFrame.

    Notes:
    ------
    - Assumes 252 trading days in a year.
    - Returns are calculated as cumulative returns over the specified period.
    - If there's insufficient data for a period, NaN is returned for that period.

    Examples:
    ---------
    >>> import pandas as pd
    >>> import numpy as np
    >>> df = pd.DataFrame({
    ...     'A': np.random.randn(300) * 0.01,
    ...     'B': np.random.randn(300) * 0.01
    ... }, index=pd.date_range(end='2023-08-30', periods=300, freq='B'))
    >>> result = calculate_periodic_returns(df)
    >>> print(result)
    """
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
    """
    Create a bar plot comparing multiple datasets.

    Parameters:
    -----------
    *args : pandas.DataFrame or pandas.Series
        One or more datasets to plot. Each dataset will be plotted as a group of bars.
    ylabel : str
        Label for the y-axis.
    title : str
        Title of the plot.
    save_path : str
        Path where the plot image will be saved.
    labels : list of str, optional
        Labels for each dataset. If None, will use default labels.
    figsize : tuple, optional
        Figure size (width, height) in inches. Default is (12, 6).
    rotation : int, optional
        Rotation angle for x-axis labels. Default is 45.
    ylim : tuple, optional
        Y-axis limits as (ymin, ymax). If None, limits are auto-set.

    Returns:
    --------
    None
    """
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
    """
    Add value labels on top of each bar.
    
    Parameters:
    ax : matplotlib.axes.Axes
        The axes object containing the bars
    rects : list
        List of matplotlib.patches.Rectangle objects (the bars)
    fontsize : int, optional
        Font size for the labels (default is 10)
    """
    for rect in rects:
        height = rect.get_height()
        ax.annotate(f'{height:.2f}',
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom',
                    fontsize=fontsize)
        



def calculate_sector_returns(returns, asset_list, start_date, end_date, periods=None):
    """
    Calculate sector-wise weighted returns for a given set of assets over multiple periods.

    Parameters:
    -----------
    returns : pandas.DataFrame
        DataFrame containing return data for all assets.
    asset_list : pandas.DataFrame
        DataFrame containing asset information (Symbol, Name, Sector, Weight).
    start_date : str
        Start date for the calculation period (format: 'YYYY-MM-DD').
    end_date : str
        End date for the calculation period (format: 'YYYY-MM-DD').
    periods : list of str, optional
        List of periods to calculate. Options: '1 Week', '1 Month', '3 Month', '6 Month', '1 Year'.
        If None, calculates all periods.

    Returns:
    --------
    pandas.DataFrame
        Sector-wise weighted returns for specified periods.
    """
    if periods is None:
        periods = ['1 Week', '1 Month', '3 Month', '6 Month', '1 Year']
    
    # Calculate periodic returns
    periodic_returns = calculate_periodic_returns(
        returns, 
        columns=asset_list['Symbol'].unique().tolist(), 
        start_date=start_date, 
        end_date=end_date
    )

    # Merge periodic returns with asset information
    results = periodic_returns.merge(
        asset_list[['Symbol', 'Name', 'Sector', 'Weight']], 
        left_index=True, 
        right_on='Symbol'
    )

    # Calculate weighted returns for each period
    for period in periods:
        results[f'{period} Rdt Weighted'] = results[f'{period} Return'] * results['Weight']

    # Group by sector and sum weighted returns for each period
    returns_sector = results.groupby('Sector')[
        [f'{period} Rdt Weighted' for period in periods]
    ].sum()

    return returns_sector
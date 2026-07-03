import dash
from dash import dcc, html, Input, Output, State, callback
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import numpy as np
import time


# Initialize the Dash app
app = dash.Dash(__name__, suppress_callback_exceptions=True)

# Define colors for different score ranges
def get_color(score):
    if score > 2:
        return '#ef4444'  # More cyclical (red)
    elif score > 0:
        return '#f97316'  # Moderately cyclical (orange)
    elif score > -2:
        return '#3b82f6'  # Moderately defensive (blue)
    else:
        return '#1d4ed8'  # More defensive (dark blue)

# Define colors for economy groups
economy_colors = {
    'BASIC MATERIALS': '#ef4444',
    'CONSUMER DURABLES': '#f97316',
    'ENERGY': '#fb923c',
    'INDUSTRIALS': '#fbbf24',
    'CONSUMER SERVICES': '#a3e635',
    'FINANCE': '#22d3ee',
    'TECHNOLOGY': '#60a5fa',
    'CONSUMER NON-DURABLES': '#818cf8',
    'UTILITIES': '#1d4ed8',
    'HEALTHCARE': '#7e22ce'
}



def load_data(filepath='screen_cyc_small.pkl'):
    print("Starting data loading...")
    start_time = time.time()
    
    df = pd.read_pickle(filepath)
    
    # Filter for rows with valid Cyclical_Score
    valid_data = df[df['Cyclical_Score'].notna() & df['FactSet Economy'].notna()]
    
    # Process FactSet Industry stats with NO minimum company filter initially
    # This ensures we capture ALL industries in the dataset
    industry_stats = valid_data.groupby(['FactSet Ind', 'FactSet Economy'])['Cyclical_Score'].agg([
        ('mean', 'mean'),
        ('median', 'median'),
        ('min', 'min'),
        ('max', 'max'),
        ('count', 'count'),
        ('q1', lambda x: x.quantile(0.25)),
        ('q3', lambda x: x.quantile(0.75))
    ]).reset_index()
    
    # Sort by industry name for easier lookup
    industry_stats = industry_stats.sort_values(['FactSet Economy', 'FactSet Ind'])
    
    # Extract all available dates from the data
    all_dates = sorted(df['Date'].unique().tolist())
    most_recent_date = max(all_dates) if all_dates else None
    
    # Get all company data
    all_companies_data = df.to_dict('records')
    
    # Process economy stats
    economy_stats = valid_data.groupby('FactSet Economy')['Cyclical_Score'].agg([
        ('mean', 'mean'),
        ('median', 'median'),
        ('min', 'min'),
        ('max', 'max'),
        ('count', 'count')
    ]).reset_index()
    
    # Add any other missing data components
    # Process component stats
    component_columns = [col for col in df.columns if col.startswith('Cyclical_Score_')]
    component_stats = []
    
    for col in component_columns:
        component_name = col.replace('Cyclical_Score_', '')
        data_subset = df[df[col].notna()]
        
        if len(data_subset) > 0:
            component_stats.append({
                'component': component_name,
                'minValue': data_subset[col].min(),
                'maxValue': data_subset[col].max(),
                'avgValue': data_subset[col].mean(),
                'avgAbsValue': data_subset[col].abs().mean(),
                'count': len(data_subset)
            })
    
    # Add correlations data
    correlations = []
    for col in component_columns:
        component_name = col.replace('Cyclical_Score_', '')
        corr_data = df[[col, 'Cyclical_Score']].dropna()
        
        if len(corr_data) > 0:
            correlation = corr_data[col].corr(corr_data['Cyclical_Score'])
            correlations.append({
                'component': component_name,
                'correlation': correlation
            })
    
    # Convert to format ready for the dashboard
    processed_data = {
        'industry_stats': industry_stats.to_dict('records'),
        'economy_stats': economy_stats.to_dict('records'),
        'all_companies_data': all_companies_data,
        'all_dates': all_dates,
        'most_recent_date': most_recent_date,
        'component_stats': component_stats,
        'correlations': correlations
    } 
    
    end_time = time.time()
    print(f"Data loading completed in {end_time - start_time:.2f} seconds!")
    print(f"Found {len(industry_stats)} unique industry/economy combinations")
    print(f"Found {len(all_dates)} unique dates")
    
    return processed_data


# Pre-load data before app layout is created
print("Pre-loading data for dashboard...")
preloaded_data = load_data()
print("Data pre-loading completed!")

# Update app.layout to include the new Methodology tab
app.layout = html.Div([
    html.H1("Cyclical Score Analysis Dashboard", className="text-2xl font-bold mb-4"),
    
    # Tabs for different views - add the new Methodology tab
    dcc.Tabs(id='tabs', value='companies-table', children=[
        dcc.Tab(label='Companies Table', value='companies-table'),
        dcc.Tab(label='Component Analysis', value='components'),
        dcc.Tab(label='Correlations', value='correlations'),
        dcc.Tab(label='FactSet Analysis', value='factset'),
        dcc.Tab(label='Company Evolution', value='company-evolution'),
        dcc.Tab(label='Methodology', value='methodology'),  # New tab
    ]),
    
    # Content div that will be updated based on the selected tab
    html.Div(id='tab-content'),
    
    # Store components to share data between callbacks
    dcc.Store(id='data-store', data=preloaded_data),  # Use pre-loaded data
    dcc.Store(id='factset-view', data='economy'),
    dcc.Store(id='selected-economy', data=None),
], className="p-4")

# Update the render_tab_content callback to include the new Methodology tab
@callback(
    Output('tab-content', 'children'),
    Input('tabs', 'value'),
    State('data-store', 'data')
)
def render_tab_content(tab, data):
    if tab == 'companies-table':
        return render_companies_table(data)
    elif tab == 'components':
        return render_component_analysis(data)
    elif tab == 'correlations':
        return render_correlations(data)
    elif tab == 'factset':
        return render_factset_analysis(data)
    elif tab == 'company-evolution':
        return render_company_evolution(data)
    elif tab == 'methodology':
        return render_methodology()  # New tab function
    
    return html.Div("Select a tab to view content")

# Function to render the company evolution tab
def render_company_evolution(data):
    # Get unique company names from the data
    all_companies_data = data['all_companies_data']
    company_df = pd.DataFrame(all_companies_data)
    
    # Extract unique company names and create a lookup dictionary for search
    unique_companies = sorted(company_df['Name'].dropna().unique())
    
    return html.Div([
        html.Div([
            html.H2("Company Cyclical Score Evolution", className="text-xl font-semibold mb-4"),
            html.P("Select a company to view how its cyclical score and components have evolved over time.", 
                   className="mb-4"),
            
            # Company selector with search capability
            html.Div([
                html.Label("Search and select company:", className="block font-medium mb-2"),
                dcc.Dropdown(
                    id='company-dropdown',
                    options=[{'label': name, 'value': name} for name in unique_companies],
                    placeholder="Type company name...",
                    className="w-full"
                )
            ], className="mb-6"),
            
            # Placeholder for company details
            html.Div(id='company-details', className="mb-6"),
            
            # Charts area (will be filled by callback)
            html.Div(id='company-charts', className="mt-4 grid grid-cols-1 gap-6"),
            
        ], className="p-4 bg-white rounded shadow")
    ])


# Function to generate companies table with both component scores and raw data
def generate_companies_table(companies_data, selected_date):
    # Filter companies by the selected date
    filtered_companies = [company for company in companies_data 
                         if company.get('Date') == selected_date]
    
    # Sort by Weight in STOXX EUROPE 600 (descending)
    filtered_companies = sorted(
        filtered_companies, 
        key=lambda x: x.get('Weight in STOXX EUROPE 600', 0) if x.get('Weight in STOXX EUROPE 600') is not None else 0, 
        reverse=True
    )[:50]  # Limit to top 50
    
    if not filtered_companies:
        return html.Div("No data available for the selected date.")
    
    # Extract component columns and raw data columns
    component_cols = [
        'Cyclical_Score_Sector_Score',
        'Cyclical_Score_Oper_Margin',
        'Cyclical_Score_Sales',
        'Cyclical_Score_Fcf_Ebitda',
        'Cyclical_Score_Dividend_Consistency',
        'Cyclical_Score_Dividend_Volatility',
        'Cyclical_Score_Beta',
        'Cyclical_Score_Market_Stress_Zscore',
        'Cyclical_Score_Hurst',
        'Cyclical_Score_Pmi_Opermargin'
    ]
    
    raw_data_cols = [
        'Cyclical_Score_vol_sales',
        'Cyclical_Score_vol_oper_margin',
        'Cyclical_Score_fcf_ebitda_ratio',
        'Cyclical_Score_paid_dividend',
        'Cyclical_Score_div_vol',
        'Cyclical_Score_Beta vs SXXP (Rolling ewma 250D)',
        'Cyclical_Score_hurst',
        'Cyclical_Score_market_stress_relative_return',
        'Cyclical_Score_beta_pmi_opermargin'
    ]
    
    # Filter out columns that don't exist in the data
    component_cols = [col for col in component_cols if col in filtered_companies[0].keys()]
    raw_data_cols = [col for col in raw_data_cols if col in filtered_companies[0].keys()]
    
    # Create table header for basic info
    header = [
        html.Th("Rank", className="px-2 py-2 border text-left"),
        html.Th("Company", className="px-2 py-2 border text-left"),
        html.Th("Economy", className="px-2 py-2 border text-left"),
        html.Th("Industry", className="px-2 py-2 border text-left"),
        html.Th("Weight (%)", className="px-2 py-2 border text-right"),
        html.Th("Cyclical Score", className="px-2 py-2 border text-right")
    ]
    
    # Add component score columns to header
    for col in component_cols:
        display_name = col.replace('Cyclical_Score_', '')
        header.append(html.Th(display_name, className="px-2 py-2 border text-right"))
    
    # Create table rows
    rows = []
    for i, company in enumerate(filtered_companies):
        cyclical_score = company.get('Cyclical_Score')
        score_color = get_color(cyclical_score) if cyclical_score is not None else '#f3f4f6'
        
        row_cells = [
            html.Td(str(i+1), className="px-2 py-1 border text-sm"),
            html.Td(company.get('Name', ''), className="px-2 py-1 border text-sm font-medium"),
            html.Td(company.get('FactSet Economy', ''), className="px-2 py-1 border text-sm"),
            html.Td(company.get('FactSet Ind', ''), className="px-2 py-1 border text-sm"),
            html.Td(f"{company.get('Weight in STOXX EUROPE 600', 0):.2f}%", 
                className="px-2 py-1 border text-sm text-right"),
            html.Td(f"{cyclical_score:.2f}" if cyclical_score is not None else "N/A", 
                   className="px-2 py-1 border text-sm text-right font-semibold",
                   style={"backgroundColor": score_color, 
                         "color": "white" if cyclical_score and abs(cyclical_score) > 2 else "black"})
        ]
        
        # Add component score cells
        for col in component_cols:
            value = company.get(col)
            score_color = get_color(value) if value is not None else '#f3f4f6'
            row_cells.append(
                html.Td(f"{value:.2f}" if value is not None else "", 
                       className="px-2 py-1 border text-sm text-right",
                       style={"backgroundColor": score_color, 
                             "color": "white" if value and abs(value) > 1.8 else "black"})
            )
        
        rows.append(html.Tr(row_cells, className="hover:bg-gray-50"))
    
    # Create raw data table header
    raw_header = [
        html.Th("Company", className="px-2 py-2 border text-left"),
    ]
    
    # Add raw data columns to header
    for col in raw_data_cols:
        display_name = col.replace('Cyclical_Score_', '')
        raw_header.append(html.Th(display_name, className="px-2 py-2 border text-right"))
    
    # Create raw data table rows
    raw_rows = []
    for i, company in enumerate(filtered_companies):
        raw_row_cells = [
            html.Td(company.get('Name', ''), className="px-2 py-1 border text-sm font-medium"),
        ]
        
        # Add raw data cells
        for col in raw_data_cols:
            value = company.get(col)
            raw_row_cells.append(
                html.Td(f"{value:.4f}" if value is not None else "", 
                       className="px-2 py-1 border text-sm text-right")
            )
        
        raw_rows.append(html.Tr(raw_row_cells, className="hover:bg-gray-50"))
    
    # Return both tables
    return html.Div([
        html.H3("Cyclical Score Components", className="text-lg font-semibold my-2"),
        html.Div([
            html.Table([
                html.Thead(html.Tr(header, className="bg-gray-50")),
                html.Tbody(rows, className="divide-y divide-gray-200")
            ], className="min-w-full bg-white border border-gray-200")
        ], className="overflow-x-auto mb-6"),
        
        html.H3("Raw Data Inputs", className="text-lg font-semibold my-2"),
        html.Div([
            html.Table([
                html.Thead(html.Tr(raw_header, className="bg-gray-50")),
                html.Tbody(raw_rows, className="divide-y divide-gray-200")
            ], className="min-w-full bg-white border border-gray-200")
        ], className="overflow-x-auto")
    ])



# Function to render the methodology tab with improved formatting
def render_methodology():
    return html.Div([
        html.H2("Cyclical Score Methodology", className="text-2xl font-bold mb-6 text-center text-blue-800"),
        
        # Formula Overview with LaTeX-style formatting
        html.Div([
            html.H3("Formula Overview", className="text-xl font-semibold mb-4 border-b pb-2 text-blue-700"),
            
            # Mathematical formula presentation
            html.Div([
                html.P([
                    "Cyclical Score = Sector Score + ", 
                    html.Span("0.4", className="text-orange-500 font-bold"), 
                    " × (Oper Margin + Sales + Fcf Ebitda + Dividend Consistency + Dividend Volatility) + ",
                    html.Span("0.5", className="text-green-600 font-bold"), 
                    " × (Beta + Market Stress Zscore + Hurst) + ",
                    html.Span("0.1", className="text-purple-600 font-bold"), 
                    " × (Pmi Opermargin)"
                ], className="text-lg font-medium leading-relaxed tracking-wide text-center p-4 bg-gray-50 rounded-lg")
            ], className="mb-6"),
            
            # Explanation of what positive/negative scores mean
            html.Div([
                html.P([
                    html.Strong("Interpretation: "), 
                    "The Cyclical Score indicates a company's sensitivity to economic cycles."
                ], className="mb-2 text-gray-800"),
                
                html.Div([
                    html.Div([
                        html.Div(className="w-4 h-4 rounded-full inline-block mr-2 bg-red-600"),
                        html.Span("Score > 2: Strongly cyclical - High sensitivity to economic cycles", className="font-semibold"),
                    ], className="flex items-center mb-2"),
                    html.Div([
                        html.Div(className="w-4 h-4 rounded-full inline-block mr-2 bg-orange-500"),
                        html.Span("Score 0 to 2: Moderately cyclical - Some sensitivity to economic cycles", className="font-semibold"),
                    ], className="flex items-center mb-2"),
                    html.Div([
                        html.Div(className="w-4 h-4 rounded-full inline-block mr-2 bg-blue-500"),
                        html.Span("Score -2 to 0: Moderately defensive - Limited sensitivity to economic cycles", className="font-semibold"),
                    ], className="flex items-center mb-2"),
                    html.Div([
                        html.Div(className="w-4 h-4 rounded-full inline-block mr-2 bg-blue-800"),
                        html.Span("Score < -2: Strongly defensive - Minimal sensitivity to economic cycles", className="font-semibold"),
                    ], className="flex items-center mb-2"),
                ], className="mb-4 pl-4")
            ], className="mb-4")
        ], className="mb-8 p-6 bg-white rounded-lg shadow-md"),
        
        # Component 1: Sector Score
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="1"),
            html.H3("Sector Score", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 1.0"),
            
            html.P("Industry classification based on cyclical characteristics.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Predefined mapping of industries to cyclical scores based on historical sensitivity to economic cycles.", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Categories:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("+2 (Cyclical):", className="font-semibold text-gray-800"),
                    ], className="flex items-center mb-1"),
                    html.P("Auto & Parts, Basic Resources, Chemicals, Construction, Industrial Goods & Services, Energy, Travel & Leisure", 
                           className="ml-8 mb-2 text-gray-600"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-orange-400"),
                        html.Span("+1 (Slightly Cyclical):", className="font-semibold text-gray-800"),
                    ], className="flex items-center mb-1"),
                    html.P("Banks, Financial Services, Real Estate, Personal & Household Goods", 
                           className="ml-8 mb-2 text-gray-600"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("0 (Neutral):", className="font-semibold text-gray-800"),
                    ], className="flex items-center mb-1"),
                    html.P("Media, Insurance, Retail, Technology, Telecommunications", 
                           className="ml-8 mb-2 text-gray-600"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("-2 (Defensive):", className="font-semibold text-gray-800"),
                    ], className="flex items-center mb-1"),
                    html.P("Food, Beverage & Tobacco, Health Care, Utilities", 
                           className="ml-8 mb-2 text-gray-600"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 2: Sales Volatility
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="2"),
            html.H3("Sales Volatility", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.5"),
            
            html.P("Measures the consistency or volatility of company sales over time.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Coefficient of variation (CV) of sales, calculated as standard deviation divided by mean.", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("CV < 0.15:", className="font-semibold text-gray-800"),
                        html.Span(" -2 (Defensive - stable sales)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("CV between 0.15 and 0.3:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("CV > 0.3:", className="font-semibold text-gray-800"),
                        html.Span(" +2 (Cyclical - volatile sales)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 3: Operating Margin Volatility
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="3"),
            html.H3("Operating Margin Volatility", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.5"),
            
            html.P("Measures the stability of a company's profitability through business cycles.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Coefficient of variation of operating margins over time (standard deviation divided by mean).", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("CV < 0.15:", className="font-semibold text-gray-800"),
                        html.Span(" -2 (Defensive - stable margins)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("CV between 0.15 and 0.3:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("CV > 0.3:", className="font-semibold text-gray-800"),
                        html.Span(" +2 (Cyclical - volatile margins)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 4: FCF/EBITDA Ratio
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="4"),
            html.H3("FCF/EBITDA Ratio", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.5"),
            
            html.P("Measures the company's ability to convert earnings into free cash flow.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Ratio of Free Cash Flow to EBITDA (Earnings Before Interest, Taxes, Depreciation, and Amortization).", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("Ratio ≥ 0.8:", className="font-semibold text-gray-800"),
                        html.Span(" -1 (Defensive - high cash conversion)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("Ratio between 0.3 and 0.8:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("Ratio < 0.3:", className="font-semibold text-gray-800"),
                        html.Span(" +1.5 (Cyclical - low cash conversion)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 5: Dividend Volatility
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="5"),
            html.H3("Dividend Volatility", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.5"),
            
            html.P("Measures the consistency of dividend payments over time.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Coefficient of variation of dividend yields over a 5-year lookback period.", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("CV < 0.2:", className="font-semibold text-gray-800"),
                        html.Span(" -1 (Defensive - stable dividends)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("CV between 0.2 and 0.4:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("CV > 0.4:", className="font-semibold text-gray-800"),
                        html.Span(" +1.5 (Cyclical - volatile dividends)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 6: Beta
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="6"),
            html.H3("Beta", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.3"),
            
            html.P("Measures the volatility of a stock relative to the overall market.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Rolling Beta against STOXX EUROPE 600 index using exponentially weighted moving average over 250 days.", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("Beta > 1.2:", className="font-semibold text-gray-800"),
                        html.Span(" +2 (Strongly cyclical - more volatile than market)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("Beta between 0.8 and 1.2:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral - similar volatility to market)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("Beta < 0.8:", className="font-semibold text-gray-800"),
                        html.Span(" -2 (Strongly defensive - less volatile than market)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 7: Market Stress Test
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="7"),
            html.H3("Market Stress Test", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.3"),
            
            html.P("Evaluates how a stock performs during market downturns relative to the broader market.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P([
                    "1. Identify the worst 10% trading days in the market over the past 3 years",
                    html.Br(),
                    "2. Calculate the stock's average relative performance (excess return) on these days",
                    html.Br(),
                    "3. Standardize this as a Z-score"
                ], className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("Z-score > 0.8:", className="font-semibold text-gray-800"),
                        html.Span(" -3 (Strong defensive - performs well under market stress)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("Z-score between -0.5 and 0.8:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("Z-score < -0.5:", className="font-semibold text-gray-800"),
                        html.Span(" +2 (Strong cyclical - performs poorly under market stress)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 8: Hurst Exponent
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="8"),
            html.H3("Hurst Exponent", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.3"),
            
            html.P("Measures the long-term memory of the stock price time series, indicating whether a stock tends to trend or revert to its mean.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P("Compute the Hurst exponent for the stock price over the past 120 days. Values range from 0 to 1.", className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("Hurst > 0.65:", className="font-semibold text-gray-800"),
                        html.Span(" +1.5 (Cyclical momentum - trend persistence)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("Hurst between 0.5 and 0.65:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("Hurst < 0.5:", className="font-semibold text-gray-800"),
                        html.Span(" -1 (Defensive reversal - mean reversion)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Component 9: PMI-Operating Margin Relationship
        html.Div([
            html.Div(className="w-8 h-8 rounded-full bg-blue-700 text-white flex items-center justify-center font-bold text-xl absolute -ml-4 -mt-4 shadow-lg", children="9"),
            html.H3("PMI-Operating Margin Relationship", className="text-xl font-semibold mb-3 ml-6 text-blue-700"),
            html.Div(className="w-16 h-6 bg-blue-100 text-blue-800 rounded-full text-xs flex items-center justify-center font-bold mb-3", children="Weight: 0.2"),
            
            html.P("Measures how strongly a company's operating margins are influenced by changes in the Purchasing Managers' Index (PMI), a key economic indicator.", className="mb-3 text-gray-700"),
            
            html.Div([
                html.H4("Calculation Method:", className="font-semibold mb-1 text-gray-800"),
                html.P([
                    "Regression analysis between PMI index and the company's operating margin to determine coefficient (sensitivity)."
                ], className="mb-3 ml-4 text-gray-600"),
                
                html.H4("Scoring Thresholds:", className="font-semibold mb-1 text-gray-800"),
                html.Div([
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-red-500"),
                        html.Span("Coefficient > 0.5:", className="font-semibold text-gray-800"),
                        html.Span(" +3 (Cyclical - strong positive relationship with economic cycles)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-gray-400"),
                        html.Span("Coefficient between 0.2 and 0.5:", className="font-semibold text-gray-800"),
                        html.Span(" 0 (Neutral)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                    
                    html.Div([
                        html.Div(className="w-3 h-3 rounded-full inline-block mr-2 bg-blue-600"),
                        html.Span("Coefficient < 0.2:", className="font-semibold text-gray-800"),
                        html.Span(" -2.5 (Defensive - weak relationship with economic cycles)", className="ml-2 text-gray-600"),
                    ], className="flex items-center mb-2"),
                ], className="ml-4")
            ], className="mb-3"),
        ], className="mb-8 p-6 pt-8 bg-white rounded-lg shadow-md relative"),
        
        # Reference and Interpretation Notes
        html.Div([
            html.H3("Notes on Interpretation", className="text-xl font-semibold mb-4 border-b pb-2 text-blue-700"),
            html.P([
                "The Cyclical Score aggregates multiple factors to provide a comprehensive view of a company's sensitivity to economic cycles. ",
                "Companies with higher scores tend to outperform during economic expansions but may underperform during contractions. ",
                "Conversely, companies with lower (negative) scores tend to demonstrate more stable performance across different economic environments."
            ], className="mb-4 text-gray-700"),
            
            html.P([
                html.Strong("Key insights:"), 
                html.Ul([
                    html.Li("Industry classification provides the foundation, but individual company metrics can lead to significant variation within sectors", className="ml-4 mb-2"),
                    html.Li("Financial stability metrics (margins, cash flow conversion) provide insight into operational resilience during downturns", className="ml-4 mb-2"),
                    html.Li("Market behavior metrics (beta, stress testing) capture how investors perceive and trade the stock during different market conditions", className="ml-4 mb-2"),
                    html.Li("The PMI-margin relationship directly measures sensitivity to macroeconomic fluctuations", className="ml-4 mb-2"),
                ], className="mt-2")
            ], className="text-gray-700"),
        ], className="mb-8 p-6 bg-white rounded-lg shadow-md"),
        
    ], className="container mx-auto px-4 py-6 max-w-5xl")





def render_companies_table(data):
    # Check if required data exists
    if not data or 'all_companies_data' not in data:
        return html.Div("Error: Missing company data", className="p-4 bg-red-100 text-red-700 rounded")
    
    # Get dates with fallback for missing keys
    all_dates = data.get('all_dates', [])
    most_recent_date = data.get('most_recent_date', None)
    
    if not all_dates and 'all_companies_data' in data:
        # Try to extract dates from company data if all_dates is missing
        company_dates = set()
        for company in data['all_companies_data']:
            if 'Date' in company:
                company_dates.add(company['Date'])
        all_dates = sorted(list(company_dates))
        most_recent_date = max(all_dates) if all_dates else None
    
    # If we still don't have dates, show error
    if not all_dates:
        return html.Div([
            html.H3("Error: No Date Information Available", className="text-red-600"),
            html.P("Cannot find any dates in the data. Please check your data file.")
        ], className="p-4 bg-red-100 rounded-lg")
    
    # Date selector
    date_selector = html.Div([
        html.Label("Select Date:", className="mr-2 font-medium"),
        dcc.Dropdown(
            id='date-dropdown',
            options=[{'label': date, 'value': date} for date in all_dates],
            value=most_recent_date,  # Default to most recent date
            className="w-64"
        )
    ], className="mb-4")
    
    # Companies table content (will be populated by callback)
    companies_table = html.Div(id='companies-table-content')
    
    return html.Div([
        date_selector,
        companies_table
    ])

# Update the render_factset_analysis function to handle missing data:




# Callback to update companies table when date changes
@callback(
    Output('companies-table-content', 'children'),
    [Input('date-dropdown', 'value')],
    [State('data-store', 'data')]
)
def update_companies_table(selected_date, data):
    if not selected_date or not data:
        return html.Div("No date selected or data not loaded.")
    
    all_companies_data = data['all_companies_data']
    return generate_companies_table(all_companies_data, selected_date)

# Render component analysis tab with the specific formula variables
def render_component_analysis(data):
    # Check if component_stats exists in the data
    if 'component_stats' not in data or not data['component_stats']:
        return html.Div("No component statistics data available.", className="p-4 bg-red-100 border border-red-300 rounded")
    
    # Define the specific variables to include
    formula_variables = [
        'Sector_Score',
        'Oper_Margin',
        'Sales',
        'Fcf_Ebitda',
        'Dividend_Consistency',
        'Dividend_Volatility',
        'Beta',
        'Market_Stress_Zscore',
        'Hurst',
        'Pmi_Opermargin'
    ]
    
    # Convert component_stats to DataFrame if it's a list of dicts
    try:
        if isinstance(data['component_stats'], list):
            component_stats_df = pd.DataFrame(data['component_stats'])
        else:
            component_stats_df = pd.DataFrame.from_records(data['component_stats'])
            
        # Filter to only include our specified formula variables
        component_stats_df = component_stats_df[component_stats_df['component'].isin(formula_variables)]
        
        # If we don't have any matching variables, show an error
        if len(component_stats_df) == 0:
            return html.Div([
                html.H3("Missing Formula Variables", className="text-red-600"),
                html.P("None of the required formula variables were found in the component data."),
                html.P("Required variables: " + ", ".join(formula_variables))
            ], className="p-4 bg-red-100 border border-red-300 rounded")
            
    except Exception as e:
        # Catch any errors in the data processing
        return html.Div([
            html.H3("Error Processing Component Data", className="text-red-600"),
            html.P(f"Error: {str(e)}"),
            html.P("Component data structure may be incompatible.")
        ], className="p-4 bg-red-100 border border-red-300 rounded")
    
    try:
        # Create bar chart for component contribution
        contribution_fig = px.bar(
            component_stats_df,
            y='component',
            x='avgAbsValue',
            orientation='h',
            labels={'avgAbsValue': 'Avg. Absolute Value', 'component': 'Component'},
            title='Component Contribution to Cyclical Score',
            height=500
        )
        contribution_fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            margin=dict(l=200)
        )
        
        # Create range chart for component values
        range_data = []
        for _, comp in component_stats_df.iterrows():
            range_data.append({
                'component': comp['component'],
                'value': comp['minValue'],
                'type': 'Min Value'
            })
            range_data.append({
                'component': comp['component'],
                'value': comp['avgValue'],
                'type': 'Avg Value'
            })
            range_data.append({
                'component': comp['component'],
                'value': comp['maxValue'],
                'type': 'Max Value'
            })
        
        range_df = pd.DataFrame(range_data)
        
        range_fig = px.bar(
            range_df,
            y='component',
            x='value',
            color='type',
            orientation='h',
            barmode='group',
            labels={'value': 'Value', 'component': 'Component', 'type': 'Statistic'},
            title='Component Value Range',
            color_discrete_map={
                'Min Value': '#60a5fa',
                'Avg Value': '#3b82f6',
                'Max Value': '#1d4ed8'
            },
            height=500
        )
        range_fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            margin=dict(l=200)
        )
        
        # Create a bar chart showing the weights in the formula
        weights_data = [
            {'component': 'Sector_Score', 'weight': 1.0, 'group': 'Weight = 1.0'},
            {'component': 'Oper_Margin', 'weight': 0.4, 'group': 'Weight = 0.4'},
            {'component': 'Sales', 'weight': 0.4, 'group': 'Weight = 0.4'},
            {'component': 'Fcf_Ebitda', 'weight': 0.4, 'group': 'Weight = 0.4'},
            {'component': 'Dividend_Consistency', 'weight': 0.4, 'group': 'Weight = 0.4'},
            {'component': 'Dividend_Volatility', 'weight': 0.4, 'group': 'Weight = 0.4'},
            {'component': 'Beta', 'weight': 0.5, 'group': 'Weight = 0.5'},
            {'component': 'Market_Stress_Zscore', 'weight': 0.5, 'group': 'Weight = 0.5'},
            {'component': 'Hurst', 'weight': 0.5, 'group': 'Weight = 0.5'},
            {'component': 'Pmi_Opermargin', 'weight': 0.1, 'group': 'Weight = 0.1'}
        ]
        weights_df = pd.DataFrame(weights_data)
        
        weights_fig = px.bar(
            weights_df,
            y='component',
            x='weight',
            orientation='h',
            color='group',
            labels={'weight': 'Weight in Formula', 'component': 'Component'},
            title='Component Weights in Cyclical Score Formula',
            height=500
        )
        weights_fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            margin=dict(l=200)
        )
        
        # Calculate weighted contribution
        weighted_data = []
        for _, comp in component_stats_df.iterrows():
            weight = 1.0  # Default weight
            component_name = comp['component']
            
            # Assign weights based on the formula
            if component_name in ['Oper_Margin', 'Sales', 'Fcf_Ebitda', 'Dividend_Consistency', 'Dividend_Volatility']:
                weight = 0.4
            elif component_name in ['Beta', 'Market_Stress_Zscore', 'Hurst']:
                weight = 0.5
            elif component_name == 'Pmi_Opermargin':
                weight = 0.1
                
            weighted_data.append({
                'component': component_name,
                'weighted_contribution': comp['avgAbsValue'] * weight
            })
            
        weighted_df = pd.DataFrame(weighted_data)
        
        weighted_fig = px.bar(
            weighted_df,
            y='component',
            x='weighted_contribution',
            orientation='h',
            labels={'weighted_contribution': 'Weighted Contribution', 'component': 'Component'},
            title='Weighted Component Contribution to Cyclical Score',
            height=500
        )
        weighted_fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            margin=dict(l=200)
        )
        
        
        return html.Div([            
            html.Div([
                html.H2("Component Weights in Formula", className="text-xl font-semibold mb-4"),
                html.P("The weights applied to each component in the Cyclical Score calculation.", className="mb-4"),
                dcc.Graph(figure=weights_fig)
            ], className="mb-8"),
            
            html.Div([
                html.H2("Weighted Component Contribution", className="text-xl font-semibold mb-4"),
                html.P("Average absolute contribution of each component after applying formula weights.", className="mb-4"),
                dcc.Graph(figure=weighted_fig)
            ], className="mb-8"),
            
            html.Div([
                html.H2("Raw Component Contribution", className="text-xl font-semibold mb-4"),
                html.P("Average absolute contribution of each component before applying weights.", className="mb-4"),
                dcc.Graph(figure=contribution_fig)
            ], className="mb-8"),
            
            html.Div([
                html.H2("Component Value Range", className="text-xl font-semibold mb-4"),
                html.P("Minimum, average, and maximum values for each component.", className="mb-4"),
                dcc.Graph(figure=range_fig)
            ], className="mb-8"),
        ], className="grid grid-cols-1 gap-8")
        
    except Exception as e:
        # Catch any errors in chart creation
        return html.Div([
            html.H3("Error Creating Component Charts", className="text-red-600"),
            html.P(f"Error: {str(e)}"),
            html.P("This may be due to unexpected data format or missing values.")
        ], className="p-4 bg-red-100 border border-red-300 rounded")


# Render correlations tab with labels directly on the graph - fixed to handle None values
def render_correlations(data):
    correlations = data['correlations']
    
    # Create a new figure with go (Graph Objects) for more control
    fig = go.Figure()
    
    # Extract data and handle None values
    components = []
    corr_values = []
    
    for comp in correlations:
        if comp['component'] is not None and comp['correlation'] is not None:
            components.append(comp['component'])
            corr_values.append(comp['correlation'])
    
    # Handle empty data case
    if not components:
        return html.Div([
            html.H3("No Valid Correlation Data", className="text-red-600"),
            html.P("The correlation data contains no valid values to display.")
        ], className="p-4 bg-red-100 border border-red-300 rounded")
    
    # Create colors based on correlation sign, safely handling None
    colors = ['#3b82f6' if c is not None and c >= 0 else '#f87171' for c in corr_values]
    
    # Add horizontal bar trace
    fig.add_trace(go.Bar(
        x=corr_values,
        y=components,
        orientation='h',
        marker_color=colors,
        text=components,  # This will be used for hover information
        hovertemplate='<b>%{text}</b><br>Correlation: %{x:.3f}<extra></extra>'
    ))
    
    # Add component name annotations directly on the plot
    for i, (component, value) in enumerate(zip(components, corr_values)):
        # Handle None values for positioning logic
        if value is None:
            continue
            
        # Position text at either the left or right end of the bar
        x_pos = -0.02 if value >= 0 else 0.02
        alignment = 'right' if value >= 0 else 'left'
        
        fig.add_annotation(
            x=x_pos,
            y=i,
            text=component,
            showarrow=False,
            xanchor=alignment,
            yanchor='middle',
            font=dict(size=12),
            xshift=-5 if value >= 0 else 5
        )
    
    # Update layout
    fig.update_layout(
        title='Component Correlation with Cyclical Score',
        xaxis=dict(
            title='Correlation',
            range=[-1.1, 1],  # Extend left side to make room for labels
            zeroline=True,
            zerolinewidth=1,
            zerolinecolor='black',
            gridwidth=1,
            showgrid=True
        ),
        yaxis=dict(
            title='',
            showticklabels=False,  # Hide the original y-axis labels
            showgrid=True
        ),
        height=max(500, len(components) * 30),  # Dynamic height based on number of items
        margin=dict(l=30, r=50, t=80, b=50),  # Reduced left margin since we have direct labels
        plot_bgcolor='white'
    )
    
    # Add a horizontal line at zero for better visual reference
    fig.add_shape(
        type="line",
        x0=0, x1=0, y0=-0.5, y1=len(correlations)-0.5,
        line=dict(color="black", width=1, dash="dot")
    )
    
    return html.Div([
        html.H2("Component Correlation with Cyclical Score", className="text-xl font-semibold mb-4"),
        html.P("How strongly each component correlates with the overall Cyclical Score.", className="mb-4"),
        
        # Main correlation chart
        html.Div([
            dcc.Graph(figure=fig)
        ], className="border rounded p-2 bg-white"),
        
        # Key insights section
        html.Div([
            html.H3("Key Insights:", className="text-lg font-semibold mb-2"),
            html.Ul([
                html.Li([
                    html.Strong("Sector Score"), 
                    " has the strongest correlation (0.90) with the overall Cyclical Score, making it the most influential component."
                ]),
                html.Li([
                    html.Strong("Operating Margin"), 
                    " (0.40) and ", 
                    html.Strong("Beta"), 
                    " (0.39) are the next most important contributors, showing moderate correlations."
                ]),
                html.Li([
                    html.Strong("Market Stress Z-Score"), 
                    " (0.31) and ", 
                    html.Strong("Dividend Volatility"), 
                    " (0.21) also show meaningful correlations."
                ]),
                html.Li([
                    "Some components like ", 
                    html.Strong("Dividend Consistency"), 
                    " (-0.02) and ", 
                    html.Strong("Beta PMI Op Margin"), 
                    " (-0.02) show very weak correlations, suggesting they have minimal impact on the overall score."
                ]),
                html.Li([
                    html.Strong("Hurst"), 
                    " shows a negative correlation (-0.18), meaning higher Hurst values tend to correspond with lower cyclical scores (more defensive)."
                ]),
            ], className="list-disc ml-5 space-y-2")
        ], className="mt-8 p-4 bg-gray-50 rounded-lg")
    ], className="grid grid-cols-1 gap-6")


def render_factset_analysis(data):
    # Check for required data keys
    economy_stats = data.get('economy_stats', [])
    industry_stats = data.get('industry_stats', [])
    all_dates = data.get('all_dates', [])
    
    # Handle missing data
    if not economy_stats or not industry_stats:
        return html.Div([
            html.H3("Error: Missing FactSet Data", className="text-red-600"),
            html.P("Cannot find economy or industry statistics in the data. Please check your data file.")
        ], className="p-4 bg-red-100 rounded-lg")
    
    # Get date range for display
    if all_dates and len(all_dates) > 0:
        start_date = min(all_dates) if isinstance(all_dates, list) else "Unknown"
        end_date = max(all_dates) if isinstance(all_dates, list) else "Unknown"
        date_range_text = f"Data aggregated across all dates ({start_date} to {end_date})"
    else:
        date_range_text = "Date range unknown"
    
    # Create FactSet view selector buttons
    factset_buttons = html.Div([
        html.Button("FactSet Economy", id="economy-button", className="px-4 py-2 rounded bg-blue-500 text-white mr-4"),
        html.Button("FactSet Industry", id="industry-button", className="px-4 py-2 rounded bg-gray-200"),
    ], className="flex space-x-4 mb-4")
    
    # Date range display
    date_display = html.Div([
        html.P(date_range_text, className="text-sm text-gray-600 italic mb-4")
    ])
    
    # Create economy view
    economy_view = html.Div([
        html.Div([
            html.H2("FactSet Economies Ranked by Cyclical Score", className="text-xl font-semibold mb-2"),
            html.P("Higher scores indicate more cyclical sectors, while lower (negative) scores indicate more defensive sectors.", className="mb-4"),
            date_display,
            
            # Create bar chart for economy scores
            dcc.Graph(
                figure=px.bar(
                    economy_stats,
                    y='FactSet Economy',
                    x='mean',
                    orientation='h',
                    labels={'mean': 'Cyclical Score', 'FactSet Economy': 'Economy'},
                    height=500,
                    color='mean',
                    color_continuous_scale=['#1d4ed8', '#3b82f6', '#f97316', '#ef4444'],
                    range_color=[-3, 4]
                ).update_layout(yaxis={'categoryorder': 'total ascending'})
            )
        ], className="mb-8"),
        
        html.Div([
            html.H2("Score Range by FactSet Economy", className="text-xl font-semibold mb-2"),
            html.P("Shows the minimum, quartiles, and maximum scores for each economy category.", className="mb-4"),
            
            # Create box plot for economy score ranges - with error handling
            dcc.Graph(
                figure=px.box(
                    industry_stats,
                    y='FactSet Economy',
                    x='mean',
                    orientation='h',
                    labels={'mean': 'Cyclical Score', 'FactSet Economy': 'Economy'},
                    height=500,
                    color='FactSet Economy',
                    color_discrete_map=economy_colors if 'economy_colors' in globals() else None
                ).update_layout(
                    yaxis={'categoryorder': 'total ascending'},
                    xaxis={'range': [-7, 7]}
                )
            )
        ], className="mb-8"),
    ], id="economy-view")
    
    # Create industry view with aggregated data
    industry_view = html.Div([
        html.Div([
            html.H2("FactSet Industries by Cyclical Score", className="text-xl font-semibold mb-2"),
            date_display,
            
            # Min companies filter
            html.Div([
                html.Label("Minimum companies per industry:", className="mr-2 font-medium"),
                dcc.Slider(
                    id='min-companies-slider',
                    min=1,
                    max=10,
                    step=1,
                    value=1,  # Default to 1 instead of 5 to show more industries
                    marks={1: '1', 5: '5', 10: '10'},
                    className="w-64"
                )
            ], className="mb-4"),
            
            # Economy filter dropdown - with error handling
            html.Div([
                html.Label("Filter by FactSet Economy:", className="mr-2 font-medium"),
                dcc.Dropdown(
                    id='economy-dropdown',
                    options=[{'label': economy, 'value': economy} 
                            for economy in sorted(set(item.get('FactSet Economy', '') for item in industry_stats if 'FactSet Economy' in item))],
                    placeholder="All Economies"
                )
            ], className="mb-4"),
            
            # Industry bar chart (will be updated by callback)
            html.Div(id='industry-chart', className="h-96 overflow-y-auto mb-4"),
            
            # Top 10 industries tables
            html.Div([
                html.Div([
                    html.H3("Top 10 Most Cyclical Industries", className="text-lg font-semibold mb-2"),
                    html.Div(id='cyclical-industries-table')
                ], className=""),
                
                html.Div([
                    html.H3("Top 10 Most Defensive Industries", className="text-lg font-semibold mb-2"),
                    html.Div(id='defensive-industries-table')
                ], className=""),
            ], className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-8"),
        ]),
    ], id="industry-view", style={'display': 'none'})
    
    # Check if we have enough data to create a summary
    # Calculate top economies dynamically
    try:
        economy_df = pd.DataFrame(economy_stats)
        top_cyclical_economies = economy_df.sort_values('mean', ascending=False).head(3)['FactSet Economy'].tolist()
        top_cyclical_scores = economy_df.sort_values('mean', ascending=False).head(3)['mean'].tolist()
        
        top_defensive_economies = economy_df.sort_values('mean').head(3)['FactSet Economy'].tolist()
        top_defensive_scores = economy_df.sort_values('mean').head(3)['mean'].tolist()
        
        # Calculate top industries dynamically
        industry_df = pd.DataFrame(industry_stats)
        top_cyclical_industries = industry_df.sort_values('mean', ascending=False).head(3)['FactSet Ind'].tolist()
        top_cyclical_ind_scores = industry_df.sort_values('mean', ascending=False).head(3)['mean'].tolist()
        
        top_defensive_industries = industry_df.sort_values('mean').head(3)['FactSet Ind'].tolist()
        top_defensive_ind_scores = industry_df.sort_values('mean').head(3)['mean'].tolist()
        
        # Create dynamic summary text
        summary_content = [
            html.Li([
                html.Strong("Most cyclical economies:"), 
                f" {top_cyclical_economies[0]} ({top_cyclical_scores[0]:.2f}), {top_cyclical_economies[1]} ({top_cyclical_scores[1]:.2f}), and {top_cyclical_economies[2]} ({top_cyclical_scores[2]:.2f}) have the highest cyclical scores."
            ]),
            html.Li([
                html.Strong("Most defensive economies:"), 
                f" {top_defensive_economies[0]} ({top_defensive_scores[0]:.2f}), {top_defensive_economies[1]} ({top_defensive_scores[1]:.2f}), and {top_defensive_economies[2]} ({top_defensive_scores[2]:.2f}) have the lowest cyclical scores."
            ]),
            html.Li([
                html.Strong("Most cyclical industries:"), 
                f" {top_cyclical_industries[0]} ({top_cyclical_ind_scores[0]:.2f}), {top_cyclical_industries[1]} ({top_cyclical_ind_scores[1]:.2f}), and {top_cyclical_industries[2]} ({top_cyclical_ind_scores[2]:.2f}) have the highest cyclical scores."
            ]),
            html.Li([
                html.Strong("Most defensive industries:"), 
                f" {top_defensive_industries[0]} ({top_defensive_ind_scores[0]:.2f}), {top_defensive_industries[1]} ({top_defensive_ind_scores[1]:.2f}), and {top_defensive_industries[2]} ({top_defensive_ind_scores[2]:.2f}) have the lowest cyclical scores."
            ]),
            html.Li([
                html.Strong("Top companies:"), 
                " The largest companies in STOXX EUROPE 600 show a mix of cyclical and defensive characteristics, with pharmaceutical companies being the most defensive and luxury goods and aerospace companies being more cyclical."
            ]),
        ]
    except Exception as e:
        # If there's an error calculating the summary, use generic text
        summary_content = [
            html.Li("Data summary could not be generated due to missing or invalid data."),
            html.Li(f"Error details: {str(e)}")
        ]
    
    # Analysis summary
    summary = html.Div([
        html.H2("Analysis Summary:", className="text-lg font-semibold mb-2"),
        html.Ol(summary_content, className="list-decimal ml-5 space-y-2")
    ], className="mt-8 p-4 bg-gray-100 rounded-lg")
    
    return html.Div([
        factset_buttons,
        economy_view,
        industry_view,
        summary
    ])



# Callbacks for FactSet tab interactions
@callback(
    [Output('economy-button', 'className'),
     Output('industry-button', 'className'),
     Output('economy-view', 'style'),
     Output('industry-view', 'style'),
     Output('factset-view', 'data')],
    [Input('economy-button', 'n_clicks'),
     Input('industry-button', 'n_clicks')],
    [State('factset-view', 'data')]
)
def toggle_factset_view(economy_clicks, industry_clicks, current_view):
    ctx = dash.callback_context
    if not ctx.triggered:
        # Default view
        return ("px-4 py-2 rounded bg-blue-500 text-white mr-4", 
                "px-4 py-2 rounded bg-gray-200", 
                {'display': 'block'}, 
                {'display': 'none'},
                'economy')
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    if button_id == 'economy-button':
        return ("px-4 py-2 rounded bg-blue-500 text-white mr-4", 
                "px-4 py-2 rounded bg-gray-200", 
                {'display': 'block'}, 
                {'display': 'none'},
                'economy')
    else:
        return ("px-4 py-2 rounded bg-gray-200", 
                "px-4 py-2 rounded bg-blue-500 text-white", 
                {'display': 'none'}, 
                {'display': 'block'},
                'industry')


# Improved callback for industry filter and chart - only showing existing industries
@callback(
    [Output('industry-chart', 'children'),
     Output('cyclical-industries-table', 'children'),
     Output('defensive-industries-table', 'children'),
     Output('selected-economy', 'data')],
    [Input('economy-dropdown', 'value'),
     Input('min-companies-slider', 'value')],
    [State('data-store', 'data')]
)
def update_industry_view(selected_economy, min_companies, data):
    industry_stats = data['industry_stats']
    
    # Convert to DataFrame for easier manipulation
    try:
        if isinstance(industry_stats, list):
            industry_df = pd.DataFrame(industry_stats)
        else:
            industry_df = pd.DataFrame.from_records(industry_stats)
    except Exception as e:
        return html.Div(f"Error processing industry data: {str(e)}"), html.Div(), html.Div(), selected_economy
    
    # Apply minimum companies filter
    if min_companies > 1:
        industry_df = industry_df[industry_df['count'] >= min_companies]
    
    # Filter by selected economy if specified
    if selected_economy:
        filtered_stats = industry_df[industry_df['FactSet Economy'] == selected_economy]
    else:
        filtered_stats = industry_df
    
    # Get only industries that exist in the filtered data
    existing_industries = filtered_stats['FactSet Ind'].unique().tolist()
    
    # Check if we have any data after filtering
    if len(filtered_stats) == 0 or len(existing_industries) == 0:
        no_data_message = html.Div([
            html.H3("No Data Available", className="text-red-600 text-center my-4"),
            html.P([
                f"No industries match the current filter criteria. Found {len(industry_df)} total industries but 0 match filters.",
                html.Br(),
                "Try: ",
                html.Ul([
                    html.Li("Selecting a different FactSet Economy"),
                    html.Li("Reducing the minimum companies threshold"),
                    html.Li("Checking if data is available for all dates")
                ], className="list-disc ml-8 mt-2")
            ], className="text-center")
        ], className="p-4 bg-gray-100 rounded-lg")
        return no_data_message, html.Div(), html.Div(), selected_economy
    
    # Sort filtered stats by mean score for consistent ordering
    filtered_stats = filtered_stats.sort_values('mean')
    
    # Debug information about data
    debug_info = html.Div([
        html.P(f"Found {len(existing_industries)} industries with data after filtering", 
               className="text-xs text-gray-500 mb-2"),
    ])
    
    # Prepare the industry bar chart with only existing industries
    industry_fig = px.bar(
        filtered_stats,
        y='FactSet Ind',
        x='mean',
        orientation='h',
        labels={'mean': 'Cyclical Score', 'FactSet Ind': 'Industry'},
        height=max(500, len(existing_industries) * 30),
        color='FactSet Economy',
        color_discrete_map=economy_colors
    )
    
    # Set the y-axis to only show existing industries in the correct order
    industry_fig.update_layout(
        yaxis={
            'categoryorder': 'array',
            'categoryarray': filtered_stats['FactSet Ind'].tolist(),
            'tickmode': 'array',
            'tickvals': filtered_stats['FactSet Ind'].tolist(),
            'ticktext': filtered_stats['FactSet Ind'].tolist()
        },
        xaxis={'range': [-5, 5], 'title': 'Cyclical Score'},
        margin=dict(l=240, r=40, t=30, b=50)  # Increased left margin even more for industry names
    )
    
    # Prepare top 10 cyclical industries table - from the entire dataset
    cyclical_industries = industry_df.sort_values('mean', ascending=False).head(10)
    cyclical_table = html.Table([
        html.Thead(
            html.Tr([
                html.Th("Industry", className="p-2 border"),
                html.Th("Economy", className="p-2 border"),
                html.Th("Score", className="p-2 border text-right"),
                html.Th("Companies", className="p-2 border text-right")
            ], className="bg-gray-100")
        ),
        html.Tbody([
            html.Tr([
                html.Td(ind['FactSet Ind'], className="p-2 border"),
                html.Td(ind['FactSet Economy'], className="p-2 border"),
                html.Td(f"{ind['mean']:.2f}", className="p-2 border text-right"),
                html.Td(str(ind['count']), className="p-2 border text-right")
            ]) for _, ind in cyclical_industries.iterrows()
        ])
    ], className="min-w-full border")
    
    # Prepare top 10 defensive industries table - from the entire dataset
    defensive_industries = industry_df.sort_values('mean').head(10)
    defensive_table = html.Table([
        html.Thead(
            html.Tr([
                html.Th("Industry", className="p-2 border"),
                html.Th("Economy", className="p-2 border"),
                html.Th("Score", className="p-2 border text-right"),
                html.Th("Companies", className="p-2 border text-right")
            ], className="bg-gray-100")
        ),
        html.Tbody([
            html.Tr([
                html.Td(ind['FactSet Ind'], className="p-2 border"),
                html.Td(ind['FactSet Economy'], className="p-2 border"),
                html.Td(f"{ind['mean']:.2f}", className="p-2 border text-right"),
                html.Td(str(ind['count']), className="p-2 border text-right")
            ]) for _, ind in defensive_industries.iterrows()
        ])
    ], className="min-w-full border")
    
    return html.Div([debug_info, dcc.Graph(figure=industry_fig)]), cyclical_table, defensive_table, selected_economy



# Function to render the company evolution tab
def render_company_evolution(data):
    # Get unique company names from the data
    all_companies_data = data['all_companies_data']
    company_df = pd.DataFrame(all_companies_data)
    
    # Extract unique company names and create a lookup dictionary for search
    unique_companies = sorted(company_df['Name'].dropna().unique())
    
    return html.Div([
        html.Div([
            html.H2("Company Cyclical Score Evolution", className="text-xl font-semibold mb-4"),
            html.P("Select a company to view how its cyclical score and components have evolved over time.", 
                   className="mb-4"),
            
            # Company selector with search capability
            html.Div([
                html.Label("Search and select company:", className="block font-medium mb-2"),
                dcc.Dropdown(
                    id='company-dropdown',
                    options=[{'label': name, 'value': name} for name in unique_companies],
                    placeholder="Type company name...",
                    className="w-full"
                )
            ], className="mb-6"),
            
            # Placeholder for company details
            html.Div(id='company-details', className="mb-6"),
            
            # Charts area (will be filled by callback)
            html.Div(id='company-charts', className="mt-4 grid grid-cols-1 gap-6"),
            
        ], className="p-4 bg-white rounded shadow")
    ])

# Callback to update company details and charts with components and raw data
@callback(
    [Output('company-details', 'children'),
     Output('company-charts', 'children')],
    [Input('company-dropdown', 'value')],
    [State('data-store', 'data')]
)
def update_company_view(selected_company, data):
    if not selected_company or not data:
        return html.Div("Please select a company to view its details."), []
    
    # Convert to DataFrame for easier manipulation
    all_companies_data = pd.DataFrame(data['all_companies_data'])
    
    # Filter data for the selected company
    company_data = all_companies_data[all_companies_data['Name'] == selected_company].copy()
    
    # Sort by date
    company_data = company_data.sort_values('Date')
    
    if len(company_data) == 0:
        return html.Div("No data available for the selected company."), []
    
    # Get the most recent company details
    recent_data = company_data.iloc[-1]
    
    # Create company details card
    company_details = html.Div([
        html.H3(selected_company, className="text-xl font-bold mb-2"),
        html.Div([
            html.Div([
                html.P([
                    html.Span("Economy: ", className="font-semibold"),
                    html.Span(recent_data.get('FactSet Economy', 'N/A'))
                ], className="mb-1"),
                html.P([
                    html.Span("Industry: ", className="font-semibold"),
                    html.Span(recent_data.get('FactSet Ind', 'N/A'))
                ], className="mb-1"),
                html.P([
                    html.Span("Latest Cyclical Score: ", className="font-semibold"),
                    html.Span(f"{recent_data.get('Cyclical_Score', 'N/A'):.2f}" 
                             if not pd.isna(recent_data.get('Cyclical_Score')) else 'N/A')
                ], className="mb-1"),
            ], className=""),
            html.Div([
                html.P([
                    html.Span("Weight in STOXX EUROPE 600: ", className="font-semibold"),
                    html.Span(f"{recent_data.get('Weight in STOXX EUROPE 600', 0):.4f}%" 
                            if not pd.isna(recent_data.get('Weight in STOXX EUROPE 600')) else 'N/A')
                ], className="mb-1"),
                html.P([
                    html.Span("Data points available: ", className="font-semibold"),
                    html.Span(str(len(company_data)))
                ], className="mb-1"),
                html.P([
                    html.Span("Date range: ", className="font-semibold"),
                    html.Span(f"{company_data['Date'].min()} to {company_data['Date'].max()}")
                ], className="mb-1"),
            ], className=""),
        ], className="grid grid-cols-1 md:grid-cols-2 gap-4")
    ], className="p-4 bg-gray-50 rounded-lg")
    
    # Define the component columns and raw data columns
    component_cols = [
        'Cyclical_Score',
        'Cyclical_Score_Sector_Score',
        'Cyclical_Score_Oper_Margin',
        'Cyclical_Score_Sales',
        'Cyclical_Score_Fcf_Ebitda',
        'Cyclical_Score_Dividend_Consistency',
        'Cyclical_Score_Dividend_Volatility',
        'Cyclical_Score_Beta',
        'Cyclical_Score_Market_Stress_Zscore',
        'Cyclical_Score_Hurst',
        'Cyclical_Score_Pmi_Opermargin'
    ]
    
    raw_data_cols = [
        'Cyclical_Score_vol_sales',
        'Cyclical_Score_vol_oper_margin',
        'Cyclical_Score_fcf_ebitda_ratio',
        'Cyclical_Score_paid_dividend',
        'Cyclical_Score_div_vol',
        'Cyclical_Score_Beta vs SXXP (Rolling ewma 250D)',
        'Cyclical_Score_hurst',
        'Cyclical_Score_market_stress_relative_return',
        'Cyclical_Score_beta_pmi_opermargin'
    ]
    
    # Filter out columns that don't exist in the data
    component_cols = [col for col in component_cols if col in company_data.columns]
    raw_data_cols = [col for col in raw_data_cols if col in company_data.columns]
    
    # Create main evolution chart for cyclical score
    main_fig = go.Figure()
    
    # Add total Cyclical Score line
    if 'Cyclical_Score' in company_data.columns:
        main_fig.add_trace(go.Scatter(
            x=company_data['Date'],
            y=company_data['Cyclical_Score'],
            mode='lines+markers',
            name='Total Cyclical Score',
            line=dict(color='black', width=3)
        ))
    
    # Add component lines
    for col in [c for c in component_cols if c != 'Cyclical_Score']:
        display_name = col.replace('Cyclical_Score_', '')
        main_fig.add_trace(go.Scatter(
            x=company_data['Date'],
            y=company_data[col],
            mode='lines+markers',
            name=display_name,
            visible='legendonly'  # Only show when selected in legend
        ))
    
    main_fig.update_layout(
        title=f"{selected_company} - Cyclical Score Evolution",
        xaxis_title="Date",
        yaxis_title="Score",
        legend_title="Components",
        height=500,
        margin=dict(l=40, r=40, t=40, b=40),
        hovermode="x unified"
    )
    
    # Create individual component charts (2 columns)
    component_names = [col.replace('Cyclical_Score_', '') for col in component_cols if col != 'Cyclical_Score']
    rows = (len(component_names) + 1) // 2  # Ceiling division to determine number of rows
    
    component_fig = make_subplots(
        rows=rows, 
        cols=2,
        subplot_titles=component_names,
        shared_xaxes=True
    )
    
    # Add each component as a subplot
    for i, col in enumerate([c for c in component_cols if c != 'Cyclical_Score']):
        row = (i // 2) + 1
        col_idx = (i % 2) + 1
        display_name = col.replace('Cyclical_Score_', '')
        
        component_fig.add_trace(
            go.Scatter(
                x=company_data['Date'],
                y=company_data[col],
                mode='lines+markers',
                name=display_name,
                line=dict(color=px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)])
            ),
            row=row, col=col_idx
        )
    
    component_fig.update_layout(
        title="Component Details",
        height=max(150 * rows, 400),
        showlegend=False,
        margin=dict(l=40, r=40, t=60, b=40),
        hovermode="x unified"
    )
    
    # Create raw data chart
    raw_data_fig = go.Figure()
    
    # Add raw data lines
    for i, col in enumerate(raw_data_cols):
        display_name = col.replace('Cyclical_Score_', '')
        raw_data_fig.add_trace(go.Scatter(
            x=company_data['Date'],
            y=company_data[col],
            mode='lines+markers',
            name=display_name,
            line=dict(color=px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)])
        ))
    
    raw_data_fig.update_layout(
        title="Raw Data Inputs",
        xaxis_title="Date",
        yaxis_title="Value",
        height=500,
        margin=dict(l=40, r=40, t=40, b=40),
        hovermode="x unified"
    )
    
    # Create individual raw data charts (2 columns)
    raw_data_names = [col.replace('Cyclical_Score_', '') for col in raw_data_cols]
    raw_rows = (len(raw_data_names) + 1) // 2  # Ceiling division to determine number of rows
    
    raw_data_detail_fig = make_subplots(
        rows=raw_rows, 
        cols=2,
        subplot_titles=raw_data_names,
        shared_xaxes=True
    )
    
    # Add each raw data item as a subplot
    for i, col in enumerate(raw_data_cols):
        row = (i // 2) + 1
        col_idx = (i % 2) + 1
        display_name = col.replace('Cyclical_Score_', '')
        
        raw_data_detail_fig.add_trace(
            go.Scatter(
                x=company_data['Date'],
                y=company_data[col],
                mode='lines+markers',
                name=display_name,
                line=dict(color=px.colors.qualitative.Plotly[i % len(px.colors.qualitative.Plotly)])
            ),
            row=row, col=col_idx
        )
    
    raw_data_detail_fig.update_layout(
        title="Raw Data Details",
        height=max(150 * raw_rows, 400),
        showlegend=False,
        margin=dict(l=40, r=40, t=60, b=40),
        hovermode="x unified"
    )
    
    # Return the details and charts
    charts = [
        dcc.Graph(figure=main_fig),
        dcc.Graph(figure=component_fig),
        html.H3("Raw Data Inputs", className="text-xl font-semibold mt-8 mb-4"),
        dcc.Graph(figure=raw_data_fig),
        dcc.Graph(figure=raw_data_detail_fig)
    ]
    
    return company_details, charts


# Add formula explanation to the app layout
def add_formula_explanation():
    return html.Div([
        html.H4("Raw Data Variables", className="text-md font-semibold mt-4 mb-2"),
        html.Ul([
            html.Li("Cyclical_Score_vol_sales", className="ml-4"),
            html.Li("Cyclical_Score_vol_oper_margin", className="ml-4"),
            html.Li("Cyclical_Score_fcf_ebitda_ratio", className="ml-4"),
            html.Li("Cyclical_Score_paid_dividend", className="ml-4"),
            html.Li("Cyclical_Score_div_vol", className="ml-4"),
            html.Li("Cyclical_Score_Beta vs SXXP (Rolling ewma 250D)", className="ml-4"),
            html.Li("Cyclical_Score_hurst", className="ml-4"),
            html.Li("Cyclical_Score_market_stress_relative_return", className="ml-4"),
            html.Li("Cyclical_Score_beta_pmi_opermargin", className="ml-4"),
        ], className="mb-4")
    ], className="mb-6 p-4 bg-gray-50 border rounded")

# Run the app
if __name__ == '__main__':
    app.run_server(debug=True)
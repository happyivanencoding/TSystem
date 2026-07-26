# Historical reference: legacy Screen column description

> Archived on 2026-07-26. This list is not the live schema; use `DATA_CONTRACT.md` and the current database profile.

Financial Data DataFrame Documentation  
=====================================  

This DataFrame contains comprehensive financial and investment data including company identifiers,  
factor scores, valuation metrics, and index weights.  

Note: All Percentile Metrics are Adjusted for Sector Neutrality  

COLUMNS:  
--------  

Identifier and Descriptive Information:  
--------------------------------------  
'Symbol'                        - Ticker Symbol  
'Name'                          - Company Name  
'Exchange Country Name'         - Exchange Country  
'Company SEDOL'                 - SEDOL Identifier  
'ISIN'                          - International Securities Identification Number  
'FactSet Ind'                   - FactSet Industry Classification  
'FactSet Economy'               - FactSet Economic Sector  
'Curncy Iso'                    - Currency ISO Code  
'Exchange Country Region'       - Exchange Country Region  
' Benchmark ICB Industry '      - Benchmark ICB Industry  
' Benchmark ICB Supersector '   - Benchmark ICB Supersector  
'Benchmark Market Value Millions in EUR' - Benchmark Market Cap (EUR Millions)  
'Date'                          - Date  

Factor Exposures and Scores:  
---------------------------  
'Dividend Avg Percentile'       - Dividend Factor Score (from 0 to 10)  
'Value Avg Percentile'          - Value Factor Score (from 0 to 10)  
'Quality Avg Percentile'        - Quality Factor Score (from 0 to 10)  
'Mom Avg Percentile'            - Momentum Factor Score (from 0 to 10)  
'Size Avg Percentile'           - Size Factor Score (from 0 to 10)  
'LowVol Avg Percentile'         - Low Volatility Factor Score (from 0 to 10)  
'Growth Avg Percentile'         - Growth Factor Score (from 0 to 10)  
'MOM Score'                     - Momentum Score  
'PCT MOM Score'                 - Momentum Score Percentile  
'Value_Forward Avg Percentile'  - Value Factor Score based on Forward Metrics (from 0 to 10)  
'Value_Spot_Avg Percentile'     - Value Factor Score based on Spot Metrics (from 0 to 10)  
'Growth_Forward_Avg Percentile' - Growth Factor Score based on Forward Metrics (from 0 to 10)  
'Growth_Historical_Avg Percentile' - Historical Growth Factor Score (from 0 to 10)  

Returns and Performance:  
-----------------------  
'Total Return'                  - Total Return for the last month  
'TTR_Fwd1M'                     - Forward 1-Month Total Return, estimated  
'Constituent Weight SOM'        - Constituent Weight (Start of Month)  
'PMOM 12M1M'                    - Price Momentum (12 Month - 1 Month)  
'PCT MOM 12M1M'                 - Price Momentum Percentile (12 Month - 1 Month)  

Earnings and Revisions:  
----------------------  
'EPS Med NTM -3M'               - EPS Median Estimate (NTM, 3 Months Ago)  
'EPS Med NTM 0'                 - EPS Median Estimate (NTM, Current)  
'EPS NTM 3M Growth'             - EPS Estimate Growth (NTM, 3 Month Change)  
'PCT EPSM3M'                    - EPS Estimate Growth Percentile (NTM, 3 Month Change)  
'EPS Revision Ratio'            - Calculates the net optimism of analysts by comparing the total number of upward revisions to downward revisions, normalized by the total number of estimates  
'PCT ERR'                       - EPS Revision Ratio Percentile  

Valuation Metrics:  
-----------------  
'PE LTM'                        - PE Ratio (Last 12 Months)  
'PE FY1'                        - PE Ratio Forward (Next Year)  
'PCT PE LTM'                    - PE Ratio Percentile (Last 12 Months)  
'PCT PE FY1'                    - PE Ratio Forward Percentile (Next Year)  
'PB LTM'                        - PB Ratio (Last 12 Months)  
'Price to Book FY1'             - PB Ratio Forward (Next Year)  
'PTangibleBook LTM'             - Price to Tangible Book Ratio (Last 12 Months)  
'PB / PTangibleBook LTM'        - PB to PTB Ratio (Last 12 Months)  
'PB / PTangibleBook NTM'        - PB to PTB Ratio Forward (Next Year)  
'PCT PB LTM'                    - PB Ratio Percentile (Last 12 Months)  
'PCT PB FY1'                    - PB Ratio Forward Percentile (Next Year)  
'PFCF LTM'                      - PFCF Ratio (Last 12 Months)  
'Price to FreeCF FY1'           - PFCF Ratio Forward (Next Year)  
'PCT PFCF LTM'                  - PFCF Ratio Percentile (Last 12 Months)  
'PCT PFCF FY1'                  - PFCF Ratio Forward Percentile (Next Year)  
'EV To EBITDA LTM'              - EV/EBITDA Ratio (Last 12 Months)  
'EV To EBITDA FY1'              - EV/EBITDA Ratio Forward (Next Year)  
'PCT EVEBITDA LTM'              - EV/EBITDA Percentile (Last 12 Months)  
'PCT EVEBITDA FY1'              - EV/EBITDA Forward Percentile (Next Year)  
'EV to Ebit FY1'                - EV/EBIT Ratio Forward (Next Year)  
'PCT EVEBIT NTM'                - EV/EBIT Forward Percentile (Next Year)  
'EV to Sales LTM'               - EV/Sales Ratio (Last 12 Months)  
'PCT EV to Sales LTM'           - EV/Sales Percentile (Last 12 Months)  
'EV to Sales FY1'               - EV/Sales Ratio Forward (Next Year)  
'PCT EV to Sales FY1'           - EV/Sales Forward Percentile (Next Year)  

Quality Metrics:  
---------------  
'ROE avg FY0'                   - Return on Equity (Current)  
'PCT ROE'                       - Return on Equity Percentile (Current)  
'NetDebt to EBITDA exFIN'       - Net Debt to EBITDA Ratio (Excluding Financials)  
'PCT NBEBITDA'                  - Net Debt to EBITDA Percentile  
'Oper Margin'                   - Operating Margin  
'PCT OM FY0'                    - Operating Margin Percentile (Current)  
'Asset TO exFIN'                - Asset Turnover Ratio (Excluding Financials)  
'PCT Asset TO'                  - Asset Turnover Percentile  
'TIER1 Ratio FY0'               - Tier 1 Ratio (Current)  
'PCT TIER1'                     - Tier 1 Ratio Percentile  
'ROTE avg FY1'                  - Return on Tangible Equity Forward (Next Year)  
'PCT ROTE'                      - Return on Tangible Equity Percentile  
'Combined Ratio FY1'            - Combined Ratio Forward (Next Year)  
'PCT CombinedRatio'             - Combined Ratio Percentile  

Dividend Metrics:  
----------------  
'DVD Yield FY0'                 - Dividend Yield (Current)  
'DVD Payout FY0'                - Dividend Payout Ratio (Current)  
'DVD Yield FY1'                 - Dividend Yield Forward (Next Year)  
'DPS 1Y Growth Forecast'        - Dividend Per Share Growth Forecast (1 Year)  
'DPS FY1'                       - Dividend Per Share Forward (Next Year)  
'D_DPS TrendStab'               - Dividend Per Share Trend Slope  
'PCT Payout Ratio'              - Payout Ratio Percentile  
'PCT DPS 1YGR'                  - Dividend Per Share Growth Percentile (1 Year)  
'PCT DvdYield FY1'              - Dividend Yield Forward Percentile (Next Year)  
'Earns Yield FY0'               - Earnings Yield (Current)  
'Earns Yield FY1'               - Earnings Yield Forward (Next Year)  

Growth Metrics:  
--------------  
'Sales Growth FY1'              - Sales Growth Forecast (Next Year)  
'PCT Sales Growth'              - Sales Growth Percentile (Next Year)  
'Gross Income Growth FY1'       - Gross Income Growth Forecast (Next Year)  
'PCT Gross Income Growth'       - Gross Income Growth Percentile (Next Year)  
'EPS Growth FY1'                - EPS Growth Forecast (Next Year)  
'PCT EPS Growth FY1'            - EPS Growth Percentile (Next Year)  
'5Y_Hist EPS TrendStab'         - 5-Year Historical EPS Trend Slope  
'PCT Hist EPS'                  - 5-Year Historical EPS Trend Percentile  
'5Y_Hist GrossInc TrendStab'    - 5-Year Historical Gross Income Trend Slope  
'PCT Hist GrossInc'             - 5-Year Historical Gross Income Percentile  
'5Y_Hist Sales TrendStab'       - 5-Year Historical Sales Trend Slope  
'PCT Hist Sales'                - 5-Year Historical Sales Trend Percentile  

Volatility Metrics:  
------------------  
'Daily Vol 60J'                 - 60-Day Volatility  
'PCT DVol 60J'                  - 60-Day Volatility Percentile  
'Daily Vol 90J'                 - 90-Day Volatility  
'PCT DVol 90J'                  - 90-Day Volatility Percentile  
'Daily Vol 260J'                - 260-Day Volatility  
'PCT DVol 260J'                 - 260-Day Volatility Percentile  

Size Metrics:  
------------  
'PCT Sales FY0'                 - Sales Percentile (Current)  
'PCT Assets FY0'                - Assets Percentile (Current)  
'PCT Mkt Value'                 - Market Value Percentile  

Index Weights:  
-------------  
'Weight in DJ BROOKFIELD_x'     - Weight in DJ Brookfield Infrastructure Index (x variant)  
'Weight in DJ BROOKFIELD_y'     - Weight in DJ Brookfield Infrastructure Index (y variant)  
'Weight in GLOBAL INFRA'        - Weight in S&P Global Infrastructure Index  
'Weight in GLOBAL REIT'         - Weight in S&P Global REIT Index  
'Weight in MSCI ACWI'           - Weight in MSCI ACWI Index  
'Weight in MSCI EM'             - Weight in MSCI Emerging Markets Index  
'Weight in MSCI EUR SMALL'      - Weight in MSCI Europe Small Cap Index  
'Weight in NIKKEI'              - Weight in Nikkei 225 Index  
'Weight in NMX'                 - Weight in NASDAQ OMX Nordic Index  
'Weight in SP500'               - Weight in S&P 500 Index  
'Weight in STOXX EUROPE 600'    - Weight in STOXX Europe 600 Index  
'Weight in MSCI WORLD'          - Weight in MSCI World Index  
'Weight in MSCI EUR'            - Weight in MSCI Europe Index  
'Weight in CAC40'               - Weight in CAC 40 Index  
'Weight in EUROSTOXX50'         - Weight in EURO STOXX 50 Index  
'Weight in MSCI EMU'            - Weight in MSCI EMU Index  
'Weight in NASDAQ COMP'         - Weight in NASDAQ Composite Index  
'Weight in RUSSELL 2000'        - Weight in Russell 2000 Index  

Additional Financial Metrics:  
===========================  

Cash Flow Metrics:  
-----------------  
'CFO'                          - Cash Flow from Operations  
'CFO 5Y CAGR'                  - Cash Flow from Operations 5-Year Compound Annual Growth Rate  
'CFO Div Cov Ratio'            - Cash Flow from Operations Dividend Coverage Ratio  
'FCF'                          - Free Cash Flow  
'FCF Div Cov Ratio'            - Free Cash Flow Dividend Coverage Ratio  
'P to CFO'                     - Price to Cash Flow from Operations Ratio  

Earnings Metrics:  
----------------  
'EPS'                          - Earnings Per Share  
'EPS Estimates FY1'            - Earnings Per Share Estimates (Next Fiscal Year)  
'EPS Growth FY1 CIQ'           - Earnings Per Share Growth (Next Fiscal Year) from Capital IQ  
'Const Earning 5Y CAGR'        - Constant Earnings 5-Year Compound Annual Growth Rate  
'Cont Op'                      - Continuing Operations Earnings  
'Cont Op Earning Margin'       - Continuing Operations Earnings Margin  
'Net Income'                   - Net Income  
'Operative Income'             - Operating Income  
'Price Cont Op Earning'        - Price to Continuing Operations Earnings Ratio  

EBIT/EBITDA Metrics:  
-------------------  
'Ebit'                         - Earnings Before Interest and Taxes  
'Ebit 5Y CAGR'                 - EBIT 5-Year Compound Annual Growth Rate  
'Ebitda'                       - Earnings Before Interest, Taxes, Depreciation, and Amortization  
'EBITDA FY1'                   - EBITDA Forecast (Next Fiscal Year)  
'Ebitda 5Y CAGR'               - EBITDA 5-Year Compound Annual Growth Rate  
'Ebitda Margin'                - EBITDA as a Percentage of Revenue  
'Ebitda to Int expense'        - EBITDA to Interest Expense Ratio (Interest Coverage)  
'EBITDA Growth FY1 CIQ'        - EBITDA Growth (Next Fiscal Year) from Capital IQ  

Valuation Metrics:  
-----------------  
'EV to Ebit'                   - Enterprise Value to EBIT Ratio  
'EV to Ebit FY1 CIQ'           - Enterprise Value to EBIT Ratio Forward (Next Fiscal Year) from Capital IQ  
'Market Cap'                   - Market Capitalization  
'PE FY1 CIQ'                   - Price to Earnings Ratio Forward (Next Fiscal Year) from Capital IQ  

Sales & Revenue Metrics:  
----------------------  
'Sales'                        - Total Sales Revenue  
'Sales FY1'                    - Sales Forecast (Next Fiscal Year)  
'Sales Growth FY1 CIQ'         - Sales Growth (Next Fiscal Year) from Capital IQ  
'Revenue 5Y CAGR'              - Revenue 5-Year Compound Annual Growth Rate  
'Gross Margin'                 - Gross Profit as a Percentage of Revenue  
'Gross Profit 5Y CAGR'         - Gross Profit 5-Year Compound Annual Growth Rate  

Balance Sheet & Debt Metrics:  
---------------------------  
'Current Ratio'                - Current Assets divided by Current Liabilities  
'Net Debt'                     - Total Debt minus Cash and Cash Equivalents  
'Net Debt to Ebit'             - Net Debt to EBIT Ratio  
'Net Debt to Market Cap'       - Net Debt to Market Capitalization Ratio  
'Net Debt to Tot Equity'       - Net Debt to Total Equity Ratio  
'Total Cash and Equiv'         - Total Cash and Cash Equivalents  
'Total Debt'                   - Total Short-term and Long-term Debt  
'Total Equity'                 - Total Shareholder Equity  

Other Metrics:  
------------  
'Pct_Short_Interest'           - Percentage of Float Shares Sold Short  
'Reco Analyst'                 - Analyst Recommendation Score  

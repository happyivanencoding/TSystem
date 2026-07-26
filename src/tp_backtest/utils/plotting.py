"""
使用Plotly的可视化工具
"""

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Optional, Tuple


class PlotlyVisualizer:
    """Handles all plotting functionality using Plotly."""
    
    @staticmethod
    def plot_portfolio_vs_benchmark(
        perf_ptf: pd.Series,
        perf_bench: pd.Series,
        title: Optional[str] = None,
        save_path: Optional[str] = "portfolio_performance.html",
        show_plot: bool = True
    ) -> go.Figure:
        """
        绘图 投资组合 业绩 vs 基准 with 比率 subplot.
        
        参数:
        -----------
        perf_ptf : Series
            投资组合 业绩 时间 series
        perf_bench : Series
            基准 业绩 时间 series
        title : str, 可选
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
        show_plot : bool
            是否 display the 绘图
            
        收益率:
        --------
        Figure
            Plotly figure object
    """
        # Concatenate dataframes
        df_plot = pd.concat([perf_ptf, perf_bench], axis=1)
        
        # 创建 subplots
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Performance", "Ratio")
        )
        
        # Add traces for 业绩
        for i, col in enumerate(df_plot.columns):
            label = 'Perf PTF' if i == 0 else 'Perf Bench'
            
            # Add line trace
            fig.add_trace(
                go.Scatter(
                    x=df_plot.index,
                    y=df_plot.iloc[:, i],
                    mode='lines',
                    name=label,
                    line=dict(width=2)
                ),
                row=1, col=1
            )
            
            # Add annotation for last 值
            last_x = df_plot.index[-1]
            last_y = df_plot.iloc[:, i].iloc[-1]
            
            fig.add_annotation(
                x=last_x,
                y=last_y,
                text=f'{last_y:.2f}',
                showarrow=False,
                xanchor='left',
                font=dict(size=10),
                bgcolor='rgba(255,255,255,0.8)',
                bordercolor='rgba(0,0,0,0.2)',
                borderwidth=1,
                row=1, col=1
            )
        
        # Add trace for the 比率
        ratio = df_plot.iloc[:, 0] / df_plot.iloc[:, 1]
        fig.add_trace(
            go.Scatter(
                x=df_plot.index,
                y=ratio,
                mode='lines',
                name='Ratio',
                line=dict(width=2, color='red')
            ),
            row=2, col=1
        )
        
        # Add annotation for last 值 of the 比率
        last_ratio = ratio.iloc[-1]
        fig.add_annotation(
            x=last_x,
            y=last_ratio,
            text=f'{last_ratio:.2f}',
            showarrow=False,
            xanchor='left',
            font=dict(size=10),
            bgcolor='rgba(255,255,255,0.8)',
            bordercolor='rgba(0,0,0,0.2)',
            borderwidth=1,
            row=2, col=1
        )
        
        # 更新 layout
        fig.update_layout(
            title=title if title else "",
            width=700,
            height=600,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=50, r=50, t=50, b=50),
            plot_bgcolor='white',
            paper_bgcolor='white'
        )
        
        # 更新 axes
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )
        
        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='lightgray',
            showline=True,
            linewidth=1,
            linecolor='black'
        )
        
        # Handle different environments
        if save_path:
            fig.write_html(save_path)
            print(f"Plot saved as HTML to: {save_path}")
        
        if show_plot:
            try:
                fig.show()
            except Exception as e:
                print(f"Cannot display plot directly: {e}")
                temp_path = "temp_plot.html"
                fig.write_html(temp_path)
                print(f"Plot saved as HTML to: {temp_path}")
                print("Please open this file in your web browser to view the plot.")
        
        return fig
    
    @staticmethod
    def plot_top_bottom_vs_benchmark(
        perf_top: pd.Series,
        perf_bottom: pd.Series,
        perf_bench: pd.Series,
        title: Optional[str] = None,
        save_path: Optional[str] = "top_bottom_performance.html",
        show_plot: bool = True,
    ) -> go.Figure:
        """
        绘制 Top、Bottom、Benchmark 的累计表现，并在第二层展示 Top/Benchmark、Bottom/Benchmark、Top/Bottom ratio。
        """
        df_plot = pd.concat([perf_top, perf_bottom, perf_bench], axis=1)
        df_plot.columns = ["Top", "Bottom", "Benchmark"]
        df_plot = df_plot.sort_index().ffill().dropna(how="all")

        fig = make_subplots(
            rows=2,
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Performance", "Ratios"),
        )

        colors = {
            "Top": "#1f77b4",
            "Bottom": "#d62728",
            "Benchmark": "#2ca02c",
            "Top / Benchmark": "#1f77b4",
            "Bottom / Benchmark": "#d62728",
            "Top / Bottom": "#9467bd",
        }

        for column in ["Top", "Bottom", "Benchmark"]:
            fig.add_trace(
                go.Scatter(
                    x=df_plot.index,
                    y=df_plot[column],
                    mode="lines",
                    name=column,
                    line=dict(width=2, color=colors[column]),
                ),
                row=1,
                col=1,
            )

        ratios = {
            "Top / Benchmark": df_plot["Top"] / df_plot["Benchmark"],
            "Bottom / Benchmark": df_plot["Bottom"] / df_plot["Benchmark"],
            "Top / Bottom": df_plot["Top"] / df_plot["Bottom"],
        }
        for name, ratio in ratios.items():
            ratio = ratio.replace([float("inf"), float("-inf")], pd.NA)
            fig.add_trace(
                go.Scatter(
                    x=df_plot.index,
                    y=ratio,
                    mode="lines",
                    name=name,
                    line=dict(width=2, color=colors[name]),
                ),
                row=2,
                col=1,
            )

        fig.update_layout(
            title=title if title else "",
            width=850,
            height=700,
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1,
            ),
            margin=dict(l=50, r=50, t=60, b=50),
            plot_bgcolor="white",
            paper_bgcolor="white",
        )
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", showline=True, linewidth=1, linecolor="black")
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor="lightgray", showline=True, linewidth=1, linecolor="black")

        if save_path:
            fig.write_html(save_path)
            print(f"Plot saved as HTML to: {save_path}")

        if show_plot:
            try:
                fig.show()
            except Exception as e:
                print(f"Cannot display plot directly: {e}")

        return fig
    
    @staticmethod
    def plot_drawdown(
        returns: pd.Series,
        title: str = "Drawdown Analysis",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 cumulative 收益率 and drawdown.
        
        参数:
        -----------
        收益率 : Series
            收益 时间 series
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        cumulative = (1 + returns).cumprod()
        running_max = cumulative.expanding().max()
        drawdown = (cumulative - running_max) / running_max
        
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=("Cumulative Returns", "Drawdown")
        )
        
        # Cumulative 收益率
        fig.add_trace(
            go.Scatter(
                x=cumulative.index,
                y=cumulative,
                mode='lines',
                name='Cumulative Returns',
                line=dict(color='blue')
            ),
            row=1, col=1
        )
        
        # Drawdown
        fig.add_trace(
            go.Scatter(
                x=drawdown.index,
                y=drawdown * 100,
                mode='lines',
                name='Drawdown %',
                line=dict(color='red'),
                fill='tozeroy'
            ),
            row=2, col=1
        )
        
        fig.update_layout(
            title=title,
            height=600,
            showlegend=True
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_monthly_returns_heatmap(
        returns: pd.Series,
        title: str = "Monthly Returns Heatmap",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 monthly 收益率 as a heatmap.
        
        参数:
        -----------
        收益率 : Series
            Daily or monthly 收益率
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        # Resample to monthly if daily
        if len(returns) > 252:
            monthly_returns = (1 + returns).resample('M').prod() - 1
        else:
            monthly_returns = returns
        
        # 创建 year-month matrix
        monthly_returns = monthly_returns.to_frame('Return')
        monthly_returns['Year'] = monthly_returns.index.year
        monthly_returns['Month'] = monthly_returns.index.month
        
        # Pivot to 创建 heatmap 数据
        heatmap_data = monthly_returns.pivot(
            index='Year',
            columns='Month',
            values='Return'
        ) * 100  # Convert to percentage
        
        # 创建 heatmap
        fig = go.Figure(data=go.Heatmap(
            z=heatmap_data.values,
            x=[f'{m:02d}' for m in heatmap_data.columns],
            y=heatmap_data.index,
            colorscale='RdYlGn',
            zmid=0,
            text=heatmap_data.values,
            texttemplate='%{text:.1f}%',
            textfont={"size": 10},
            colorbar=dict(title="Return %")
        ))
        
        fig.update_layout(
            title=title,
            xaxis_title="Month",
            yaxis_title="Year",
            height=400 + len(heatmap_data) * 30
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_ic_heatmap(
        ic_time_series: pd.DataFrame,
        title: str = "IC Heatmap",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 信息系数 heatmap.
        
        参数:
        -----------
        ic_time_series : DataFrame
            IC 时间 series (索引: dates, columns: 因子)
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        # Resample to monthly
        monthly_ic = ic_time_series.resample('M').mean()
        monthly_ic['Year'] = monthly_ic.index.year
        monthly_ic['Month'] = monthly_ic.index.month
        
        # 创建 subplots for each 因子
        factors = [col for col in ic_time_series.columns if col not in ['Year', 'Month']]
        
        fig = make_subplots(
            rows=len(factors),
            cols=1,
            subplot_titles=factors,
            vertical_spacing=0.05
        )
        
        for i, factor in enumerate(factors, 1):
            heatmap_data = monthly_ic.pivot(
                index='Year',
                columns='Month',
                values=factor
            )
            
            fig.add_trace(
                go.Heatmap(
                    z=heatmap_data.values,
                    x=[f'{m:02d}' for m in heatmap_data.columns],
                    y=heatmap_data.index,
                    colorscale='RdBu',
                    zmid=0,
                    showscale=(i == 1)
                ),
                row=i, col=1
            )
        
        fig.update_layout(
            title=title,
            height=300 * len(factors)
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_rolling_metrics(
        returns: pd.Series,
        window: int = 60,
        metrics: list = ['sharpe', 'volatility'],
        title: str = "Rolling Metrics",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 rolling 业绩 指标.
        
        参数:
        -----------
        收益率 : Series
            收益 series
        window : int
            Rolling window size
        指标 : 列表
            指标 to 绘图 ('sharpe', '波动率', 'max_dd')
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        from tp_backtest.core.metrics import PerformanceMetrics
        
        fig = make_subplots(
            rows=len(metrics),
            cols=1,
            shared_xaxes=True,
            vertical_spacing=0.1,
            subplot_titles=[m.replace('_', ' ').title() for m in metrics]
        )
        
        for i, metric in enumerate(metrics, 1):
            if metric == 'sharpe':
                rolling_values = returns.rolling(window).apply(
                    lambda x: PerformanceMetrics.sharpe_ratio(pd.Series(x))
                )
                metric_name = 'Sharpe Ratio'
            elif metric == 'volatility':
                rolling_values = returns.rolling(window).std() * np.sqrt(252)
                metric_name = 'Volatility'
            elif metric == 'max_dd':
                rolling_values = returns.rolling(window).apply(
                    lambda x: PerformanceMetrics.max_drawdown(pd.Series(x))
                )
                metric_name = 'Max Drawdown'
            else:
                continue
            
            fig.add_trace(
                go.Scatter(
                    x=rolling_values.index,
                    y=rolling_values,
                    mode='lines',
                    name=metric_name
                ),
                row=i, col=1
            )
        
        fig.update_layout(
            title=title,
            height=300 * len(metrics),
            showlegend=True
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_factor_exposure_radar(
        exposures: pd.DataFrame,
        date: Optional[pd.Timestamp] = None,
        title: str = "Factor Exposure",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 因子 exposures as radar chart.
        
        参数:
        -----------
        exposures : DataFrame
            因子 exposures (索引: dates, columns: 因子)
        日期 : Timestamp, 可选
            日期 to 绘图 (默认: latest)
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        if date is None:
            date = exposures.index[-1]
        
        exposure_values = exposures.loc[date]
        
        fig = go.Figure(data=go.Scatterpolar(
            r=exposure_values.values,
            theta=exposure_values.index,
            fill='toself',
            name=f'Exposure on {date.strftime("%Y-%m-%d")}'
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[exposure_values.min() * 1.1, exposure_values.max() * 1.1]
                )
            ),
            title=title,
            showlegend=False
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_attribution_waterfall(
        attribution_results: dict,
        title: str = "Attribution Analysis",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 归因 分析 as waterfall chart.
        
        参数:
        -----------
        attribution_results : 字典
            Results from Brinson 归因
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        # 聚合 归因 components
        allocation = attribution_results['allocation'].sum().sum()
        selection = attribution_results['selection'].sum().sum()
        interaction = attribution_results['interaction'].sum().sum()
        total = allocation + selection + interaction
        
        # 创建 waterfall 数据
        x = ['Benchmark', 'Allocation', 'Selection', 'Interaction', 'Portfolio']
        y = [0, allocation, selection, interaction, total]
        
        fig = go.Figure(go.Waterfall(
            x=x,
            y=y,
            measure=['absolute', 'relative', 'relative', 'relative', 'total'],
            text=[f'{v:.2%}' for v in y],
            textposition='outside',
            connector={"line": {"color": "rgb(63, 63, 63)"}},
        ))
        
        fig.update_layout(
            title=title,
            showlegend=False,
            yaxis_title="Contribution",
            height=500
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig
    
    @staticmethod
    def plot_turnover_analysis(
        turnover_data: pd.DataFrame,
        title: str = "Portfolio Turnover",
        save_path: Optional[str] = None
    ) -> go.Figure:
        """
        绘图 投资组合 turnover over 时间.
        
        参数:
        -----------
        turnover_data : DataFrame
            Turnover 数据 with '日期' and 'turnover' columns
        title : str
            绘图 title
        save_path : str, 可选
            路径 to 保存 HTML 文件
            
        收益率:
        --------
        Figure
            Plotly figure object
        """
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=turnover_data['date'],
            y=turnover_data['turnover'] * 100,
            mode='lines+markers',
            name='Turnover',
            line=dict(color='blue')
        ))
        
        # Add average line
        avg_turnover = turnover_data['turnover'].mean() * 100
        fig.add_hline(
            y=avg_turnover,
            line_dash="dash",
            line_color="red",
            annotation_text=f"Average: {avg_turnover:.1f}%"
        )
        
        fig.update_layout(
            title=title,
            xaxis_title="Date",
            yaxis_title="Turnover %",
            height=400,
            showlegend=True
        )
        
        if save_path:
            fig.write_html(save_path)
        
        return fig


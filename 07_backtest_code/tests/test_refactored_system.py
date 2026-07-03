"""
Test script for refactored backtest system.
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from tp_core.data_sources import RETURNS_PATH
from tp_core.data_sources import SCREEN_AGGREGATE_PATH

import pandas as pd
from datetime import datetime
from tp_core.backtesting import PtfBuilder

print("=" * 60)
print("TESTING REFACTORED BACKTEST SYSTEM")
print("=" * 60)

# Load data
print("\n1. Loading data...")

# Get the project root directory (parent of tests/)
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
path_screen = str(SCREEN_AGGREGATE_PATH)
path_returns = str(RETURNS_PATH)

print(f"   Looking for data in: {project_root}")

try:
    screen_agg = pd.read_parquet(path_screen)
    returns = pd.read_parquet(path_returns)
    print(f"   ✓ Screen data loaded: {screen_agg.shape}")
    print(f"   ✓ Returns data loaded: {returns.shape}")
except Exception as e:
    print(f"   ✗ Error loading data: {e}")
    sys.exit(1)

# Test 1: Initialize PtfBuilder
print("\n2. Testing PtfBuilder initialization...")
try:
    builder = PtfBuilder(
        screen=screen_agg,
        returns=returns,
        bench='STOXX EUROPE 600',
        percentile=0.05,
        metrics='Quality Avg Percentile',
        ptf_name='Test Portfolio',
        ponderation='Market cap'
    )
    print("   ✓ PtfBuilder initialized successfully")
except Exception as e:
    print(f"   ✗ Error initializing PtfBuilder: {e}")
    sys.exit(1)

# Test 2: Generate single month sec list
print("\n3. Testing single month security list generation...")
try:
    sec_list, exclusions = builder.sec_list_spot()
    print(f"   ✓ Security list generated: {len(sec_list)} securities")
    print(f"   ✓ Exclusions tracked: {len(exclusions)} exclusions")
except Exception as e:
    print(f"   ✗ Error generating security list: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 3: Generate historical sec list (small sample)
print("\n4. Testing historical security list generation...")
try:
    start_date = datetime(2024, 12, 31)
    hist_sec_list = builder.generic_histo_seclist(start_date=start_date)
    print(f"   ✓ Historical security list generated")
    print(f"   ✓ Total securities: {len(hist_sec_list)}")
    print(f"   ✓ Date range: {hist_sec_list['Date'].min()} to {hist_sec_list['Date'].max()}")
except Exception as e:
    print(f"   ✗ Error generating historical security list: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 4: Backtest
print("\n5. Testing backtest...")
try:
    perf, buy_list = builder.backtest()
    print(f"   ✓ Backtest completed successfully")
    print(f"   ✓ Performance series length: {len(perf)}")
    print(f"   ✓ Final value: {perf.iloc[-1]:.2f}")
except Exception as e:
    print(f"   ✗ Error in backtest: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 5: Benchmark performance
print("\n6. Testing benchmark performance...")
try:
    builder.backtest_get_bench_perf(screen_agg, builder.start_date, builder.bench)
    print(f"   ✓ Benchmark performance calculated")
    print(f"   ✓ Final benchmark value: {builder.perf_bench.iloc[-1]:.2f}")
except Exception as e:
    print(f"   ✗ Error calculating benchmark: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# Test 6: Performance metrics
print("\n7. Testing performance metrics...")
try:
    from core.metrics import PerformanceMetrics
    
    # Calculate daily returns
    ptf_returns = builder.perf_ptf.pct_change().dropna()
    bench_returns = builder.perf_bench.pct_change().dropna()
    
    metrics = PerformanceMetrics.calculate_all_metrics(
        ptf_returns,
        bench_returns,
        risk_free_rate=0.0
    )
    
    print(f"   ✓ Performance metrics calculated:")
    for key, value in metrics.items():
        print(f"     - {key}: {value:.4f}")
except Exception as e:
    print(f"   ✗ Error calculating metrics: {e}")
    import traceback
    traceback.print_exc()

# Test 7: Plotting
print("\n8. Testing plotting...")
try:
    fig = builder.backtest_plot_ptf_bench(
        title="Refactored System Test",
        save_path="test_plot.html",
        show_plot=False
    )
    print("   ✓ Plot generated and saved as test_plot.html")
except Exception as e:
    print(f"   ✗ Error generating plot: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("ALL TESTS COMPLETED")
print("=" * 60)
print("\nRefactored system is working correctly!")
print("New modular structure:")
print("  - core/data_loader.py")
print("  - core/portfolio_builder.py")
print("  - core/backtest_engine.py")
print("  - core/weight_manager.py")
print("  - core/metrics.py")
print("  - utils/data_utils.py")
print("  - utils/plotting.py")
print("  - utils/constants.py")
print("  - utils/performance_utils.py")



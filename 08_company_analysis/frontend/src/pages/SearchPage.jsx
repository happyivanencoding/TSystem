import React, { useState, useEffect, useMemo, useRef } from 'react';
import { Search, Copy, Check, TrendingUp, DollarSign, Activity, PieChart, BarChart, ArrowRight, Zap, Award, ChevronDown, ChevronUp, Plus, Minus, X, Columns } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis, Legend } from 'recharts';

const SearchPage = ({ stateRef }) => {
  const ref = stateRef || { current: {} };

  const [query, setQuery] = useState(ref.current.query || '');
  const [results, setResults] = useState(ref.current.results || []);
  const [loading, setLoading] = useState(false);
  const [selectedCompany, setSelectedCompany] = useState(ref.current.selectedCompany || null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  // History Data State
  const [historyData, setHistoryData] = useState(ref.current.historyData || null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [expandedMetric, setExpandedMetric] = useState(ref.current.expandedMetric || null);
  const [range, setRange] = useState(ref.current.range || '3Y');

  // 对比功能状态
  const [compareList, setCompareList] = useState(ref.current.compareList || []);
  const [compareOpen, setCompareOpen] = useState(ref.current.compareOpen || false);
  const [compareMetric, setCompareMetric] = useState(ref.current.compareMetric || null);
  // 防止同一 ISIN 重复发起 history 请求
  const historyFetchedRef = useRef(new Set());

  // 将状态同步到 ref，路由切换后可恢复
  useEffect(() => {
    ref.current.query = query;
    ref.current.results = results;
    ref.current.selectedCompany = selectedCompany;
    ref.current.historyData = historyData;
    ref.current.expandedMetric = expandedMetric;
    ref.current.range = range;
    ref.current.compareList = compareList;
    ref.current.compareOpen = compareOpen;
    ref.current.compareMetric = compareMetric;
  }, [query, results, selectedCompany, historyData, expandedMetric, range, compareList, compareOpen, compareMetric]);

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;
    
    setLoading(true);
    setResults([]);
    setSelectedCompany(null);
    setHistoryData(null);
    setExpandedMetric(null);
    
    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      if (!res.ok) throw new Error('Search failed');
      const data = await res.json();
      setResults(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleSelectCompany = async (isin) => {
    setDetailsLoading(true);
    setHistoryData(null);
    setExpandedMetric(null);
    try {
      const res = await fetch(`/api/company/${isin}`);
      if (!res.ok) throw new Error('Fetch details failed');
      const data = await res.json();
      setSelectedCompany(data);
      setCopied(false);
    } catch (err) {
      console.error(err);
    } finally {
      setDetailsLoading(false);
    }
  };

  const fetchHistoryIfNeeded = async (isin) => {
      if (historyData || historyLoading) return;
      
      setHistoryLoading(true);
      try {
          const res = await fetch(`/api/company/${isin}/history`);
          if (!res.ok) throw new Error('Fetch history failed');
          const data = await res.json();
          setHistoryData(data);
      } catch (err) {
          console.error(err);
      } finally {
          setHistoryLoading(false);
      }
  };

  const handleMetricClick = (field) => {
      if (expandedMetric === field) {
          setExpandedMetric(null);
      } else {
          setExpandedMetric(field);
          if (selectedCompany?.data?.ISIN) {
              fetchHistoryIfNeeded(selectedCompany.data.ISIN);
          }
      }
  };

  // 获取对比公司的股价回报数据
  const fetchCompareReturns = async (isin) => {
    try {
      const res = await fetch(`/api/company/${isin}/returns`);
      if (!res.ok) return;
      const data = await res.json();
      setCompareList(prev => prev.map(c => c.isin === isin ? { ...c, returnsData: data } : c));
    } catch (err) {}
  };

  // 获取对比公司的历史指标数据（懒加载，每个 ISIN 只请求一次）
  const fetchCompareHistory = async (isin) => {
    if (historyFetchedRef.current.has(isin)) return;
    historyFetchedRef.current.add(isin);
    try {
      const res = await fetch(`/api/company/${isin}/history`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      setCompareList(prev => prev.map(c => c.isin === isin ? { ...c, historyData: data } : c));
    } catch (err) {
      historyFetchedRef.current.delete(isin);
    }
  };

  // 当选择历史指标时，为所有未获取历史数据的公司发起请求
  useEffect(() => {
    if (!compareMetric || !compareOpen) return;
    compareList.forEach(c => { if (!c.historyData) fetchCompareHistory(c.isin); });
  }, [compareMetric, compareOpen]); // eslint-disable-line

  // 添加/移除对比公司（最多 4 个）
  const toggleCompare = async (item, e) => {
    e.stopPropagation();
    const isInList = compareList.some(c => c.isin === item.ISIN);
    if (isInList) {
      setCompareList(prev => prev.filter(c => c.isin !== item.ISIN));
      historyFetchedRef.current.delete(item.ISIN);
      return;
    }
    if (compareList.length >= 4) return;
    try {
      const res = await fetch(`/api/company/${item.ISIN}`);
      if (!res.ok) return;
      const data = await res.json();
      setCompareList(prev => [...prev, {
        isin: item.ISIN, name: item.Name,
        data: data.data, medians: data.medians,
        returnsData: null, historyData: null
      }]);
      setCompareOpen(true);
      fetchCompareReturns(item.ISIN);
      if (compareMetric) fetchCompareHistory(item.ISIN);
    } catch (err) {
      console.error(err);
    }
  };

  const copyToClipboard = () => {
    if (!selectedCompany?.clipboard_text) return;
    navigator.clipboard.writeText(selectedCompany.clipboard_text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const rangeOptions = [
    { key: '1M', label: '1M' },
    { key: '3M', label: '3M' },
    { key: 'YTD', label: 'YTD' },
    { key: '6M', label: '6M' },
    { key: '1Y', label: '1Y' },
    { key: '3Y', label: '3Y' },
    { key: '5Y', label: '5Y' },
    { key: '10Y', label: '10Y' },
    { key: 'MAX', label: 'MAX' },
  ];

  // 对比面板：每个公司的颜色方案
  const COMPARE_COLORS = [
    { stroke: '#3b82f6', fill: '#3b82f6', text: 'text-blue-600', badge: 'bg-blue-100 text-blue-700' },
    { stroke: '#f97316', fill: '#f97316', text: 'text-orange-600', badge: 'bg-orange-100 text-orange-700' },
    { stroke: '#10b981', fill: '#10b981', text: 'text-emerald-600', badge: 'bg-emerald-100 text-emerald-700' },
    { stroke: '#8b5cf6', fill: '#8b5cf6', text: 'text-violet-600', badge: 'bg-violet-100 text-violet-700' },
  ];

  // 对比面板展示的指标（横向表格）
  const COMPARE_METRICS = [
    { label: 'Score ML', field: 'Score ML' },
    { label: 'PE (NTM)', field: 'PE NTM' },
    { label: 'EV/EBITDA (NTM)', field: 'EV To EBITDA NTM' },
    { label: 'PB (LTM)', field: 'PB LTM' },
    { label: 'Div Yield', field: 'DVD Yield NTM', suffix: '%' },
    { label: 'EPS Growth', field: 'EPS Growth NTM', suffix: '%' },
    { label: 'ROE (FY0)', field: 'ROE avg FY0', suffix: '%' },
    { label: 'Oper Margin', field: 'Oper Margin', suffix: '%' },
  ];

  const filterHistoryByRange = (data, currentRange) => {
    if (!data || !Array.isArray(data) || data.length === 0) return [];
    if (currentRange === 'MAX') return data;

    const now = new Date();
    let cutoff;

    if (currentRange === 'YTD') {
      cutoff = new Date(now.getFullYear(), 0, 1); // 当年 1 月 1 日
    } else {
      const monthsMap = { '1M': 1, '3M': 3, '6M': 6, '1Y': 12, '3Y': 36, '5Y': 60, '10Y': 120 };
      const months = monthsMap[currentRange];
      if (!months) return data;
      cutoff = new Date(now);
      cutoff.setMonth(cutoff.getMonth() - months);
    }

    return data.filter((item) => {
      const d = item?.Date ? new Date(item.Date) : null;
      return d && d >= cutoff;
    });
  };

  // 历史指标对比可选项
  const HISTORY_METRICS = [
    { label: 'Score ML', field: 'Score ML' },
    { label: 'Value Score', field: 'Value Score (Histo + NTM)' },
    { label: 'Quality Score', field: 'Quality Score (Histo + NTM)' },
    { label: 'Growth Score', field: 'Growth Score (Histo + NTM)' },
    { label: 'Momentum', field: 'Momentum Score (Histo + FY1)' },
    { label: 'Dividend Score', field: 'Dividend Score (Histo + NTM)' },
    { label: 'LowVol Score', field: 'LowVol Score (Histo + FY1)' },
    { label: 'PE NTM', field: 'PE NTM' },
    { label: 'EV/EBITDA', field: 'EV To EBITDA NTM' },
    { label: 'ROE', field: 'ROE avg FY0' },
    { label: 'Oper Margin', field: 'Oper Margin' },
  ];

  // 合并多公司股价指数数据（在当前可见范围内起始点归一化为 100）
  const returnsChartData = useMemo(() => {
    if (!compareOpen) return [];
    const dateMap = {};
    compareList.forEach(c => {
      if (!c.returnsData) return;
      c.returnsData.forEach(row => {
        if (!dateMap[row.Date]) dateMap[row.Date] = { Date: row.Date };
        dateMap[row.Date][c.isin] = row.PriceIndex;
      });
    });
    const sorted = Object.values(dateMap).sort((a, b) => a.Date.localeCompare(b.Date));
    const filtered = filterHistoryByRange(sorted, range);
    if (filtered.length === 0) return [];

    // 找到每个公司在可见范围内的第一个有效值作为基准
    const baseValues = {};
    compareList.forEach(c => {
      const firstRow = filtered.find(row => row[c.isin] != null);
      if (firstRow) baseValues[c.isin] = firstRow[c.isin];
    });

    // 重新归一化：起始点 = 100
    return filtered.map(row => {
      const rebased = { Date: row.Date };
      compareList.forEach(c => {
        if (row[c.isin] != null && baseValues[c.isin]) {
          rebased[c.isin] = (row[c.isin] / baseValues[c.isin]) * 100;
        }
      });
      return rebased;
    });
  }, [compareList, compareOpen, range]);

  // 合并多公司历史指标数据
  const historyChartData = useMemo(() => {
    if (!compareMetric || !compareOpen) return [];
    const dateMap = {};
    compareList.forEach(c => {
      if (!c.historyData) return;
      c.historyData.forEach(row => {
        if (!dateMap[row.Date]) dateMap[row.Date] = { Date: row.Date };
        dateMap[row.Date][c.isin] = row[compareMetric];
      });
    });
    const sorted = Object.values(dateMap).sort((a, b) => a.Date.localeCompare(b.Date));
    return filterHistoryByRange(sorted, range);
  }, [compareList, compareMetric, compareOpen, range]);

  // Helper Chart Component
  const MetricChart = ({ field, color = "#3b82f6" }) => {
      const filteredData = filterHistoryByRange(historyData, range);
      return (
        <div className="h-48 w-full py-4 pl-2 pr-4 bg-slate-50/30 rounded-b-lg animate-in fade-in zoom-in-95 duration-300">
            {historyLoading ? (
                <div className="h-full flex items-center justify-center text-slate-400 text-sm gap-2">
                    <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-slate-400"></div>
                    Loading history...
                </div>
            ) : (!filteredData || filteredData.length === 0) ? (
                <div className="h-full flex items-center justify-center text-slate-400 text-sm">
                    No historical data available
                </div>
            ) : (
                <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={filteredData}>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                        <XAxis 
                          dataKey="Date" 
                          tick={{fontSize: 10, fill: '#94a3b8'}} 
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={(val) => val.slice(0,4)} 
                          minTickGap={30}
                        />
                        <YAxis 
                          domain={['auto', 'auto']} 
                          tick={{fontSize: 10, fill: '#94a3b8'}} 
                          axisLine={false}
                          tickLine={false}
                          width={30}
                        />
                        <Tooltip 
                          contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                          labelStyle={{ color: '#64748b', fontSize: '12px' }}
                        />
                        <Line 
                          type="monotone" 
                          dataKey={field} 
                          stroke={color} 
                          strokeWidth={2} 
                          dot={false} 
                          activeDot={{ r: 4 }}
                          connectNulls 
                          animationDuration={500}
                        />
                    </LineChart>
                </ResponsiveContainer>
            )}
        </div>
      );
  }

  // Helper to render score bars
  const ScoreBar = ({ label, field, value }) => {
    const isExpanded = expandedMetric === field;
    return (
      <div className="border-b border-white/0 last:border-0">
          <div 
             className={`flex items-center gap-3 py-2 px-2 rounded-lg transition-colors cursor-pointer ${isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50/50'}`}
             onClick={() => handleMetricClick(field)}
          >
            <div className="w-24 text-sm font-medium text-slate-500 flex items-center gap-1">
                {label}
                {isExpanded ? <ChevronUp size={12} className="text-slate-400"/> : <ChevronDown size={12} className="text-slate-300"/>}
            </div>
            <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
              <div 
                className="h-full bg-blue-500 rounded-full" 
                style={{ width: `${Math.min(Math.max(value || 0, 0), 10) * 10}%` }}
              />
            </div>
            <div className="w-8 text-right text-sm font-bold text-slate-700">{(value || 0).toFixed(1)}</div>
          </div>
          {isExpanded && <MetricChart field={field} color="#3b82f6" />}
      </div>
    );
  };

  // Helper for metric comparison row
  const MetricRow = ({ label, field, suffix = '' }) => {
    if (!selectedCompany) return null;
    const value = selectedCompany.data[field];
    const median = selectedCompany.medians?.[field];
    
    const hasValue = value !== null && value !== undefined;
    const hasMedian = median !== null && median !== undefined;
    const isExpanded = expandedMetric === field;

    return (
      <div className="border-b border-slate-100 last:border-0">
          <div 
            className={`flex justify-between items-center py-2 px-2 rounded-lg transition-colors cursor-pointer ${isExpanded ? 'bg-slate-50' : 'hover:bg-slate-50/50'}`}
            onClick={() => handleMetricClick(field)}
          >
            <div className="flex items-center gap-2">
                <span className="text-slate-500 text-sm">{label}</span>
                {isExpanded ? <ChevronUp size={14} className="text-slate-400"/> : <ChevronDown size={14} className="text-slate-300"/>}
            </div>
            <div className="text-right">
              <div className="font-mono font-bold text-slate-800">
                {hasValue ? value?.toFixed(2) + suffix : '-'}
              </div>
              {hasMedian && (
                <div className="text-xs text-slate-400">
                  Med: {median?.toFixed(2)}{suffix}
                </div>
              )}
            </div>
          </div>
          {isExpanded && <MetricChart field={field} />}
      </div>
    );
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      {/* Search Input */}
      <div className="max-w-2xl mx-auto">
        <form onSubmit={handleSearch} className="relative">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by Name, Symbol or ISIN..."
            className="w-full px-6 py-4 pl-14 rounded-2xl border-none bg-white/60 backdrop-blur-xl shadow-lg focus:ring-2 focus:ring-blue-400 focus:outline-none text-lg text-slate-800 placeholder-slate-400 transition-all"
          />
          <Search className="absolute left-5 top-1/2 -translate-y-1/2 text-slate-400" size={24} />
          <button 
            type="submit"
            disabled={loading}
            className="absolute right-3 top-1/2 -translate-y-1/2 px-4 py-2 bg-blue-600 text-white rounded-xl font-medium hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? 'Searching...' : 'Search'}
          </button>
        </form>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 min-h-[500px]">
        {/* Results List */}
        <div className={`${compareOpen && compareList.length > 0 ? 'lg:col-span-3' : 'lg:col-span-4'} bg-white/40 backdrop-blur-xl rounded-[32px] border border-white/60 shadow-xl overflow-hidden flex flex-col`}>
          <div className="p-6 border-b border-white/40">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-slate-700">Results</h2>
              {compareList.length > 0 && (
                <button
                  onClick={() => setCompareOpen(v => !v)}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-semibold rounded-full hover:bg-blue-700 transition-colors"
                >
                  <Columns size={13} />
                  对比 ({compareList.length})
                </button>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1">Sorted by Market Cap (High to Low)</p>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-2 no-scrollbar">
            {results.length === 0 && !loading && (
              <div className="text-center py-10 text-slate-400">
                Start searching to see results
              </div>
            )}
            {results.map((item) => {
              const inCompare = compareList.some(c => c.isin === item.ISIN);
              return (
                <div
                  key={item.ISIN}
                  className={`flex items-start gap-2 p-4 rounded-xl transition-all cursor-pointer ${
                    selectedCompany?.data?.ISIN === item.ISIN
                      ? 'bg-white shadow-md ring-1 ring-blue-400'
                      : 'hover:bg-white/50'
                  }`}
                  onClick={() => handleSelectCompany(item.ISIN)}
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-bold text-slate-800 truncate">{item.Name}</div>
                    <div className="flex flex-wrap gap-2 mt-2">
                      <span className="text-xs font-mono text-blue-600 bg-blue-50 px-2 py-0.5 rounded border border-blue-100">{item.Symbol}</span>
                      <span className="text-xs text-slate-600 bg-slate-100 px-2 py-0.5 rounded border border-slate-200">{item['Exchange Country Name'] || item['Exchange Country Region']}</span>
                    </div>
                    <div className="text-xs text-slate-400 mt-1 truncate">{item.Supersector}</div>
                  </div>
                  <button
                    onClick={(e) => toggleCompare(item, e)}
                    title={inCompare ? '移出对比' : (compareList.length >= 4 ? '最多对比4个' : '添加到对比')}
                    className={`flex-shrink-0 p-1.5 rounded-lg transition-colors mt-0.5 ${
                      inCompare
                        ? 'bg-blue-100 text-blue-600 hover:bg-red-100 hover:text-red-500'
                        : compareList.length >= 4
                          ? 'bg-slate-50 text-slate-300 cursor-not-allowed'
                          : 'bg-slate-100 text-slate-400 hover:bg-blue-100 hover:text-blue-600'
                    }`}
                  >
                    {inCompare ? <Minus size={14} /> : <Plus size={14} />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>

        {/* Company Details */}
        <div className={`${compareOpen && compareList.length > 0 ? 'lg:col-span-4' : 'lg:col-span-8'} bg-white/60 backdrop-blur-xl rounded-[32px] border border-white/60 shadow-xl p-8 flex flex-col relative overflow-hidden`}>
          {detailsLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
            </div>
          ) : selectedCompany ? (
            <div className="flex-1 overflow-y-auto no-scrollbar">
              {/* Header */}
              <div className="flex justify-between items-start mb-6">
                <div>
                  <h2 className="text-3xl font-bold text-slate-800">{selectedCompany.data.Name}</h2>
                  <div className="flex flex-wrap gap-3 mt-3">
                     <span className="px-3 py-1 bg-slate-100 rounded-lg text-slate-600 font-medium text-sm">
                       {selectedCompany.data.ISIN}
                     </span>
                     <span className="px-3 py-1 bg-blue-100 rounded-lg text-blue-600 font-medium text-sm">
                       {selectedCompany.data.Symbol}
                     </span>
                     <span className="px-3 py-1 bg-purple-100 rounded-lg text-purple-600 font-medium text-sm flex items-center gap-1">
                       <Activity size={14} />
                       {selectedCompany.data['Supersector']}
                     </span>
                     <span className="px-3 py-1 bg-emerald-100 rounded-lg text-emerald-600 font-medium text-sm flex items-center gap-1">
                       <Award size={14} />
                       {selectedCompany.data['Exchange Country Name'] || selectedCompany.data['Exchange Country Region']}
                     </span>
                  </div>
                </div>
                
                <button
                  onClick={copyToClipboard}
                  className={`flex items-center gap-2 px-6 py-3 rounded-xl font-bold transition-all shadow-lg ${
                    copied 
                      ? 'bg-green-500 text-white scale-105' 
                      : 'bg-slate-800 text-white hover:bg-slate-700 hover:scale-105'
                  }`}
                >
                  {copied ? <Check size={20} /> : <Copy size={20} />}
                  {copied ? '已复制数据' : '复制数据字典'}
                </button>
              </div>

              {/* 历史区间选择 */}
              <div className="flex flex-wrap gap-2 items-center mb-4">
                <span className="text-xs text-slate-500">Range:</span>
                {rangeOptions.map((opt) => (
                  <button
                    key={opt.key}
                    onClick={() => setRange(opt.key)}
                    className={`px-3 py-1 rounded-full text-xs font-semibold border ${
                      range === opt.key
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300'
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>

              {/* Score ML Badge */}
              {selectedCompany.data['Score ML'] !== undefined && (
                 <div className="mb-8">
                     <div 
                         className="p-4 bg-gradient-to-r from-indigo-500 to-purple-600 rounded-2xl text-white flex items-center justify-between shadow-lg shadow-indigo-500/20 cursor-pointer hover:shadow-xl transition-all"
                         onClick={() => handleMetricClick('Score ML')}
                     >
                        <div className="flex items-center gap-3">
                           <div className="p-2 bg-white/20 rounded-lg backdrop-blur-sm">
                             <Zap size={24} className="text-yellow-300" />
                           </div>
                           <div>
                             <div className="text-sm font-medium text-indigo-100 flex items-center gap-2">
                                 Machine Learning Score
                                 {expandedMetric === 'Score ML' ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                             </div>
                             <div className="text-sm opacity-80">AI Model Confidence</div>
                           </div>
                        </div>
                        <div className="text-4xl font-bold tracking-tight">
                           {selectedCompany.data['Score ML'].toFixed(1)}
                           <span className="text-lg opacity-60 font-normal ml-1">/ 10</span>
                        </div>
                     </div>
                     {expandedMetric === 'Score ML' && (
                         <div className="mt-2">
                             <MetricChart field="Score ML" color="#8b5cf6" />
                         </div>
                     )}
                 </div>
              )}

              {/* Data Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Column 1: Valuation & Growth */}
                <div className="space-y-6">
                  {/* Valuation Card */}
                  <div className="bg-white/50 rounded-2xl p-5 border border-white/50">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-slate-700 mb-4">
                      <DollarSign className="text-emerald-500" size={20} />
                      Valuation <span className="text-xs font-normal text-slate-400 ml-auto">vs Sector Median</span>
                    </h3>
                    <div className="space-y-1">
                      <MetricRow label="PE (NTM)" field="PE NTM" />
                      <MetricRow label="PE (LTM)" field="PE LTM" />
                      <MetricRow label="EV/EBITDA (NTM)" field="EV To EBITDA NTM" />
                      <MetricRow label="PB (LTM)" field="PB LTM" />
                      <MetricRow label="Div Yield (NTM)" field="DVD Yield NTM" suffix="%" />
                    </div>
                  </div>

                  {/* Growth Card */}
                  <div className="bg-white/50 rounded-2xl p-5 border border-white/50">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-slate-700 mb-4">
                      <TrendingUp className="text-blue-500" size={20} />
                      Growth <span className="text-xs font-normal text-slate-400 ml-auto">vs Sector Median</span>
                    </h3>
                    <div className="space-y-1">
                      <MetricRow label="EPS Growth (NTM)" field="EPS Growth NTM" suffix="%" />
                      <MetricRow label="Sales Growth (NTM)" field="Sales Growth NTM" suffix="%" />
                      <MetricRow label="Div Growth (NTM)" field="DPS 1Y Growth NTM" suffix="%" />
                      <MetricRow label="Gross Inc Growth (NTM)" field="Gross Income Growth NTM" suffix="%" />
                    </div>
                  </div>
                </div>

                {/* Column 2: Factor Scores & Quality */}
                <div className="space-y-6">
                   {/* Factor Scores */}
                   <div className="bg-white/50 rounded-2xl p-5 border border-white/50">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-slate-700 mb-4">
                      <Activity className="text-purple-500" size={20} />
                      Factor Scores (0-10)
                    </h3>
                    <div className="space-y-4">
                      <ScoreBar label="Value" field="Value Score (Histo + NTM)" value={selectedCompany.data['Value Score (Histo + NTM)']} />
                      <ScoreBar label="Quality" field="Quality Score (Histo + NTM)" value={selectedCompany.data['Quality Score (Histo + NTM)']} />
                      <ScoreBar label="Growth" field="Growth Score (Histo + NTM)" value={selectedCompany.data['Growth Score (Histo + NTM)']} />
                      <ScoreBar label="Momentum" field="Momentum Score (Histo + FY1)" value={selectedCompany.data['Momentum Score (Histo + FY1)']} />
                      <ScoreBar label="Dividend" field="Dividend Score (Histo + NTM)" value={selectedCompany.data['Dividend Score (Histo + NTM)']} />
                      <ScoreBar label="Low Vol" field="LowVol Score (Histo + FY1)" value={selectedCompany.data['LowVol Score (Histo + FY1)']} />
                    </div>
                  </div>

                  {/* Profitability & Other */}
                  <div className="bg-white/50 rounded-2xl p-5 border border-white/50">
                    <h3 className="flex items-center gap-2 text-lg font-bold text-slate-700 mb-4">
                      <PieChart className="text-orange-500" size={20} />
                      Profitability & Size <span className="text-xs font-normal text-slate-400 ml-auto">vs Sector Median</span>
                    </h3>
                    <div className="space-y-1">
                       <MetricRow label="ROE (FY0)" field="ROE avg FY0" suffix="%" />
                       <MetricRow label="Oper Margin" field="Oper Margin" suffix="%" />
                       <MetricRow label="Price Momentum (12M)" field="PCT MOM 12M1M" />
                       <MetricRow label="Market Cap (Log)" field="Log Market Value" />
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ) : (
             <div className="flex-1 flex flex-col items-center justify-center text-slate-400">
               <PieChart size={64} className="mb-4 opacity-50" />
               <p className="text-lg font-medium">Select a company to view details</p>
             </div>
          )}
        </div>

        {/* 对比面板：作为第三列嵌入 grid */}
        {compareOpen && compareList.length > 0 && (
        <div className="lg:col-span-5 bg-white/60 backdrop-blur-xl rounded-[32px] border border-white/60 shadow-xl p-6 space-y-5 overflow-y-auto animate-in fade-in duration-300">

          {/* 标题栏 */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className="flex items-center gap-3 flex-wrap">
              <h3 className="text-lg font-bold text-slate-700 flex items-center gap-2">
                <Columns size={18} className="text-blue-600" />
                公司对比
              </h3>
              {compareList.map((c, i) => (
                <span key={c.isin} className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-sm font-medium ${COMPARE_COLORS[i].badge}`}>
                  {c.name}
                  <button onClick={() => { setCompareList(prev => prev.filter(x => x.isin !== c.isin)); historyFetchedRef.current.delete(c.isin); }}>
                    <X size={12} />
                  </button>
                </span>
              ))}
            </div>
            <div className="flex items-center gap-2">
              <button
                onClick={() => { setCompareList([]); setCompareOpen(false); historyFetchedRef.current.clear(); }}
                className="text-xs text-slate-400 hover:text-red-500 px-2 py-1 rounded hover:bg-red-50 transition-colors"
              >
                清空
              </button>
              <button onClick={() => setCompareOpen(false)} className="text-slate-400 hover:text-slate-600 p-1 rounded hover:bg-slate-100">
                <X size={16} />
              </button>
            </div>
          </div>

          {/* 股价表现（100 起点价格指数） */}
          <div>
            <h4 className="text-sm font-semibold text-slate-500 mb-3">📈 股价表现（起始 = 100）</h4>
            {returnsChartData.length === 0 ? (
              <div className="h-16 flex items-center justify-center text-slate-400 text-sm">
                {compareList.some(c => c.returnsData === null) ? (
                  <span className="flex items-center gap-2"><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-slate-400" /> 加载中...</span>
                ) : '暂无股价回报数据'}
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <LineChart data={returnsChartData}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis
                    dataKey="Date"
                    tick={{ fontSize: 10, fill: '#94a3b8' }}
                    axisLine={false}
                    tickLine={false}
                    minTickGap={['1M','3M','YTD','6M','1Y'].includes(range) ? 45 : 40}
                    tickFormatter={v => {
                      if (['1M','3M','YTD','6M','1Y'].includes(range)) {
                        const d = new Date(v);
                        return d.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
                      }
                      return v.slice(0, 4);
                    }}
                  />
                  <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={38} tickFormatter={v => v.toFixed(0)} />
                  <Tooltip
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                    formatter={(v, name) => {
                      const c = compareList.find(x => x.isin === name);
                      return [v?.toFixed(2), c?.name || name];
                    }}
                  />
                  <Legend formatter={name => { const c = compareList.find(x => x.isin === name); return c?.name || name; }} wrapperStyle={{ fontSize: '12px' }} />
                  {compareList.map((c, i) => (
                    <Line key={c.isin} type="monotone" dataKey={c.isin} name={c.isin}
                      stroke={COMPARE_COLORS[i].stroke} strokeWidth={2} dot={false}
                      activeDot={{ r: 4 }} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>

          {/* 历史指标对比 */}
          <div>
            <div className="flex items-center gap-3 mb-3 flex-wrap">
              <h4 className="text-sm font-semibold text-slate-500">📊 历史指标对比</h4>
              {HISTORY_METRICS.map(m => (
                <button
                  key={m.field}
                  onClick={() => setCompareMetric(compareMetric === m.field ? null : m.field)}
                  className={`px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                    compareMetric === m.field
                      ? 'bg-blue-600 text-white border-blue-600'
                      : 'bg-white text-slate-600 border-slate-200 hover:border-blue-300'
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            {compareMetric && (
              historyChartData.length === 0 ? (
                <div className="h-16 flex items-center justify-center text-slate-400 text-sm">
                  {compareList.some(c => !c.historyData) ? (
                    <span className="flex items-center gap-2"><div className="animate-spin rounded-full h-4 w-4 border-b-2 border-slate-400" /> 加载中...</span>
                  ) : '暂无历史数据'}
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={200}>
                  <LineChart data={historyChartData}>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                    <XAxis dataKey="Date" tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} tickFormatter={v => v.slice(0, 4)} minTickGap={40} />
                    <YAxis tick={{ fontSize: 10, fill: '#94a3b8' }} axisLine={false} tickLine={false} width={35} />
                    <Tooltip
                      contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                      formatter={(v, name) => {
                        const c = compareList.find(x => x.isin === name);
                        return [v?.toFixed(2), c?.name || name];
                      }}
                    />
                    <Legend formatter={name => { const c = compareList.find(x => x.isin === name); return c?.name || name; }} wrapperStyle={{ fontSize: '12px' }} />
                    {compareList.map((c, i) => (
                      <Line key={c.isin} type="monotone" dataKey={c.isin} name={c.isin}
                        stroke={COMPARE_COLORS[i].stroke} strokeWidth={2} dot={false}
                        activeDot={{ r: 4 }} connectNulls />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )
            )}
          </div>

          {/* 因子雷达图 + 关键指标表（纵向堆叠，适配列布局） */}
          <div className="space-y-5">
            {/* 因子得分雷达图（修复 margin 防止 legend 与轴标签重叠） */}
            <div>
              <h4 className="text-sm font-semibold text-slate-500 mb-1">Factor Scores (0-10)</h4>
              <ResponsiveContainer width="100%" height={290}>
                <RadarChart
                  margin={{ top: 10, right: 30, bottom: 10, left: 30 }}
                  data={[
                    { subject: 'Value',    ...Object.fromEntries(compareList.map(c => [c.isin, c.data['Value Score (Histo + NTM)'] || 0])) },
                    { subject: 'Quality',  ...Object.fromEntries(compareList.map(c => [c.isin, c.data['Quality Score (Histo + NTM)'] || 0])) },
                    { subject: 'Growth',   ...Object.fromEntries(compareList.map(c => [c.isin, c.data['Growth Score (Histo + NTM)'] || 0])) },
                    { subject: 'Momentum', ...Object.fromEntries(compareList.map(c => [c.isin, c.data['Momentum Score (Histo + FY1)'] || 0])) },
                    { subject: 'Dividend', ...Object.fromEntries(compareList.map(c => [c.isin, c.data['Dividend Score (Histo + NTM)'] || 0])) },
                    { subject: 'LowVol',   ...Object.fromEntries(compareList.map(c => [c.isin, c.data['LowVol Score (Histo + FY1)'] || 0])) },
                  ]}
                >
                  <PolarGrid stroke="#e2e8f0" />
                  <PolarAngleAxis dataKey="subject" tick={{ fontSize: 11, fill: '#64748b' }} />
                  <PolarRadiusAxis domain={[0, 10]} tick={false} axisLine={false} />
                  {compareList.map((c, i) => (
                    <Radar key={c.isin} name={c.isin} dataKey={c.isin}
                      stroke={COMPARE_COLORS[i].stroke} fill={COMPARE_COLORS[i].fill}
                      fillOpacity={0.15} strokeWidth={2} />
                  ))}
                  <Legend
                    formatter={name => { const c = compareList.find(x => x.isin === name); return c?.name || name; }}
                    wrapperStyle={{ fontSize: '12px', paddingTop: '8px' }}
                  />
                  <Tooltip
                    formatter={(v, name) => { const c = compareList.find(x => x.isin === name); return [v?.toFixed(2), c?.name || name]; }}
                    contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                  />
                </RadarChart>
              </ResponsiveContainer>
            </div>

            {/* 关键指标对比表 */}
            <div>
              <h4 className="text-sm font-semibold text-slate-500 mb-3">Key Metrics</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr>
                      <th className="text-left py-2 pr-4 text-slate-500 font-medium">指标</th>
                      {compareList.map((c, i) => (
                        <th key={c.isin} className={`text-center py-2 px-3 font-bold ${COMPARE_COLORS[i].text}`}>{c.name}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {COMPARE_METRICS.map(m => (
                      <tr key={m.field} className="border-t border-slate-100">
                        <td className="py-2 pr-4 text-slate-500 whitespace-nowrap">{m.label}</td>
                        {compareList.map(c => {
                          const val = c.data[m.field];
                          return (
                            <td key={c.isin} className="py-2 px-3 text-center font-mono font-bold text-slate-800">
                              {val !== null && val !== undefined ? Number(val).toFixed(2) + (m.suffix || '') : '-'}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
        )}
      </div>
    </div>
  );
};

export default SearchPage;

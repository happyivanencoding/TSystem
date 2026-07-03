import React, { useState, useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom';
import { Search, BarChart3, LayoutGrid, Calendar } from 'lucide-react';
import SearchPage from './pages/SearchPage';
import MarketPage from './pages/MarketPage';

const NavLink = ({ to, icon: Icon, children }) => {
  const location = useLocation();
  const isActive = location.pathname === to;
  
  return (
    <Link 
      to={to} 
      className={`flex items-center gap-2 px-4 py-2 rounded-full transition-all duration-300 ${
        isActive 
          ? 'bg-white shadow-md text-blue-600 font-medium' 
          : 'text-slate-500 hover:bg-white/50 hover:text-slate-700'
      }`}
    >
      <Icon size={18} />
      <span>{children}</span>
    </Link>
  );
};

const App = () => {
  // --- 全局状态：数据日期 ---
  const [dataDate, setDataDate] = useState(null);

  // --- 持久化搜索页状态 ---
  const searchStateRef = useRef({
    query: '',
    results: [],
    selectedCompany: null,
    historyData: null,
    expandedMetric: null,
    range: '3Y',
    // 对比功能状态
    compareList: [],     // [{isin, name, data, medians}]
    compareOpen: false,
  });

  useEffect(() => {
    fetch('/api/data-date')
      .then(res => res.ok ? res.json() : null)
      .then(data => {
        if (data?.date) setDataDate(data.date);
      })
      .catch(() => {});
  }, []);

  return (
    <Router>
      <div className="min-h-screen p-4 md:p-8 font-sans text-slate-800">
        <header className="mb-8 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-blue-600 p-2 rounded-xl shadow-lg shadow-blue-600/20">
              <LayoutGrid className="text-white" size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-700 to-indigo-600">
                Company Analysis
              </h1>
              {dataDate && (
                <div className="flex items-center gap-1.5 mt-0.5">
                  <Calendar size={12} className="text-slate-400" />
                  <span className="text-xs text-slate-400 font-medium">
                    Data as of {dataDate}
                  </span>
                </div>
              )}
            </div>
          </div>
          
          <nav className="flex items-center gap-2 bg-white/30 p-1.5 rounded-full backdrop-blur-md border border-white/40">
            <NavLink to="/" icon={Search}>公司搜索</NavLink>
            <NavLink to="/market" icon={BarChart3}>市场概览</NavLink>
          </nav>
        </header>

        <main>
          <Routes>
            <Route path="/" element={<SearchPage stateRef={searchStateRef} dataDate={dataDate} />} />
            <Route path="/market" element={<MarketPage />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
};

export default App;

import React, { useState, useMemo, useEffect } from 'react';
import { 
  Info, TrendingUp, Zap, Globe, Activity, Sparkles, Loader2, 
  X, Pin, BarChart3, PieChart, ArrowRightLeft, MousePointerClick 
} from 'lucide-react';
import { 
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, 
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, Cell
} from 'recharts';

// --- DATA SOURCE ---
const SECTOR_DATA = {
  "North America": [
    { name: "Auto & Parts", pe: 11.80, peg: 0.34, pegy: 0.34 },
    { name: "Banks", pe: 9.79, peg: 2.62, pegy: 1.05 },
    { name: "Basic Resources", pe: 14.05, peg: 5, pegy: 2.68 },
    { name: "Chemicals", pe: 15.41, peg: 0.81, pegy: 0.81 },
    { name: "Construction", pe: 21.00, peg: 0.92, pegy: 0.91 },
    { name: "Energy", pe: 13.66, peg: 0.79, pegy: 0.71 },
    { name: "Financial Services", pe: 13.29, peg: 0.52, pegy: 0.40 },
    { name: "Food, Beverage & Tobacco", pe: 15.62, peg: 5.00, pegy: 1.58 },
    { name: "Health Care", pe: 18.57, peg: 2.48, pegy: 2.13 },
    { name: "Industrial Goods & Services", pe: 18.74, peg: 3.39, pegy: 1.25 },
    { name: "Insurance", pe: 10.46, peg: 0.90, pegy: 0.84 },
    { name: "Media", pe: 16.50, peg: 1.84, pegy: 0.84 },
    { name: "Personal & Household Goods", pe: 13.85, peg: 0.39, pegy: 0.39 },
    { name: "Real Estate", pe: 25.75, peg: 1.63, pegy: 1.40 },
    { name: "Retail", pe: 15.95, peg: 1.01, pegy: 0.77 },
    { name: "Technology", pe: 21.17, peg: 1.18, pegy: 0.87 },
    { name: "Telecommunications", pe: 15.42, peg: 1.53, pegy: 1.53 },
    { name: "Travel & Leisure", pe: 16.58, peg: 1.12, pegy: 0.85 },
    { name: "Utilities", pe: 18.57, peg: 0.60, pegy: 0.52 }
  ],
  "West Europe": [
    { name: "Auto & Parts", pe: 9.71, peg: 0.47, pegy: 0.46 },
    { name: "Banks", pe: 10.24, peg: 1.80, pegy: 0.87 },
    { name: "Basic Resources", pe: 11.99, peg: 1.81, pegy: 0.93 },
    { name: "Chemicals", pe: 14.99, peg: 3.45, pegy: 1.44 },
    { name: "Construction", pe: 13.70, peg: 2.23, pegy: 1.55 },
    { name: "Energy", pe: 9.48, peg: 1.24, pegy: 0.96 },
    { name: "Financial Services", pe: 11.97, peg: 0.61, pegy: 0.38 },
    { name: "Food, Beverage & Tobacco", pe: 13.81, peg: 2.18, pegy: 1.41 },
    { name: "Health Care", pe: 18.06, peg: 5.00, pegy: 4.01 },
    { name: "Industrial Goods & Services", pe: 16.58, peg: 5.00, pegy: 2.56 },
    { name: "Insurance", pe: 10.49, peg: 0.59, pegy: 0.41 },
    { name: "Media", pe: 11.43, peg: 2.63, pegy: 1.08 },
    { name: "Personal & Household Goods", pe: 15.05, peg: 3.07, pegy: 2.09 },
    { name: "Real Estate", pe: 13.98, peg: 0.99, pegy: 0.85 },
    { name: "Retail", pe: 12.13, peg: 0.91, pegy: 0.78 },
    { name: "Technology", pe: 19.94, peg: 2.85, pegy: 1.22 },
    { name: "Telecommunications", pe: 14.78, peg: 0.79, pegy: 0.60 },
    { name: "Travel & Leisure", pe: 10.96, peg: 0.84, pegy: 0.62 },
    { name: "Utilities", pe: 13.91, peg: 1.92, pegy: 1.27 }
  ]
};

// --- GEMINI API HELPERS ---
const callGemini = async (prompt) => {
  const apiKey = ""; // Injected by runtime
  const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-09-2025:generateContent?key=${apiKey}`;

  const payload = {
    contents: [{ parts: [{ text: prompt }] }]
  };

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!response.ok) throw new Error(`API Error: ${response.status}`);
    const data = await response.json();
    return data.candidates?.[0]?.content?.parts?.[0]?.text || "无法生成分析，请稍后再试。";
  } catch (error) {
    console.error("Gemini API Call Failed:", error);
    return "AI 服务暂时不可用，请检查网络连接或稍后再试。";
  }
};

// --- INSIGHT LOGIC ---
const getInsight = (sector, metric, value, region) => {
  const s = sector.toLowerCase();
  const isNA = region === "North America";
  
  if (s.includes("technology")) {
    if (metric === "pe") return isNA ? "AI 2.0 阶段：市场正从硬件基建转向软件应用定价，高 PE 反映了对 2026 年企业级 Agent 爆发的抢跑。" : "缺乏超大规模云厂商，主要由半导体设备驱动，受出口管制影响，估值较美股折价。";
    if (metric === "peg") return value < 1.2 ? "PEG 合理，盈利增速支撑高估值，AI 生产力提升正在兑现。" : "增长预期可能过于激进，需警惕 IT 支出削减风险。";
  }
  if (s.includes("energy")) {
    if (isNA) return "去监管预期增加供给，压制油价上限。低估值反映了长期油价中枢下移定价。";
    return "现金牛。放缓绿色转型后自由现金流改善，依靠回购分红维持回报。";
  }
  if (s.includes("real estate")) {
    return isNA ? "K型分化：写字楼深陷泥潭，但 AI 数据中心需求井喷支撑整体估值。" : "对利率最敏感。ECB 降息节奏快于美联储，提供估值修复支撑。";
  }
  if (s.includes("auto")) {
    return "至暗时刻？电动化放缓叠加关税壁垒。低 PEG 暗示市场预期未来增长停滞，甚至包含破产清算预期。";
  }
  
  // Generic Logic
  if (metric === 'pe' && value > 20) return "高成长溢价，但容错率极低。";
  if (metric === 'pe' && value < 10) return "深度价值区间，需警惕价值陷阱。";
  
  return "数据反映了该行业在当前宏观环境下的风险收益特征。";
};

// --- COMPONENTS ---
const MetricCard = ({ title, value, isActive, onClick, icon: Icon, colorClass }) => (
  <button
    onClick={onClick}
    className={`relative overflow-hidden rounded-2xl p-4 text-left transition-all duration-300 w-full ${
      isActive 
        ? 'bg-white shadow-lg ring-2 ring-blue-400/50 scale-[1.02]' 
        : 'bg-white/40 hover:bg-white/60 hover:shadow-md'
    }`}
  >
    <div className="flex items-center justify-between mb-2">
      <p className="text-xs font-bold uppercase tracking-wider text-slate-500">{title}</p>
      <Icon size={16} className={isActive ? colorClass : "text-slate-400"} />
    </div>
    <div className="flex items-baseline gap-2">
      <span className={`text-xl font-bold tracking-tight ${isActive ? 'text-slate-800' : 'text-slate-600'}`}>
         {value}
      </span>
    </div>
  </button>
);

const AIModal = ({ isOpen, onClose, title, content, isLoading }) => {
  if (!isOpen) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-slate-900/20 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl bg-white/90 backdrop-blur-xl border border-white/60 rounded-[32px] shadow-2xl flex flex-col max-h-[85vh] animate-in fade-in zoom-in-95 duration-300">
        <div className="p-6 border-b border-white/20 flex items-center justify-between bg-gradient-to-r from-blue-50 to-indigo-50 rounded-t-[32px]">
          <div className="flex items-center gap-2 text-blue-800">
            <Sparkles className="w-5 h-5 text-blue-600" />
            <h3 className="text-xl font-bold">{title}</h3>
          </div>
          <button onClick={onClose} className="p-2 rounded-full hover:bg-black/5"><X size={20} /></button>
        </div>
        <div className="p-8 overflow-y-auto">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-12 space-y-4">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
              <p className="text-slate-500 font-medium animate-pulse">Gemini 正在分析跨市场数据...</p>
            </div>
          ) : (
            <div className="prose prose-slate prose-lg max-w-none">
              {content.split('\n').map((p, idx) => <p key={idx} className="text-slate-700 leading-relaxed mb-4">{p}</p>)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

// --- MAIN APP ---
const App = () => {
  const [activeMetric, setActiveMetric] = useState("pe");
  const [selectedSectorName, setSelectedSectorName] = useState(null); // Just the name string
  
  // AI States
  const [aiModalOpen, setAiModalOpen] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiTitle, setAiTitle] = useState("");
  const [aiContent, setAiContent] = useState("");

  // Sort Logic: Default sort by North America's value descending
  const sortedSectors = useMemo(() => {
    const naData = SECTOR_DATA["North America"];
    const euData = SECTOR_DATA["West Europe"];
    
    // Create combined objects for easier mapping
    const combined = naData.map(naItem => {
      const euItem = euData.find(e => e.name === naItem.name);
      return {
        name: naItem.name,
        na: naItem,
        eu: euItem
      };
    });

    return combined.sort((a, b) => b.na[activeMetric] - a.na[activeMetric]);
  }, [activeMetric]);

  // Find the selected full objects for the detail panel
  const selectedDetail = useMemo(() => {
    if (!selectedSectorName) return null;
    return sortedSectors.find(s => s.name === selectedSectorName);
  }, [selectedSectorName, sortedSectors]);

  const handleSectorClick = (name) => setSelectedSectorName(name);

  // --- AI HANDLERS ---
  const handleDeepDive = async () => {
    if (!selectedDetail) return;
    
    setAiTitle(`AI 跨大西洋对比: ${selectedDetail.name}`);
    setAiLoading(true);
    setAiModalOpen(true);
    setAiContent("");

    const prompt = `
      角色：资深全球宏观策略师。
      任务：对比 ${selectedDetail.name} 行业在北美与西欧的估值差异。
      数据：
      - 北美 (NA): PE=${selectedDetail.na.pe}, PEG=${selectedDetail.na.peg}
      - 西欧 (EU): PE=${selectedDetail.eu.pe}, PEG=${selectedDetail.eu.peg}
      
      请提供一份中文分析（约 250 字）：
      1. **价差分析**：为什么两个市场存在这样的估值溢价或折价？（考虑科技权重、宏观经济、货币政策）。
      2. **套利机会**：如果是投资者，现在应该买入更便宜的欧洲资产，还是坚持拥抱高增长的美国资产？
      3. **风险提示**：2026 年该行业的最大宏观风险。
    `;

    const result = await callGemini(prompt);
    setAiContent(result);
    setAiLoading(false);
  };

  // --- CHART DATA PREP ---
  const radarData = useMemo(() => {
    if (!selectedDetail) return [];
    // Normalize logic roughly for visualization
    return [
      { subject: 'P/E Ratio', A: selectedDetail.na.pe, B: selectedDetail.eu.pe, fullMark: 30 },
      { subject: 'PEG Ratio (x10)', A: selectedDetail.na.peg * 10, B: selectedDetail.eu.peg * 10, fullMark: 50 }, // Scale PEG for visibility
      { subject: 'PEGY Ratio (x10)', A: selectedDetail.na.pegy * 10, B: selectedDetail.eu.pegy * 10, fullMark: 50 },
    ];
  }, [selectedDetail]);

  const comparisonData = useMemo(() => {
    // Top 5 sectors by NA PE
    return sortedSectors.slice(0, 8).map(item => ({
      name: item.name,
      NA: item.na[activeMetric],
      EU: item.eu[activeMetric]
    }));
  }, [sortedSectors, activeMetric]);

  return (
    <div className="min-h-screen w-full bg-[#f4f7fb] text-slate-800 font-sans selection:bg-blue-200">
      <AIModal 
        isOpen={aiModalOpen} 
        onClose={() => setAiModalOpen(false)} 
        title={aiTitle} 
        content={aiContent} 
        isLoading={aiLoading} 
      />

      <div className="max-w-[1400px] mx-auto px-4 py-6 sm:px-6 lg:px-8">
        
        {/* HEADER */}
        <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Activity className="text-blue-600" />
              <h1 className="text-3xl font-bold tracking-tight text-slate-900">Global Valuation Monitor</h1>
            </div>
            <p className="text-slate-500 text-sm">
              Consolidated North America & West Europe Data • NTM Consensus (2026)
            </p>
          </div>
          
          {/* METRIC TOGGLES */}
          <div className="flex gap-3 bg-white p-1.5 rounded-2xl shadow-sm border border-slate-200">
            <MetricCard 
              title="P/E" 
              value="Ratio" 
              isActive={activeMetric === 'pe'} 
              onClick={() => setActiveMetric('pe')}
              icon={TrendingUp}
              colorClass="text-blue-600"
            />
             <MetricCard 
              title="PEG" 
              value="Growth" 
              isActive={activeMetric === 'peg'} 
              onClick={() => setActiveMetric('peg')}
              icon={Zap}
              colorClass="text-emerald-600"
            />
             <MetricCard 
              title="PEGY" 
              value="Yield" 
              isActive={activeMetric === 'pegy'} 
              onClick={() => setActiveMetric('pegy')}
              icon={Globe}
              colorClass="text-amber-600"
            />
          </div>
        </header>

        {/* MAIN CONTENT GRID */}
        <div className="grid grid-cols-12 gap-6">
          
          {/* LEFT: DATA TABLES (Comparison) - Spans 8 cols */}
          <div className="col-span-12 lg:col-span-8 space-y-6">
            <div className="bg-white rounded-3xl shadow-sm border border-slate-200 overflow-hidden">
              <div className="p-5 border-b border-slate-100 flex justify-between items-center bg-slate-50/50">
                <h3 className="font-semibold text-slate-700 flex items-center gap-2">
                  <ArrowRightLeft size={18} />
                  跨市场行业对比
                </h3>
                <span className="text-xs font-medium text-slate-400 bg-white px-2 py-1 rounded border border-slate-200">
                  Sort by: NA {activeMetric.toUpperCase()}
                </span>
              </div>
              
              <div className="grid grid-cols-2 text-xs font-semibold text-slate-500 bg-slate-50 border-b border-slate-200">
                <div className="px-4 py-3 border-r border-slate-200 text-center text-blue-800 bg-blue-50/30">NORTH AMERICA</div>
                <div className="px-4 py-3 text-center text-indigo-800 bg-indigo-50/30">WEST EUROPE</div>
              </div>

              <div className="max-h-[600px] overflow-y-auto custom-scrollbar">
                {sortedSectors.map((item) => {
                  const isSelected = selectedSectorName === item.name;
                  return (
                    <div 
                      key={item.name}
                      onClick={() => handleSectorClick(item.name)}
                      className={`grid grid-cols-2 border-b border-slate-100 cursor-pointer transition-all duration-200 group ${
                        isSelected ? 'bg-blue-50/80 ring-1 ring-inset ring-blue-200' : 'hover:bg-slate-50'
                      }`}
                    >
                      {/* North America Side */}
                      <div className="p-3 border-r border-slate-100 flex justify-between items-center group-hover:border-slate-200">
                        <span className={`font-medium ${isSelected ? 'text-blue-900' : 'text-slate-700'}`}>{item.name}</span>
                        <div className="flex flex-col items-end">
                           <span className={`font-mono font-bold ${activeMetric === 'pe' ? 'text-blue-600' : 'text-slate-800'}`}>
                             {item.na[activeMetric].toFixed(2)}
                           </span>
                           {activeMetric === 'pe' && (
                             <span className="text-[10px] text-slate-400 mt-0.5">
                               PEG: {item.na.peg} <span className="text-slate-300 mx-0.5">|</span> PEGY: {item.na.pegy}
                             </span>
                           )}
                        </div>
                      </div>

                      {/* Europe Side */}
                      <div className="p-3 flex justify-between items-center">
                        <div className="flex flex-col items-start">
                           <span className={`font-mono font-bold ${activeMetric === 'pe' ? 'text-indigo-600' : 'text-slate-800'}`}>
                             {item.eu[activeMetric].toFixed(2)}
                           </span>
                           {activeMetric === 'pe' && (
                             <span className="text-[10px] text-slate-400 mt-0.5">
                               PEG: {item.eu.peg} <span className="text-slate-300 mx-0.5">|</span> PEGY: {item.eu.pegy}
                             </span>
                           )}
                        </div>
                        {/* Gap Visualization */}
                        <div className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-slate-100 text-slate-500">
                           Δ {(item.na[activeMetric] - item.eu[activeMetric]).toFixed(1)}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* RIGHT: INSIGHT PANEL - Spans 4 cols */}
          <div className="col-span-12 lg:col-span-4 space-y-6">
            <div className={`sticky top-6 transition-all duration-500 ${selectedSectorName ? 'opacity-100' : 'opacity-90'}`}>
              <div className="bg-white/80 backdrop-blur-xl border border-white rounded-[32px] p-6 shadow-xl shadow-blue-900/5">
                
                {selectedDetail ? (
                  <>
                    <div className="flex items-center justify-between mb-6">
                      <div>
                        <h2 className="text-xl font-bold text-slate-900">{selectedDetail.name}</h2>
                        <div className="flex gap-2 mt-1">
                          <span className="text-[10px] font-bold px-2 py-0.5 bg-blue-100 text-blue-700 rounded-full">North America</span>
                          <span className="text-[10px] font-bold px-2 py-0.5 bg-indigo-100 text-indigo-700 rounded-full">West Europe</span>
                        </div>
                      </div>
                      <div className="bg-slate-50 p-2 rounded-full border border-slate-100">
                        <BarChart3 className="text-slate-400" size={20} />
                      </div>
                    </div>

                    <div className="space-y-4 mb-6">
                      <div className="p-4 bg-gradient-to-br from-blue-50 to-white border border-blue-100 rounded-2xl">
                        <div className="flex justify-between items-end mb-1">
                          <span className="text-xs font-semibold text-blue-800">North America Valuation</span>
                          <span className="text-2xl font-light text-blue-900">{selectedDetail.na[activeMetric]}</span>
                        </div>
                        <p className="text-xs text-slate-500 leading-snug">
                          {getInsight(selectedDetail.name, activeMetric, selectedDetail.na[activeMetric], "North America")}
                        </p>
                      </div>

                      <div className="p-4 bg-gradient-to-br from-indigo-50 to-white border border-indigo-100 rounded-2xl">
                        <div className="flex justify-between items-end mb-1">
                          <span className="text-xs font-semibold text-indigo-800">Europe Valuation</span>
                          <span className="text-2xl font-light text-indigo-900">{selectedDetail.eu[activeMetric]}</span>
                        </div>
                         <p className="text-xs text-slate-500 leading-snug">
                          {getInsight(selectedDetail.name, activeMetric, selectedDetail.eu[activeMetric], "West Europe")}
                        </p>
                      </div>
                    </div>

                    <button
                      onClick={handleDeepDive}
                      className="w-full py-3 rounded-xl bg-slate-900 text-white font-medium text-sm flex items-center justify-center gap-2 hover:bg-slate-800 transition-colors shadow-lg shadow-slate-900/20"
                    >
                      <Sparkles size={16} className="text-yellow-400" />
                      AI 深度对比分析
                    </button>
                  </>
                ) : (
                   <div className="h-64 flex flex-col items-center justify-center text-center text-slate-400">
                     <MousePointerClick size={48} className="mb-4 opacity-50" />
                     <p className="font-medium">选择左侧行业</p>
                     <p className="text-xs mt-1">查看详细对比与 AI 分析</p>
                   </div>
                )}
              </div>
            </div>
          </div>

          {/* BOTTOM: VISUALIZATION SECTION - Spans Full Width */}
          <div className="col-span-12 mt-4">
            <h3 className="text-lg font-bold text-slate-800 mb-4 flex items-center gap-2">
              <PieChart size={20} className="text-slate-500" />
              可视化工坊
            </h3>
            
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              
              {/* CHART 1: RADAR (Specific Sector Shape) */}
              <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-200 h-[400px] flex flex-col">
                <div className="mb-4 flex justify-between items-start">
                  <div>
                    <h4 className="font-bold text-slate-700">估值形态对比 (Radar)</h4>
                    <p className="text-xs text-slate-400">
                      {selectedDetail ? selectedDetail.name : "请选择一个行业"} • Normalized Metrics
                    </p>
                  </div>
                </div>
                
                <div className="flex-1 min-h-0">
                  {selectedDetail ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <RadarChart cx="50%" cy="50%" outerRadius="80%" data={radarData}>
                        <PolarGrid stroke="#e2e8f0" />
                        <PolarAngleAxis dataKey="subject" tick={{ fill: '#64748b', fontSize: 12 }} />
                        <PolarRadiusAxis angle={30} domain={[0, 'fullMark']} tick={false} axisLine={false} />
                        <Radar
                          name="North America"
                          dataKey="A"
                          stroke="#2563eb"
                          fill="#3b82f6"
                          fillOpacity={0.3}
                        />
                        <Radar
                          name="Europe"
                          dataKey="B"
                          stroke="#4f46e5"
                          fill="#6366f1"
                          fillOpacity={0.3}
                        />
                        <Legend />
                        <Tooltip 
                           contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                           itemStyle={{ fontSize: '12px' }}
                        />
                      </RadarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-full flex items-center justify-center bg-slate-50 rounded-2xl border border-dashed border-slate-200">
                       <p className="text-slate-400 text-sm">点击上方列表选择行业以生成雷达图</p>
                    </div>
                  )}
                </div>
              </div>

              {/* CHART 2: BAR (Top Sectors Comparison) */}
              <div className="bg-white rounded-3xl p-6 shadow-sm border border-slate-200 h-[400px] flex flex-col">
                <div className="mb-4">
                  <h4 className="font-bold text-slate-700">热门板块溢价分析</h4>
                  <p className="text-xs text-slate-400">Top 8 Sectors by NA {activeMetric.toUpperCase()} • Direct Comparison</p>
                </div>
                
                <div className="flex-1 min-h-0">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart
                      data={comparisonData}
                      margin={{ top: 20, right: 30, left: 0, bottom: 5 }}
                    >
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                      <XAxis dataKey="name" tick={{ fontSize: 10, fill: '#64748b' }} interval={0} angle={-15} textAnchor="end" height={60} />
                      <YAxis tick={{ fontSize: 11, fill: '#64748b' }} axisLine={false} tickLine={false} />
                      <Tooltip 
                        cursor={{ fill: '#f8fafc' }}
                        contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                      />
                      <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                      <Bar dataKey="NA" name="North America" fill="#3b82f6" radius={[4, 4, 0, 0]} barSize={12} />
                      <Bar dataKey="EU" name="Europe" fill="#6366f1" radius={[4, 4, 0, 0]} barSize={12} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>

            </div>
          </div>

        </div>
      </div>
    </div>
  );
};

export default App;
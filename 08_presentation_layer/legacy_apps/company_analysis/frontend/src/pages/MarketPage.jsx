import React, { useState, useMemo } from 'react';
import { 
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, 
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip, Legend,
  CartesianGrid, Cell 
} from 'recharts';
import { Info, TrendingUp, Zap, Globe, Activity, Sparkles, Loader2, X, Pin, BarChart3, PieChart, ArrowRightLeft, MousePointerClick } from 'lucide-react';

// --- DATA SOURCE (Same as provided) ---
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

const MarketPage = () => {
  const [activeMetric, setActiveMetric] = useState("pe");
  const [selectedSectorName, setSelectedSectorName] = useState(null);
  
  const sortedSectors = useMemo(() => {
    const naData = SECTOR_DATA["North America"];
    const euData = SECTOR_DATA["West Europe"];
    
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

  const selectedDetail = useMemo(() => {
    if (!selectedSectorName) return null;
    return sortedSectors.find(s => s.name === selectedSectorName);
  }, [selectedSectorName, sortedSectors]);

  const handleSectorClick = (name) => setSelectedSectorName(name);

  return (
    <div className="space-y-6 animate-in fade-in duration-500">
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 h-[800px]">
        {/* Left Panel: Controls & Chart */}
        <div className="lg:col-span-8 flex flex-col gap-6">
          {/* Metrics Selector */}
          <div className="grid grid-cols-3 gap-4">
            <MetricCard 
              title="P/E Ratio" 
              value="Price / Earnings" 
              isActive={activeMetric === 'pe'} 
              onClick={() => setActiveMetric('pe')}
              icon={TrendingUp}
              colorClass="text-blue-500"
            />
            <MetricCard 
              title="PEG Ratio" 
              value="PE / Growth" 
              isActive={activeMetric === 'peg'} 
              onClick={() => setActiveMetric('peg')}
              icon={Zap}
              colorClass="text-amber-500"
            />
            <MetricCard 
              title="PEGY Ratio" 
              value="PE / (G + Yield)" 
              isActive={activeMetric === 'pegy'} 
              onClick={() => setActiveMetric('pegy')}
              icon={PieChart}
              colorClass="text-emerald-500"
            />
          </div>

          {/* Main Chart Card */}
          <div className="flex-1 bg-white/50 backdrop-blur-xl rounded-[32px] border border-white/60 shadow-xl p-6 relative overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h2 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
                  <Globe className="text-blue-500" />
                  Global Sector Valuation
                </h2>
                <p className="text-slate-500 text-sm mt-1">
                  Comparing North America vs. West Europe across 19 supersectors
                </p>
              </div>
            </div>

            <div className="flex-1 min-h-0">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={sortedSectors}
                  layout="vertical"
                  margin={{ top: 5, right: 30, left: 40, bottom: 5 }}
                  barGap={2}
                >
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} stroke="#cbd5e1" opacity={0.4} />
                  <XAxis type="number" hide />
                  <YAxis 
                    type="category" 
                    dataKey="name" 
                    width={180}
                    tick={{ fill: '#64748b', fontSize: 12, fontWeight: 500 }}
                    axisLine={false}
                    tickLine={false}
                  />
                  <Tooltip 
                    cursor={{ fill: '#f1f5f9', opacity: 0.5 }}
                    contentStyle={{ borderRadius: '12px', border: 'none', boxShadow: '0 10px 15px -3px rgb(0 0 0 / 0.1)' }}
                  />
                  <Bar 
                    dataKey={`na.${activeMetric}`} 
                    name="North America" 
                    fill="#3b82f6" 
                    radius={[0, 4, 4, 0]}
                    barSize={12}
                    onClick={(data) => handleSectorClick(data.name)}
                    className="cursor-pointer hover:opacity-80 transition-opacity"
                  />
                  <Bar 
                    dataKey={`eu.${activeMetric}`} 
                    name="West Europe" 
                    fill="#a855f7" 
                    radius={[0, 4, 4, 0]}
                    barSize={12}
                    onClick={(data) => handleSectorClick(data.name)}
                    className="cursor-pointer hover:opacity-80 transition-opacity"
                  />
                </BarChart>
              </ResponsiveContainer>
            </div>
            
            <div className="flex justify-center gap-6 mt-4">
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <div className="w-3 h-3 rounded-full bg-blue-500" /> North America
              </div>
              <div className="flex items-center gap-2 text-sm text-slate-600">
                <div className="w-3 h-3 rounded-full bg-purple-500" /> West Europe
              </div>
            </div>
          </div>
        </div>

        {/* Right Panel: Details */}
        <div className="lg:col-span-4 flex flex-col h-full">
           <div className={`h-full bg-white/60 backdrop-blur-xl rounded-[32px] border border-white/60 shadow-xl p-8 transition-all duration-500 ${selectedDetail ? 'opacity-100 translate-x-0' : 'opacity-50 translate-x-4'}`}>
             {selectedDetail ? (
               <div className="h-full flex flex-col">
                 <div className="mb-8">
                   <div className="inline-flex items-center justify-center p-3 bg-blue-100 rounded-2xl mb-4 text-blue-600">
                     <Activity size={24} />
                   </div>
                   <h3 className="text-3xl font-bold text-slate-800 mb-2">{selectedDetail.name}</h3>
                   <div className="h-1 w-20 bg-gradient-to-r from-blue-500 to-purple-500 rounded-full" />
                 </div>

                 <div className="space-y-6 flex-1">
                   {/* Radar Chart */}
                   <div className="h-64 relative -mx-4">
                     <ResponsiveContainer width="100%" height="100%">
                       <RadarChart cx="50%" cy="50%" outerRadius="70%" data={[
                         { subject: 'PE', A: selectedDetail.na.pe, B: selectedDetail.eu.pe, fullMark: 30 },
                         { subject: 'PEG', A: selectedDetail.na.peg * 10, B: selectedDetail.eu.peg * 10, fullMark: 50 },
                         { subject: 'PEGY', A: selectedDetail.na.pegy * 10, B: selectedDetail.eu.pegy * 10, fullMark: 50 },
                       ]}>
                         <PolarGrid stroke="#e2e8f0" />
                         <PolarAngleAxis dataKey="subject" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                         <PolarRadiusAxis angle={30} domain={[0, 30]} tick={false} axisLine={false} />
                         <Radar name="North America" dataKey="A" stroke="#3b82f6" strokeWidth={2} fill="#3b82f6" fillOpacity={0.3} />
                         <Radar name="West Europe" dataKey="B" stroke="#a855f7" strokeWidth={2} fill="#a855f7" fillOpacity={0.3} />
                         <Legend />
                       </RadarChart>
                     </ResponsiveContainer>
                   </div>

                   {/* Stats Grid */}
                   <div className="grid grid-cols-2 gap-4">
                     <div className="p-4 rounded-2xl bg-blue-50 border border-blue-100">
                       <p className="text-xs font-bold text-blue-400 uppercase mb-1">North America</p>
                       <div className="text-2xl font-bold text-slate-800">{selectedDetail.na[activeMetric].toFixed(2)}</div>
                     </div>
                     <div className="p-4 rounded-2xl bg-purple-50 border border-purple-100">
                       <p className="text-xs font-bold text-purple-400 uppercase mb-1">West Europe</p>
                       <div className="text-2xl font-bold text-slate-800">{selectedDetail.eu[activeMetric].toFixed(2)}</div>
                     </div>
                   </div>
                 </div>

                 <div className="mt-auto pt-6 text-center text-slate-400 text-sm flex items-center justify-center gap-2">
                   <MousePointerClick size={14} />
                   Select another sector to compare
                 </div>
               </div>
             ) : (
               <div className="h-full flex flex-col items-center justify-center text-center space-y-4">
                 <div className="w-20 h-20 bg-slate-100 rounded-full flex items-center justify-center text-slate-300">
                   <ArrowRightLeft size={32} />
                 </div>
                 <div>
                   <h3 className="text-xl font-bold text-slate-700">Select a Sector</h3>
                   <p className="text-slate-500 mt-2 max-w-[200px] mx-auto">Click on any bar in the chart to view detailed regional comparison</p>
                 </div>
               </div>
             )}
           </div>
        </div>
      </div>
    </div>
  );
};

export default MarketPage;



import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Dashboard from './pages/Dashboard';
import Strategy from './pages/Strategy';
import Backtest from './pages/Backtest';
import Signals from './pages/Signals';
import Positions from './pages/Positions';
import Trades from './pages/Trades';
import Settings from './pages/Settings';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="strategy" element={<Strategy />} />
        <Route path="backtest" element={<Backtest />} />
        <Route path="signals" element={<Signals />} />
        <Route path="positions" element={<Positions />} />
        <Route path="trades" element={<Trades />} />
        <Route path="settings" element={<Settings />} />
      </Route>
    </Routes>
  );
}

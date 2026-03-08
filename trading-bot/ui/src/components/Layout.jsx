import { Link, useLocation, Outlet } from 'react-router-dom';
import TopBar from './TopBar';

const nav = [
  { to: '/', label: 'Dashboard' },
  { to: '/strategy', label: 'Strategy' },
  { to: '/backtest', label: 'Backtest' },
  { to: '/signals', label: 'Signals' },
  { to: '/positions', label: 'Positions' },
  { to: '/trades', label: 'Trades' },
  { to: '/settings', label: 'Settings' },
];

export default function Layout() {
  const location = useLocation();

  return (
    <div className="flex min-h-screen bg-gray-100">
      <aside className="w-56 bg-gray-800 text-white flex flex-col fixed left-0 top-0 h-full">
        <div className="p-4 border-b border-gray-700">
          <h1 className="font-semibold text-lg">MTF Bot</h1>
        </div>
        <nav className="flex-1 p-2">
          {nav.map(({ to, label }) => (
            <Link
              key={to}
              to={to}
              className={`block px-3 py-2 rounded-md text-sm font-medium ${
                location.pathname === to
                  ? 'bg-gray-700 text-white'
                  : 'text-gray-300 hover:bg-gray-700 hover:text-white'
              }`}
            >
              {label}
            </Link>
          ))}
        </nav>
      </aside>
      <div className="flex-1 ml-56 flex flex-col min-h-screen">
        <TopBar />
        <main className="flex-1 p-6 overflow-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

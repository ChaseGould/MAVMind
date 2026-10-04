import { EventLog } from "./components/EventLog";
import { Hud } from "./components/Hud";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { TelemetryStrip } from "./components/TelemetryStrip";
import { Toasts } from "./components/Toasts";
import { CommandBanner, TopBar } from "./components/TopBar";
import { WatchPanel } from "./components/WatchPanel";
import { AppProvider } from "./state/AppContext";

export default function App() {
  return (
    <AppProvider>
      <div className="app">
        <TopBar />
        <CommandBanner />
        <main className="main">
          <aside className="left">
            <Hud />
            <WatchPanel />
            <EventLog />
          </aside>
          <section className="center">
            <MapView />
          </section>
          <aside className="right">
            <SidePanel />
          </aside>
        </main>
        <TelemetryStrip />
        <Toasts />
      </div>
    </AppProvider>
  );
}

import { useMemo, useState } from "react";
import { sortedProposals } from "../lib/vehicle";
import { useVehicle } from "../state/AppContext";
import { Chat } from "./Chat";
import { Inspector } from "./Inspector";
import { ProposalCard } from "./ProposalCard";

type Tab = "chat" | "proposals" | "inspector";

function ProposalsPanel() {
  const proposals = useVehicle((s) => s.proposals);
  const list = useMemo(() => sortedProposals(proposals), [proposals]);
  return (
    <div className="proposals-panel">
      {list.length === 0 ? (
        <div className="empty">
          No proposals. With <b>Commands</b> enabled, ask the assistant to plan a mission; proposals appear here and on
          the map for your approval.
        </div>
      ) : (
        list.map((p) => <ProposalCard key={p.id} id={p.id} />)
      )}
    </div>
  );
}

export function SidePanel() {
  const [tab, setTab] = useState<Tab>("chat");
  const pending = useVehicle((s) => Object.values(s.proposals).filter((p) => p.status === "pending").length);
  const types = useVehicle((s) => s.messages.length);
  // All tabs stay mounted (hidden) so an in-flight chat stream survives tab switches.
  return (
    <div className="side">
      <nav className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "chat"} className={tab === "chat" ? "active" : ""} onClick={() => setTab("chat")}>
          Chat
        </button>
        <button
          role="tab"
          aria-selected={tab === "proposals"}
          className={tab === "proposals" ? "active" : ""}
          onClick={() => setTab("proposals")}
        >
          Proposals{pending > 0 && <span className="count count-warn">{pending}</span>}
        </button>
        <button
          role="tab"
          aria-selected={tab === "inspector"}
          className={tab === "inspector" ? "active" : ""}
          onClick={() => setTab("inspector")}
        >
          Inspector{types > 0 && <span className="count">{types}</span>}
        </button>
      </nav>
      <div className="tab-body" hidden={tab !== "chat"}>
        <Chat />
      </div>
      <div className="tab-body" hidden={tab !== "proposals"}>
        <ProposalsPanel />
      </div>
      <div className="tab-body" hidden={tab !== "inspector"}>
        <Inspector />
      </div>
    </div>
  );
}

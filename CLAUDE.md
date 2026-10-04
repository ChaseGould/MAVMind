# MAVMind: rules for Claude Code sessions

MAVMind is an LLM ground station for ArduPilot vehicles. It runs alongside Mission Planner.
Read `README.md` for the architecture and `docs/api.md` for the service contract.

## Safety rules (non-negotiable)

- **The LLM never arms, disarms, changes mode, or uploads.** Those are UI buttons
  (`/api/actions/*`) or post-approval code (`ProposalManager.approve`). Never add an MCP tool, agent
  tool, or agent-service route that reaches them.
- **The validator is deterministic code with its own test suite, never an LLM.** All limits live in
  `config/safety.yaml`. Every new check gets rejection cases in `tests/test_validator.py`.
- **The command MCP server is off by default** and visibly flagged in the UI when on. Its only tool is
  `propose_mission`. There is no approve tool. Commands need both switches: the chat request
  (`commands_enabled`) and the vehicle service flag (`POST /api/command`).
- **Approval goes from the UI straight to the vehicle service**, never through the agent or the LLM.
- **Every LLM tool call, proposal, approval, and upload goes to an audit log**
  (`logs/vehicle_audit.jsonl`, `logs/agent_audit.jsonl`). Don't remove audit writes.
- **Everything runs in SITL before real hardware; bench tests with props off.**
- The read-only MCP server must stay read-only: tools may read the link (including mission and
  parameter downloads) but never write to the vehicle.
- The API key is read only by the agent service (env or OS keychain). It never goes to the UI,
  the vehicle service, logs, or the repo.

## Conventions

- One MAVLink decoder everywhere: pymavlink, ardupilotmega dialect. All sources emit `MavMessage`
  with standard MAVLink message and field names; nothing above `TelemetrySource` knows the link type.
- Tool responses carry `source`, `timestamp`, `age_s`, `rate_hz`. Units go in field names
  (`alt_rel_m`, `groundspeed_mps`); scaled integers are converted via `shared/units.json`.
  Missing data is `available: false` with a reason, never a guess. History/analysis is capped
  (default 200 points), and statistics are computed in code (`analyze_field`).
- Profiles in `config/profiles/*.yaml`; switching profile never requires code changes.
- Agent history is append-only: append `response.content` unchanged; roll back a failed turn whole.
- Keep `docs/api.md` and `apps/desktop/src/types.ts` in sync when the contract changes.

## Commands

```sh
pip install -r requirements-dev.txt          # both services, editable, plus test tools
pytest                                       # unit + integration (no SITL, no API key needed)
pytest -m llm tests/test_golden.py           # golden questions against the real model
MAVMIND_SITL=1 pytest -m sitl tests/sitl     # needs ArduPilot SITL running
python tests/tlogs/generate_synthetic.py     # regenerate the battery-failsafe tlog + facts
cd apps/desktop && npm test && npm run build # UI tests and build
```

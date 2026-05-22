# NeuroOps — Getting Started with Antigravity

How to load this project into Antigravity and start building immediately.

---

## Step 1 — Install Antigravity 2.0

1. Go to **antigravity.im/getting-started** and download the desktop app for your OS
2. Sign in with your personal Gmail account (Workspace accounts are not supported in preview)
3. Launch the app — you should see the Agent Manager surface

> **Note:** Antigravity 2.0 was announced at Google I/O 2026 (May 2026). If you are on an older
> version, update before starting — the multi-agent parallel execution features require 2.0+.

---

## Step 2 — Clone this repo and open in Antigravity

```bash
git clone https://github.com/Tayab-Ahamed/neuroops.git
cd neuroops
```

In Antigravity:
- `File` → `Open Folder` → select the `neuroops/` folder
- Antigravity will automatically detect `.antigravity/rules.md` and load the agent rules

---

## Step 3 — Set up your environment

```bash
# Copy the environment template
cp .env.example .env

# Fill in your values (at minimum you need):
# ANTHROPIC_API_KEY — get at console.anthropic.com
# GITHUB_TOKEN — get at github.com/settings/tokens (needs repo scope)
```

---

## Step 4 — Install local prerequisites

```bash
# macOS (use Homebrew)
brew install minikube kubectl helm

# Verify
minikube version   # should be 1.33+
kubectl version    # should be 1.30+
helm version       # should be 3.15+
```

---

## Step 5 — How to use this project in Antigravity

This repo is structured as a series of **missions** — one per phase. Each mission is a
self-contained prompt in `PHASES.md` that you paste into the Antigravity Agent Manager.

### The workflow for each phase:

1. **Read the phase section** in `PHASES.md`
2. **Open Agent Manager** in Antigravity (top-left button or `Cmd+Shift+A`)
3. **Create a New Mission** → paste the Antigravity Mission Prompt from that phase
4. **Review the Implementation Plan** that Antigravity generates before approving it
5. **Watch agents work** — they will write code, run terminal commands, and verify output
6. **Check the done criteria** at the end of each phase before moving on

### Tips for working with Antigravity on this project:

- Keep `ARCHITECTURE.md` open in the editor — agents will reference it automatically
- If an agent asks for clarification, refer it to `PRD.md` or `TECH_STACK.md`
- Use Antigravity's Artifact trail to review every decision agents made
- For Phase 2 (LangGraph agents), run the mission in smaller chunks — one agent at a time — 
  if the full mission is too large
- The `.antigravity/rules.md` file is loaded automatically and constrains agent behavior

---

## Step 6 — Start Phase 0

Once Antigravity is open with this folder loaded, go to `PHASES.md` and paste the 
**Phase 0 Antigravity Mission Prompt** into the Agent Manager.

Phase 0 will take approximately 2 hours. When it completes, run:

```bash
make cluster-up    # starts Minikube + deploys Helm charts + demo apps
make up            # starts Docker Compose (Prometheus, Jaeger, Grafana)
make status        # verify everything is running
```

Then open:
- **Grafana:** http://localhost:3000 (admin / admin)
- **Jaeger:** http://localhost:16686
- **Prometheus:** http://localhost:9090

If all three load with data, Phase 0 is done. Proceed to Phase 1.

---

## Troubleshooting

**Minikube not pulling images:**
```bash
minikube ssh
docker pull prom/prometheus:v2.54.1   # test directly
```

**Prometheus not scraping pods:**
Make sure pods have the annotation: `prometheus.io/scrape: "true"`

**Jaeger not receiving traces:**
Check that the OTel Collector is running: `docker compose ps otel-collector`

**LLM API errors in Phase 2:**
Check your ANTHROPIC_API_KEY is set and has available credits.
The agent will retry 3 times with backoff before failing.

**Antigravity agent stuck:**
Open the Artifact trail, find the last completed step, and resume from there.
You can also interrupt and re-run with a more specific follow-up prompt.

---

## Project file map

```
neuroops/
├── PRD.md                    ← Start here — full product requirements
├── ARCHITECTURE.md           ← System design + component details
├── PHASES.md                 ← Build plan + Antigravity mission prompts
├── TECH_STACK.md             ← Exact versions + environment variables
├── GETTING_STARTED.md        ← This file
├── .antigravity/
│   └── rules.md              ← Agent behavior rules (auto-loaded by Antigravity)
├── .env.example              ← Environment variable template
├── docker-compose.yml        ← Generated in Phase 0
├── Makefile                  ← Generated in Phase 0
└── README.md                 ← Generated in Phase 0, updated each phase
```

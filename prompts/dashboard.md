# Portfolio Pulse app

Live app (with Claude chat): https://claude.ai/artifact/BgVcYZTRyt8MrAdUW5pSuU
Source: `app/index.html` (publish it with capabilities `{"sample": {}, "db": {"rules": [{"path": "", "read": "view", "write": "admin"}]}}`).

The page reads its data from its own store, collection `dash`, one document per dataset:
summary, holdings, allocation, news, events, suggestions, scenarios, health, profiles.
Each document is `{"rows": [...], "updated": "<UTC ISO time>"}` (`summary` holds one row).

To refresh after a pipeline run:
1. Write `data/research/<date>.json` (format: see `data/research/2026-11-12.json`);
   update `data/research/profiles.json` when results or analyst views change.
2. Run `python -m portfolio.publish.dashboard_data` to rebuild `data/dashboard/*.json`.
3. Write each file into the app's store with ArtifactData (`set` on collection `dash`,
   doc id = file name, body `{"rows": <file contents>, "updated": <now>}`), pinning
   `if_version` to the version last read. Open copies of the app update by themselves;
   no republish is needed.

The earlier dashboard (https://claude.ai/artifact/NfPYz7qpinGdF6Jp9dyV3T) and its copy in
`dashboard/index.html` are kept for reference but are no longer updated.

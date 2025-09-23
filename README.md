# Dana PO Pipeline

This repository implements a completely free, self‑hostable pipeline for reviewing Persian/English purchase orders (POs) along with associated documents (pro forma invoices, commission approvals, etc.).  The goal of the pipeline is to automate mundane contract checks by combining deterministic code with targeted LLM calls.  At the end of each run the system produces:

- A single Word document (`00_Review_Report.docx`) summarising clause verdicts, deterministic checks, suggested fixes, and evidence.
- Machine‑readable files (`issues.json` and `issues.csv`) that list each clause with its status, severity, expected vs actual text, evidence anchors, and proposed fix.
- Human‑readable HTML diffs for each clause (in the `diffs/` directory).
- Optionally, a best‑effort redline `.docx` comparing the vendor PO to your base template.

## Components

The pipeline relies entirely on free components:

* **n8n Community Edition** – Orchestrates the workflow via a single Webhook and several Execute Command/HTTP nodes.  It receives the uploaded files and returns the final report.
* **OpenSearch** – Provides keyword search with a built‑in Persian analyzer.  Parent chunks are indexed here for BM25 retrieval.
* **Qdrant** – Stores dense vector representations of the parent chunks for semantic search using BGE‑M3 embeddings.
* **Unstructured** – Partitions DOCX/PDF files into typed elements (paragraphs, headings, tables) while preserving page numbers.
* **LangChain / LlamaIndex** – Splits the text into parent chunks (~1.9 k chars) and child chunks (~600 chars with overlap) using recursive and semantic splitters.
* **BGE‑M3 / BGE reranker** – Generates multilingual embeddings for retrieval and performs local cross‑encoder reranking to score candidate chunks.
* **scikit‑learn** – Trains a simple logistic regression classifier to filter candidate chunks before invoking the LLM.
* **OpenAI API** – The only paid component; used with structured JSON output to compare small chunks against your expected clause text.
* **diff‑match‑patch**, **python‑docx**, **docxtpl** – Build human‑friendly diffs and assemble the final Word report.

## Directory Layout

```
dana_po_pipeline/
├── docker-compose.yml               # Compose file defining opensearch, qdrant, n8n, and a Python worker
├── opensearch/
│   └── mapping.json                # Persian analyzer index mapping
├── qdrant/
│   └── create_collection.py        # Script to create the Qdrant collection
├── n8n/
│   ├── workflow.json               # Example n8n workflow definition
│   └── import.sh                   # Helper to import the workflow via n8n CLI
├── schemas/
│   ├── structured_output_schema.json  # JSON schema enforced for LLM responses
│   ├── requirements_contract_main_IRR.json      # Clause spec for IRR main template
│   ├── requirements_contract_summary_IRR.json   # Clause spec for IRR summary template
│   ├── requirements_contract_main_FX.json       # Clause spec for FX main template
│   ├── requirements_contract_summary_FX.json    # Clause spec for FX summary template
│   └── requirements_contract_noban.json         # Clause spec for Noban template
├── scripts/
│   ├── normalize_and_partition.py   # Normalise digits/characters, remove ZWNJ, partition via Unstructured
│   ├── chunk_and_index.py           # Build parent/child chunks, index parents into OpenSearch/Qdrant
│   ├── deterministic_checks.py      # Perform non‑LLM checks (math, currency, dates, PG/APG, etc.)
│   ├── retrieve_candidates.py       # Simple regex‑based retrieval of clause candidates
│   ├── classifier_train.py          # Train the pre‑LLM clause classifier (One‑Vs‑Rest logistic regression)
│   ├── classifier_infer.py          # Apply the classifier to score candidate chunks
│   ├── judge.py                     # Post‑LLM sanity checks and verdict adjustment
│   └── report_builder.py            # Assemble the final Word report and machine‑readable outputs
├── golden_set/                      # Contains synthetic samples for smoke testing (to be populated)
├── requirements.txt                 # Python dependencies for the worker container
└── README.md                        # This file
```

## Setting up the environment

1. **Clone the repository** and navigate into `dana_po_pipeline`.
2. **Start the services**:

   ```bash
   docker compose up -d
   ```

   This command launches OpenSearch (with the Persian analyzer), Qdrant, n8n, and a Python worker container.  The first start may take a few minutes as images are downloaded and indices are created.

3. **Create the Qdrant collection** (optional – only needed on first run):

   ```bash
   docker compose exec worker python qdrant/create_collection.py --collection contracts
   ```

   This creates a collection named `contracts` with dimension 1024 and cosine distance.  You can enable quantisation via the `--quantized` flag.

4. **Import the n8n workflow**:

   ```bash
   # Inside the repo root
   cd n8n
   ./import.sh
   ```

   The script runs `n8n import:workflow` against your local n8n instance.  Alternatively you can import the workflow via the n8n UI.

5. **Train the pre‑LLM classifier** (once you have labelled data):

   The `classifier_train.py` script expects a directory of labelled child chunks.  See the script comments for details.  Once trained, save the model to `models/classifier.joblib` and adjust the workflow accordingly.

## Running the pipeline

With everything started, send a `POST` request with your files to the webhook endpoint.  For example, assuming n8n is exposed on port 5678:

```bash
curl -F "data=@/path/to/PO.docx" \
     -F "pi=@/path/to/PI.docx" \
     -F "commission=@/path/to/commission.docx" \
     -F "template_override=contract_main_IRR" \
     http://localhost:5678/webhook/po-check
```

The response will be a ZIP archive containing:

* `00_Review_Report.docx` – The comprehensive Word report.
* `issues.json` and `issues.csv` – Machine‑readable findings.
* `diffs/` – Per‑clause HTML diffs.
* `01_PO_Redline.docx` – (optional) best‑effort tracked‑changes redline.

## Golden set testing

The `golden_set/` directory is intended for smoke testing.  You can place ten synthetic PO packs here along with small JSON files listing their expected clause statuses.  Use the CLI scripts directly to process these files and verify that the pipeline yields the correct results.

Example of running the scripts on a single case:

```bash
python scripts/normalize_and_partition.py --input golden_set/sample1/po.docx --output sample1_elements.json
python scripts/chunk_and_index.py --elements sample1_elements.json --child-output sample1_child.json --opensearch-index contracts --qdrant-collection contracts
python scripts/deterministic_checks.py --input golden_set/sample1/po.docx --output sample1_deterministic.json
python scripts/retrieve_candidates.py --chunks sample1_child.json --requirements schemas/requirements_contract_main_IRR.json --output sample1_candidates.json
python scripts/classifier_infer.py --model models/classifier.joblib --input sample1_candidates.json --output sample1_filtered.json
# Build the request body for OpenAI structured outputs and call the LLM (not shown)
python scripts/judge.py --results sample1_llm_results.json --requirements schemas/requirements_contract_main_IRR.json --output sample1_judged.json
python scripts/report_builder.py --findings sample1_judged.json --deterministic sample1_deterministic.json --output_dir sample1_report
```

Refer to the individual script documentation strings for further options.

## Notes

* This repository intentionally omits any paid or proprietary components other than OpenAI.  All other tooling is open source and free to self‑host.
* The workflow JSON (`n8n/workflow.json`) is a template; you may need to adjust command paths, environment variables, and the handling of binary data depending on your deployment environment.
* The structured output schema in `schemas/structured_output_schema.json` must match the schema passed to the OpenAI API in the workflow.  The `judge.py` script relies on the presence of `status`, `expected`, `actual`, `evidence`, `fix`, and `severity` fields for each clause.

Feel free to adapt and extend the clauses, requirements, and deterministic checks to suit your organisation’s policies.  Contributions are welcome!
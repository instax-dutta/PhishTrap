# PhishTrap: High-Quality Phishing URL Dataset — Design Spec

## Overview

Create a curated, high-quality phishing URL dataset ("PhishTrap") with 16 extracted features, uploaded to Hugging Face as `saidutta69/PhishTrap`. Process on GCP VM, then use it to reproduce the 2024 paper's Random Forest pipeline and verify all claims.

## Priorities

1. **Quality** — cross-verified sources, deduplication, balanced classes, clean features
2. **Ease of access** — CSV + Parquet, HF datasets-compatible, thorough dataset card
3. **Quantity** — last priority; target ~20K total samples (10K per class)

## Data Sources

### Phishing URLs
- **Phishing.Database** (mitchellkrogza) — 496K domains, MIT license, PyFunceble-verified daily
- **OpenPhish** free feed — updated every 15 minutes, academic standard
- **PhishTank** — community-verified, widely cited
- Quality gate: URL must appear in >= 2 sources OR come from a single high-trust source

### Legitimate URLs
- **Tranco top 10K** — research-grade ranking aggregating CrUX + Cloudflare + Umbrella + Majestic
- Filters out any domain that appears in phishing sources

## Features (16 total)

### Paper's original 6
| Feature | Description |
|---|---|
| url_length | Total URL character count |
| hyphen_count | Number of hyphens in URL |
| digit_count | Number of digits in URL |
| subdomain_count | Number of subdomains |
| trusted_tld | 1 if TLD is .com/.org/.net/.edu/.gov |
| protocol_exists | 1 if http/https present |

### Additional 10 quality features
| Feature | Description |
|---|---|
| special_char_count | Count of special chars (@, -, _, ., etc.) |
| url_entropy | Shannon entropy of URL string |
| path_depth | Number of path segments |
| domain_length | Length of domain portion |
| is_domain_ip | 1 if domain is an IP address |
| has_at_symbol | 1 if @ present in URL |
| has_double_slash_redirect | 1 if // after protocol |
| tld_length | Length of TLD |
| query_param_count | Number of query parameters |
| path_length | Length of path portion |

## Dataset Structure

```
PhishTrap/
├── data/
│   ├── train.csv        (70%)
│   ├── val.csv          (15%)
│   ├── test.csv         (15%)
│   ├── train.parquet
│   ├── val.parquet
│   └── test.parquet
├── README.md            (dataset card)
└── phishtrap_full.csv   (all data, 50/50 balanced)
```

- Columns: `url`, `label` (0=legit, 1=phishing), 16 features, `source`
- Target: ~20K samples (10K phishing, 10K legitimate)

## GCP Infrastructure

- VM: `e2-standard-4` (4 vCPU, 16GB), us-central1-a
- Boot disk: 50GB SSD
- Firewall: no external access needed (only outbound HTTP/HTTPS)
- Daily cost: ~$0.50

## Processing Pipeline

1. Create GCP VM via gcloud CLI
2. SSH in and install Python deps (pandas, scikit-learn, huggingface_hub, etc.)
3. Download all data sources
4. Deduplicate and apply quality gates
5. Extract 16 features
6. Balance classes (downsample majority)
7. Split train/val/test
8. Save as CSV + Parquet
9. Upload to Hugging Face via `huggingface_hub`
10. Write dataset card

## Post-Dataset: Paper Reproduction

After PhishTrap is on HF:
1. Iterative training of Random Forest (matching paper methodology)
2. Benchmark accuracy/precision/recall/F1/prediction time vs data size
3. Compare against paper's claims (95% accuracy at 1500 samples, diminishing returns at ~2500)
4. Surface any discrepancies

## Success Criteria

- [ ] Dataset uploaded to `saidutta69/PhishTrap` with README + CSV + Parquet
- [ ] At least one paper claim validated or challenged with evidence
- [ ] VM cleaned up after completion

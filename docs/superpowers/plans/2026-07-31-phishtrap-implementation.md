# PhishTrap Implementation Plan

**Goal:** Build, upload to HF, and use the PhishTrap dataset to reproduce 2024 paper claims

**Architecture:** GCP VM -> Python pipeline -> Hugging Face -> paper reproduction script

**Tech Stack:** Python (pandas, scikit-learn, huggingface_hub), GCP e2-standard-4

## Tasks

### Task 1: Provision GCP VM and transfer scripts
- Create `e2-standard-4` VM in us-central1-a
- Install Python deps (pandas, scikit-learn, huggingface_hub, requests, tld, numpy)
- Transfer `build_phishtrap.py` and `reproduce_paper.py` to VM

### Task 2: Build and upload PhishTrap dataset
- Download all data sources
- Dedup, extract 16 features, balance classes
- Save CSV + Parquet, push to `saidutta69/PhishTrap`
- Write README dataset card

### Task 3: Reproduce paper pipeline
- Load PhishTrap from HF
- Iterative Random Forest training (matching paper methodology)
- Generate accuracy/F1/precision/recall/prediction time vs data size plots
- Compare against paper claims

### Task 4: Cleanup
- Save results locally
- Delete GCP VM

# 🌿 Agri Doctor — AI-Powered Crop Health Assistant

> A beginner-friendly, production-quality web application that uses two independent AI agents to diagnose crop diseases and generate farmer-friendly advisories.

**Powered by:**
- 🔬 **Groq Vision LLM** (Pathologist Agent — image analysis)
- 🌿 **IBM Granite 4 H Small** via **IBM watsonx.ai** (Extension Officer Agent — farm advisory)

---

## 📋 Table of Contents

1. [Features](#-features)
2. [Project Architecture](#-project-architecture)
3. [Prerequisites](#-prerequisites)
4. [Setup Instructions](#-setup-instructions)
5. [API Configuration](#-api-configuration)
6. [Running the Application](#-running-the-application)
7. [Running Tests](#-running-tests)
8. [How the Two-Agent Workflow Works](#-how-the-two-agent-workflow-works)
9. [Safety Guardrails](#-safety-guardrails)
10. [Troubleshooting](#-troubleshooting)
11. [Deployment](#-deployment)

---

## ✨ Features

| Feature | Details |
|---|---|
| 🔬 Pathologist Agent | Groq Vision LLM analyses crop images for disease, symptoms, causes |
| 🌿 Extension Officer Agent | IBM Granite 4 H Small generates farmer-friendly recommendations |
| 🤖 Multi-Agent Workflow | Sequential pipeline: Image → Pathologist → Extension Officer → Advisory |
| 📊 LLM Performance Dashboard | Real-time latency, token usage, cost tracking, guardrail analytics |
| 🛡️ Safety Guardrails | Injection detection, toxicity filtering, PII protection, output validation |
| 📋 Advisory History | All diagnoses stored in SQLite with download button |
| ⬇️ Export Advisory | Download complete advisory as a TXT file |
| ⚙️ Settings Page | Runtime API key configuration without restarting |

---

## 🏗️ Project Architecture

```
Agri-doc/
├── app.py                          # Main Streamlit application
├── config.py                       # All configuration & constants
├── database.py                     # SQLite persistence layer
├── dashboard.py                    # LLM Performance Dashboard renderer
│
├── agents/
│   ├── __init__.py
│   ├── pathologist_agent.py        # Agent 1: Groq Vision LLM
│   └── extension_officer_agent.py  # Agent 2: IBM Granite
│
├── services/
│   ├── __init__.py
│   ├── groq_service.py             # Groq API client
│   └── ibm_service.py              # IBM watsonx.ai API client
│
├── guardrails/
│   ├── __init__.py
│   ├── input_guardrails.py         # Image & text input validation
│   └── output_guardrails.py        # LLM output safety filters
│
├── tests/
│   ├── conftest.py
│   ├── test_guardrails.py
│   ├── test_agents.py
│   └── test_database.py
│
├── .env.example                    # Environment variable template
├── requirements.txt
└── README.md
```

---

## 📦 Prerequisites

- Python 3.9 or higher
- pip (Python package manager)
- A **Groq API key** (free tier available at [console.groq.com](https://console.groq.com))
- An **IBM Cloud account** with a watsonx.ai project

---

## 🚀 Setup Instructions

### Step 1 — Clone / Download the project

```bash
cd ~/your/projects/folder
# If you have the folder already, just navigate to it
cd Agri-doc
```

### Step 2 — Create a Python virtual environment

```bash
python3 -m venv venv
source venv/bin/activate        # macOS / Linux
# venv\Scripts\activate.bat     # Windows
```

### Step 3 — Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Configure environment variables

```bash
cp .env.example .env
```

Edit `.env` with your actual API keys:

```env
WATSONX_API_KEY=your_ibm_cloud_api_key
WATSONX_PROJECT_ID=your_watsonx_project_id
WATSONX_URL=https://us-south.ml.cloud.ibm.com
WATSONX_MODEL_ID=ibm/granite-4-0-tiny-preview

GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL_ID=gemini-2.5-flash

GROQ_API_KEY=your_groq_api_key
GROQ_MODEL_ID=qwen/qwen3.8-27b
```

---

## 🔑 API Configuration

### IBM watsonx.ai Setup

1. Log in to [IBM Cloud](https://cloud.ibm.com)
2. Navigate to **watsonx.ai** service
3. Create a **project** and copy the **Project ID**
4. Go to **Manage → API keys** and create a new API key
5. Add both values to your `.env` file
6. The default region URL is `https://us-south.ml.cloud.ibm.com`

### Groq API Setup

1. Create a free account at [console.groq.com](https://console.groq.com)
2. Navigate to **API Keys** and create a new key
3. Add it to your `.env` file as `GROQ_API_KEY`

> **Note:** You can also enter API keys directly in the application's **Settings** page without needing a `.env` file. Keys entered there are stored only in the browser session and never persisted.

---

## ▶️ Running the Application

```bash
# Make sure your virtual environment is activated
source venv/bin/activate

# Start the Streamlit app
streamlit run app.py
```

The application will open at **http://localhost:8501** in your browser.

---

## 🧪 Running Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_guardrails.py -v
pytest tests/test_agents.py -v
pytest tests/test_database.py -v

# Run with coverage report
pytest tests/ --cov=. --cov-report=term-missing
```

> **Note:** Tests use mock API responses and do **not** consume any API credits.

---

## 🤖 How the Two-Agent Workflow Works

```
Farmer uploads crop image
        ↓
[Input Guardrails]
  • Image format/size/integrity validation
  • Farmer notes injection detection
        ↓
[Agent 1: Pathologist Agent]
  • Sends image to Groq Vision LLM
  • Returns: suspected disease, symptoms, causes, confidence
        ↓
[Output Guardrails — Pathologist]
  • Validates required fields
  • Checks for hallucination signals
  • Adds safety disclaimer
        ↓
[Cross-Agent Handoff Verification]
  • Extension Officer verifies report is usable
        ↓
[Agent 2: Extension Officer Agent]
  • Passes pathologist report to IBM Granite 4 H Small
  • Returns: immediate actions, preventive measures, treatments
        ↓
[Output Guardrails — Extension Officer]
  • Validates required fields
  • Filters unsafe chemical advice
  • Adds mandatory disclaimer
        ↓
[Final Advisory displayed + saved to DB + downloadable as TXT]
```

---

## 🛡️ Safety Guardrails

### Input Guardrails
- ✅ Image format, size, and integrity validation
- ✅ Prompt injection detection in farmer notes
- ✅ Toxicity / abusive content filtering
- ✅ PII detection (phone, email, national ID)
- ✅ HTML and control character sanitisation

### Output Guardrails
- ✅ Required field validation for both agents
- ✅ Hallucination signal detection
- ✅ Overconfidence detection (flags "100% certain" claims)
- ✅ Unsafe chemical advice filtering
- ✅ Cross-agent handoff verification
- ✅ Mandatory AI disclaimer on all outputs

### Agricultural Safety
- All results are labelled as AI-generated preliminary assessments
- Chemicals recommended only when supported by reliable guidance
- PPE instructions included with all chemical recommendations
- Environmental precautions specified
- Local expert consultation recommended when confidence is low

---

## 🔧 Troubleshooting

| Problem | Solution |
|---|---|
| `GROQ_API_KEY is missing` | Add your Groq key to `.env` or the Settings page |
| `IBM watsonx 401 Unauthorized` | Check your `WATSONX_API_KEY` and that it has watsonx.ai access |
| `ibm/granite-4-0-tiny-preview model not found` | Try `ibm/granite-13b-instruct-v2` or check IBM's current model list |
| `Image too large` | Resize your image to under 10 MB |
| `Corrupted image error` | Try saving the image again in a standard JPG/PNG format |
| `Connection timeout` | Check your internet connection and retry |
| Port 8501 already in use | Run with `streamlit run app.py --server.port 8502` |

---

## 🌐 Deployment

### Streamlit Cloud (Recommended for sharing)

1. Push your project to a GitHub repository (exclude `.env` — it's in `.gitignore`)
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect your repo
3. Add your environment variables under **Advanced settings → Secrets**
4. Deploy — Streamlit Cloud will install `requirements.txt` automatically

### Local Production

```bash
streamlit run app.py --server.port 8501 --server.headless true
```

---

## ⚠️ Disclaimer

All diagnoses produced by Agri Doctor are **AI-generated preliminary assessments** and are **not** confirmed laboratory diagnoses. Always consult a qualified agricultural extension officer or plant pathologist before applying any treatment. Follow all pesticide label instructions and local agricultural regulations.

---

*Agri Doctor v1.0 — Built with ❤️ for smallholder farmers*
*Powered by IBM Granite 4 H Small + Groq Vision LLM*

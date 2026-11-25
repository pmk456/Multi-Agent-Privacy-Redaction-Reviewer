# Review 2 demo script

**Rule for the whole demo:** use demo mode and fictional data only. Never upload a real
document, and never screenshot anything that isn't fictional.

**Length:** about 8 minutes, plus questions.

## Before the session
1. Pull the branch that will be demoed, then run `cd backend && pytest` and confirm it passes.
2. Start the app from the repository root:
   ```bash
   uvicorn --factory privacy_review.api:create_app --app-dir backend
   ```
3. Open `http://127.0.0.1:8000/ui/` in a fresh browser window, then zoom to 125% so the room can read it.
4. Prepare a folder `demo-files/` **outside the repository** containing:
   - `notes.txt`: a fictional sentence, for example *"Contact Alex Example at alex@example.com."*
   - `empty.txt`: an empty file
   - `slides.docx`: any file with a `.docx` extension
5. Close every other tab and notification.

## 1. The rule (30 s)
> "Original documents never leave the backend. The browser only ever receives redacted
> text, entity categories, risks, strategies, findings and counts."

Point at the footer line on the page, which says the same thing.

## 2. Backend status (30 s)
Point at the status line under the title, which shows **pipeline: stub (documents are withheld)**.
> "Until the full pipeline lands, the backend withholds everything. A mock that echoed
> its input would leak exactly what it stands in for, so it never does."

If the live pipeline has landed by the review, the line reads **live**. Adapt this step.

## 3. Ingestion and safe errors (1.5 min)
1. Click **Click to choose files** and select `notes.txt`, `empty.txt` and `slides.docx`. Then click **Review files**.
2. The error panel lists file 2 with `empty_document` and file 3 with `unsupported_format`.
   > "The server reports problems by file index and code. It never echoes the filename,
   > because a filename like *jane_doe_discharge.pdf* is itself identifying. The name you
   > see comes from the browser's own file picker."
3. Mention without demoing: encrypted PDFs and scanned PDFs with no text layer are rejected with clear codes, and there is no OCR.
4. Select only `notes.txt` and click **Review files**. The document comes back **blocked** with the stub's reason.

## 4. Demo mode: a document that was released (2 min)
Click **Demo mode** and open **hr-record-01**.
- **Badge and reason:** released after 1 remediation round.
- **Redacted text:** placeholders are highlighted: `PERSON_01`, `[ORGANIZATION]`, `[EMAIL_ADDRESS]`, `[PHONE_NUMBER]`, `[REDACTED]`. The age band `30-39` and the state `Karnataka` are generalised values.
  > "Generalised values aren't highlighted, because entity positions refer to the original
  > text, and we never show those positions."
- **Entities by type:** each chip shows risk and strategy. Colour shows risk, from low to critical.
- **Strategy per entity:** each row gives type, risk (including any escalation, for example *from low*), strategy, policy and rationale. There is no value column.
- **Verification findings:** one warning, resolved in round 1.

## 5. Consistent pseudonyms (45 s)
Open **award-news-02**.
> "The same person is `PERSON_01` here too. The pseudonym is batch-consistent, so the
> documents stay useful together. That same consistency is why we need Agent 5."

## 6. A blocked document and cross-document linkage (1.5 min)
Open **support-ticket-03**.
- The badge says **blocked**. The redacted text is *Withheld*: a blocked document's text is never sent to the browser.
- Findings:
  - a **blocking** quasi-identifier combination (occupation + employer + age band, k = 1)
  - an adversarial **cross-document linkage** to `hr-record-01`

Open **Aggregate**.
- Show the released vs blocked counts and the charts for risks, entity types, strategies and findings.
- In the **Cross-document linkage** table, show group `lc-01`: two documents linked by organisation and occupation, with **k = 1**.
  > "Each document looks harmless alone. Together they identify one person. That's the
  > case Agent 5 is built to catch."

## 7. How we know Agent 5 is right (1 min)
Briefly show `backend/tests/fixtures/synthetic_cross_document.json` in the editor. Scroll to `planted_risks`.
> "Ground truth that doesn't depend on any agent: 28 fictional documents and a 40-person
> registry. Five people are re-identifiable only by combining documents; four controls
> must not be flagged. The tests recompute every k from the registry."

**[PLACEHOLDER]** Once the evaluation report exists, show its Agent 5 result on this set. Quote only numbers from the report.

## 8. Close (30 s)
- Done: contracts, knowledge base, ingestion, API, storage, frontend, synthetic ground truth.
- **[PLACEHOLDER]** Agent and orchestration status at the time of the review.
- Next: **[PLACEHOLDER]**

## If something fails during the demo
- **Backend down:** demo mode still works, because the mock is a static file. Say so and carry on from step 4.
- **Plotly CDN blocked:** the aggregate view says so in place of each chart. The linkage table and counts still render.

## Screenshot checklist for the report
- [ ] Taken in demo mode, or with the fictional `demo-files/` only
- [ ] The browser address bar shows `127.0.0.1` and no personal bookmarks or tabs
- [ ] No terminal window showing paths with a personal username

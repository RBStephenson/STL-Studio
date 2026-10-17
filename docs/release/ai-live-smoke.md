# AI live smoke

STL Studio calls the Anthropic API from four places. Every automated test for
them replaces the SDK with a fake at the boundary, which is correct for unit
tests but means CI cannot tell you whether the real API still accepts our
requests. A green suite proves only that our fakes still match our own call
shape.

Run this smoke against a real API key whenever a release changes any of:

- the `anthropic` pin in `backend/requirements.txt`
- the default model or the model list (`DEFAULT_MODEL`, `_PRE_ADAPTIVE_MODELS`)
- the thinking or effort parameters sent with a request

Record the build, the model, and a pass/fail per step on the release ticket.

## The four call sites

| # | Feature | Where the request is made | Route | Feature flag (Settings tab) |
|---|---|---|---|---|
| 1 | Painting guide AI draft | `generate_guide_draft` in `backend/app/painting/services/generation.py` (streaming) | `POST /api/painting/guides/{id}/draft` | `painting_guides_enabled` (Painting) |
| 2 | Swatch-chart import, PDF with embedded swatch images | `_ocr_chunk` in `backend/app/painting/services/swatch_extract_vision.py` | `POST /api/painting/paints/extract-colors` | `paint_swatch_import_enabled` (Painting) |
| 3 | Swatch-chart import, photo or image-only PDF | `_extract_from_one_image` in `backend/app/painting/services/swatch_extract_photo.py` | same route | same flag |
| 4 | Reorganize "Suggest with AI" | `_llm_refine_anthropic` in `backend/app/services/ai_organize.py` | `POST /api/reorganize/ai-suggest` | `ai_organize_enabled` (AI Integrations) |

Rows 2 and 3 share one endpoint. `extract_colors` chooses the tier from the
uploaded file, so **the file you upload decides which call site runs**:

- A vector PDF (swatches drawn as shapes) is read without any AI call, so it
  does not count toward this smoke.
- A PDF whose swatches are embedded images reaches call site 2.
- A JPG/PNG photo of a chart, or a scanned image-only PDF, reaches call site 3.

## Setup

1. Install or run the build under test.
2. In **Settings → AI Integrations**, confirm a valid API key is saved and note
   the selected model.
3. Turn on the three feature flags above. All three are off by default.

## Steps

1. **Guide draft.** Painting → create a guide with **Generate AI draft**
   ticked, or open an existing guide's content editor and click
   **Generate AI draft**. *Pass:* the draft page fills in and the job reaches a
   finished state. *Fail:* a 400 from the API (usually the thinking
   parameters do not suit the selected model), a 502 (upstream error), or a job
   that never leaves the queue.
2. **Swatch import, embedded images.** Paint Shelf → **Import from Chart** →
   upload a manufacturer PDF whose swatches are images. *Pass:* **Review swatch
   matches** opens with colors listed. *Fail:* 503 means no usable API key is
   configured; 502 means the AI request itself failed.
3. **Swatch import, photo.** Same button, upload a clear photo (JPG/PNG) of a
   swatch chart. *Pass:* **Review swatch matches** opens with colors listed. An
   "unreadable" result is a legitimate outcome for a poor photo rather than an
   SDK failure, so retry with a clearer image before recording a fail.
4. **Reorganize suggestion.** Reorganize Library → build a preview → on any
   row, click **Suggest with AI**. *Pass:* the row's override fields are
   prefilled. *Fail:* the error text under the row shows the API's message (or
   "AI suggestion unavailable").

## Model coverage

What matters is **adaptive vs pre-adaptive thinking**, not the number of
models tried. Models listed in `_PRE_ADAPTIVE_MODELS` (currently
`claude-haiku-4-5`) are sent no thinking or effort parameters. That tuple is
defined separately in `generation.py` and `ai_organize.py`, which must be kept
in step.

Run all four steps on the default model. When the release touches the model
list or the thinking parameters, also switch to a pre-adaptive model and repeat
steps 1 and 4, the two call sites that branch on that list.

# Open WebUI document extraction engines: cost & self-hosting research

Research into Open WebUI's RAG "content extraction engine" options — what they cost,
what it takes to self-host each one, and how they compare. Triggered by wanting better
PDF/document handling for the `open-webui` service (`homelab/services/open-webui/`),
which today runs with no local models (Ollama Cloud only) and has never touched this
setting, so it's still on the built-in default.

## TL;DR

- **Today's default (`pypdf`, no config) is the weakest option**: no OCR, can't read
  image-only PDFs, and has a known memory-leak-on-heavy-ingestion complaint from users.
  It's fine for occasional text-native PDFs, which is likely most of what gets uploaded
  here.
- **Apache Tika is the cheapest real upgrade** for picklelab's hardware (Celeron J3455,
  16 GB RAM, no GPU, see `homelab/README.md`): a sidecar container, ~1–2 GB RAM, JVM-based,
  no GPU needed, does OCR via Tesseract in the "full" image variant.
- **Docling is the better *quality* upgrade** (real layout/table detection) but is
  meaningfully heavier: CPU-only inference works (no GPU required), but it's built and
  benchmarked on server-class CPUs, and the Celeron J3455 is a low-power 2016 Apollo Lake
  part — expect noticeably-worse-than-benchmark throughput, likely several seconds/page
  rather than the ~0.8s/page median seen on an AMD EPYC benchmark box.
- **Cloud OCR APIs (Mistral OCR, Azure Document Intelligence, Datalab Marker,
  Unstructured serverless) are all cheap per-page** ($0.30–$4 per 1,000 pages) and offload
  compute from the NUC entirely, at the cost of sending document content off-box and
  needing an API key/secret in 1Password. For a homelab with occasional document uploads,
  the actual monthly cost of any of these is likely single-digit dollars or less.
- **No option needs a GPU** for open-webui's use case; GPUs only matter if pushing for
  high page-per-second throughput, which isn't the workload here.

## Engine options

Open WebUI's content extraction engine is set in Admin Settings → Documents. Options as
of the current release (per [docs.openwebui.com](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/)):

| Engine | What it is | Self-host or cloud | Extra service needed |
|--------|-----------|---------------------|------------------------|
| **Default (`pypdf`)** | Built into the Open WebUI backend, Python PDF text extraction | Self-host (already running, no extra component) | None |
| **Apache Tika** | Java content-analysis toolkit, extracts text/metadata from 1000+ file types | Self-host | `apache/tika` sidecar container |
| **Docling** | IBM-backed document conversion library — layout detection, table structure (TableFormer), OCR (EasyOCR) → structured Markdown/JSON | Self-host (CPU or GPU) | `docling-serve` sidecar container |
| **Mistral OCR** | Mistral's hosted OCR/document API, layout + handwriting + 170 languages | Cloud API | API key only, no container |
| **Azure Document Intelligence** | Microsoft's hosted document/OCR service, prebuilt + custom extraction models | Cloud API | API key/endpoint only |
| **External (Datalab Marker, Unstructured, etc.)** | Third-party parsers wired in via Open WebUI's "external" loader hook | Either (Marker/Unstructured both offer cloud API *and* self-hosted OSS) | Depends on which one |

Two notable options that came up in Open WebUI's GitHub discussions but aren't first-class
UI dropdown entries yet: **Marker** (via Datalab's cloud API, requested in
[discussion #14312](https://github.com/open-webui/open-webui/discussions/14312)) and
**Azure Content Understanding** (requested in
[discussion #22918](https://github.com/open-webui/open-webui/discussions/22918)).

## Resource requirements for self-hosting

| Engine | CPU/RAM | GPU | Disk | Notes |
|--------|---------|-----|------|-------|
| `pypdf` (default) | Negligible, runs in-process | No | 0 (no extra container) | Leaks memory under heavy ingestion per user reports; no OCR |
| Apache Tika | ~1–2 GB RAM recommended (`-Xmx1024m`+); default container memory is often too low and OOMs (exit 137) on large PDFs | No | Small (~200–500 MB image, "minimal" variant); "full" variant adds Tesseract/GDAL, notably larger | JVM tuning (`JAVA_OPTS`, `--spawnChild`/ForkParser) matters for stability under load |
| Docling (`docling-serve`) | ~2 GB RAM minimum for CPU inference; models are baked into the image (~4 GB image), no separate download step | Optional. If used: ~4–6 GB VRAM total (layout model ~1 GB, TableFormer ~600 MB, EasyOCR 0.5–1.5 GB). Official benchmark used an L4 (24 GB VRAM) / g6.xlarge (8 vCPU, 32 GB RAM) | ~4 GB image | CPU-only median was 0.79s/page on an AMD EPYC benchmark box (IBM's technical report) — a low-power quad-core Celeron J3455 (picklelab) should be assumed noticeably slower, not benchmark-equivalent |
| Marker / MinerU (self-hosted OSS) | Similar order to Docling; benchmarked on the same class of GPU cloud instance (Spheron's guide targets GPU cloud, not CPU-only) | Recommended for throughput; MinerU fastest at ~0.21s/page and Docling ~0.49s/page on Nvidia L4 in one comparison | — | Both have OSS self-host paths; Marker has more restrictive licensing than Docling/MinerU for commercial use |

**Takeaway for picklelab specifically:** nothing here needs a GPU (the NUC doesn't have
one), but Docling/Marker/MinerU are all designed and benchmarked assuming decent CPU
throughput or a GPU cloud box. On the J3455 they'll work but slowly — fine for the
homelab's actual volume (occasional document uploads, not bulk RAG ingestion), but not a
service to point at "index my whole vault" without expecting it to take a while.

## Cost comparison (cloud APIs)

| Service | Price | Free tier |
|---------|-------|-----------|
| Datalab Marker API | $0.30 per 1,000 pages | $5 **one-time** signup credit (~16,700 pages), not recurring — balance hits $0 and requests 403 until you're on a paid plan |
| Unstructured serverless API | ~$1 per 1,000 pages (pay-as-you-go listed as $0.03/page in one source — treat as approximate, pricing pages disagree) | **15,000 pages/month, recurring**, resets monthly, no credit card required |
| Mistral OCR 3 | $2/1,000 pages standard, $1/1,000 batch | None — the free "Experiment" tier (~1B tokens/month) covers chat/text models only; the OCR endpoint bills per-page from page one |
| Mistral OCR 4 (current) | $4/1,000 pages standard, $2/1,000 batch | Same as above — no free allowance |
| Azure Document Intelligence — Read (OCR only) | $1.50/1,000 pages | 500 pages/month, recurring, but the free **F0 tier only processes the first 2 pages of any document** and silently drops the rest — not usable for real multi-page PDFs without upgrading to S0 |
| Azure Document Intelligence — Prebuilt models | $10/1,000 pages | Same F0 tier + 2-page-per-doc cap |
| Azure Document Intelligence — Custom extraction | $30/1,000 pages | Same F0 tier + 2-page-per-doc cap |

At homelab scale (dozens to low hundreds of pages/month, not thousands), Unstructured's
recurring 15,000-pages/month free tier likely covers this use case indefinitely at zero
cost. Everything else is either a one-time trial credit (Datalab) or has no free
allowance at all (Mistral OCR), and Azure's free tier is effectively unusable beyond
2-page test documents. Outside of Unstructured, cost is still trivial at this volume —
it's just not actually "free" the way the headline numbers imply.

## Comparisons found online

- **Speed (GPU, Nvidia L4)**: MinerU fastest at ~0.21s/page, Docling ~0.49s/page, Marker
  ~0.86s/page ([Spheron Blog](https://www.spheron.network/blog/self-host-document-intelligence-docling-marker-mineru-rag-guide/)).
  Docling was faster than MinerU on at least one smaller (12-page) document test — the
  ranking isn't perfectly consistent across benchmarks/doc sizes.
- **Speed (CPU-only, no GPU)**: Docling median 0.79s/page on an AMD EPYC-class server CPU;
  5th–95th percentile range 0.6s–16.3s/page depending on document complexity
  ([Docling Technical Report](https://arxiv.org/html/2408.09869v4)). Unstructured reportedly
  doesn't benefit from GPU acceleration at all.
- **Layout/table accuracy**: MinerU leads layout detection benchmarks (~97.5 mAP) and wins
  on formula detection; Docling's TableFormer scores >91% TEDS on FinTabNet (table
  structure) vs. Marker's ~75–80% TEDS on the same benchmark. Marker's Surya layout model
  is competitive on text/headers but weaker on tables.
  ([themenonlab.blog comparison](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026),
  [jimmysong.io deep dive](https://jimmysong.io/blog/pdf-to-markdown-open-source-deep-dive/))
- **Marker vs. Mistral OCR / Docling / Tika**: an Open WebUI feature-request discussion
  claims Marker "outperforms Mistral OCR" and is faster than both Docling and Tika when
  its own LLM-assist mode is disabled — but the discussion gives no concrete numbers, so
  treat this as a qualitative, self-interested claim rather than a benchmark
  ([discussion #14312](https://github.com/open-webui/open-webui/discussions/14312)).
- **Licensing**: Marker carries more restrictive licensing than Docling or MinerU for
  commercial self-hosted use — irrelevant for a personal homelab but worth knowing if this
  ever became a shared/commercial tool.

## Recommendation

For `open-webui` on picklelab, in order of effort vs. payoff:

1. **Stay on default** if uploaded documents are mostly text-native PDFs/docs and OCR/table
   fidelity has never actually been a problem — no action needed.
2. **Add Apache Tika** as the first upgrade if OCR or exotic file types (images, scanned
   PDFs) start showing up — cheapest self-hosted option in RAM/CPU terms, straightforward
   sidecar (`http://tika:9998`), same Compose-sidecar pattern already used for
   `open-terminal`.
3. **Consider a cloud OCR API instead of Docling** if document quality matters more than
   self-hosting purity — it avoids adding a multi-GB container + CPU load to a low-power
   NUC that also runs everything else in `homelab/services/`. **Unstructured** is the
   strongest pick here: its 15,000-pages/month free tier recurs monthly and likely covers
   this use case at zero ongoing cost. Mistral OCR and Azure Document Intelligence have no
   comparable free allowance (Azure's F0 tier is capped at 2 pages/document, effectively
   unusable) but are still cents/month at this volume.
4. **Docling self-hosted** is the right call only if OCR/table quality needs to be good
   *and* documents must never leave the box — expect it to be the heaviest and slowest of
   these options on this hardware.

## Sources

- [Open WebUI: Document Extraction overview](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/)
- [Open WebUI: Apache Tika extraction](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/apachetika/)
- [Open WebUI: Docling extraction](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/docling/)
- [Open WebUI: Mistral OCR extraction](https://docs.openwebui.com/features/chat-conversations/rag/document-extraction/mistral-ocr/)
- [Open WebUI discussion #14312 — Marker API content extraction](https://github.com/open-webui/open-webui/discussions/14312)
- [Open WebUI discussion #22918 — Azure Content Understanding request](https://github.com/open-webui/open-webui/discussions/22918)
- [Open WebUI discussion #9583 — Azure Document Intelligence support](https://github.com/open-webui/open-webui/discussions/9583)
- [Open WebUI discussion #16792 — Default engine PDF OCR regression](https://github.com/open-webui/open-webui/discussions/16792)
- [GitHub: hwdsl2/docker-docling](https://github.com/hwdsl2/docker-docling) (self-hosted Docling server resource notes)
- [Docling Technical Report (arXiv)](https://arxiv.org/html/2408.09869v4)
- [Docling GPU support docs](https://docling-project.github.io/docling/usage/gpu/)
- [Spheron Blog: Self-Host Document Intelligence — Docling, Marker, MinerU](https://www.spheron.network/blog/self-host-document-intelligence-docling-marker-mineru-rag-guide/)
- [jimmysong.io: Best Open Source PDF to Markdown Tools 2026](https://jimmysong.io/blog/pdf-to-markdown-open-source-deep-dive/)
- [themenonlab.blog: Best Open-Source PDF-to-Markdown Tools 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [Mistral AI pricing](https://mistral.ai/pricing/)
- [Azure Document Intelligence pricing](https://azure.microsoft.com/en-us/pricing/details/document-intelligence/)
- [Datalab Marker conversion API overview](https://documentation.datalab.to/docs/recipes/marker/conversion-api-overview)
- [Unstructured pricing](https://unstructured.io/pricing)
- [Unstructured: 15,000 free pages announcement](https://x.com/UnstructuredIO/status/1990817148759847260)
- [Azure Document Intelligence service quotas and limits (F0 tier, 2-page cap)](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/service-limits?view=doc-intel-4.0.0)
- [Datalab billing docs (credit expiry behavior)](https://documentation.datalab.to/platform/billing)
- [Apache Tika Docker images](https://github.com/apache/tika-docker)
- [Apache Tika memory issue discussion (Alfresco)](https://github.com/Alfresco/alfresco-docker-installer/issues/87)

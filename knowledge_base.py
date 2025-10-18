import os
import io
import torch
import numpy as np
import fitz  # PyMuPDF
from PIL import Image

############################
# Load & Configure Retrieval
############################

def _pick_dtype(device: str):
    if device.startswith("cuda"):
        return torch.float16
    # bf16 is nice if CPU supports it, but safest is float32 on CPU
    return torch.float32


def load_retrieval_model(model_choice="colpali", device="cpu"):
    """
    Backward-compatible loader with extra, faster VLM options.
    Returns: (model, processor, model_type)
    model_type equals model_choice, preserving your external behavior.

    Supported choices (additive over your original):
      - "siglip"  : google/siglip-base-patch16-224 (fast, multimodal)
      - "clip"    : openai/clip-vit-base-patch32 (fast, multimodal)
      - "colpali" : vidore/colpali-v1.2-hf (your original heavy retriever)
      - "all-minilm" : all-MiniLM-L6-v2 (your original text-only)
    """
    dtype = _pick_dtype(device)

    if model_choice == "siglip":
        from transformers import SiglipModel, SiglipProcessor
        name = "google/siglip-base-patch16-224"
        model = SiglipModel.from_pretrained(name, dtype=dtype).to(device).eval()
        processor = SiglipProcessor.from_pretrained(name, use_fast=True)
        model_type = "siglip"

    elif model_choice == "clip":
        from transformers import CLIPModel, CLIPProcessor
        name = "openai/clip-vit-base-patch32"
        model = CLIPModel.from_pretrained(name, dtype=dtype).to(device).eval()
        processor = CLIPProcessor.from_pretrained(name, use_fast=True)
        model_type = "clip"

    elif model_choice == "colpali":
        from transformers import ColPaliForRetrieval, ColPaliProcessor
        name = "vidore/colpali-v1.2-hf"
        # keep your semantics, just ensure dtype/device
        model = ColPaliForRetrieval.from_pretrained(name, dtype=torch.bfloat16).to(device).eval()
        processor = ColPaliProcessor.from_pretrained(name, use_fast=True)
        model_type = "colpali"

    elif model_choice == "all-minilm":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        processor = None
        model_type = "all-minilm"

    else:
        raise ValueError(f"Unsupported retrieval model choice: {model_choice}")

    return model, processor, model_type


def _l2norm(x: torch.Tensor) -> torch.Tensor:
    x = x.float()
    return x / (x.norm(dim=-1, keepdim=True) + 1e-12)


def embed_text(query, model, processor, model_type="colpali", device="cpu"):
    """
    Backward-compatible. Always returns a torch.Tensor on CPU for uniformity.
    """
    with torch.no_grad():
        if model_type == "colpali":
            # Keep your original pathway (text → embeddings)
            inputs = processor(text=[query], truncation=True, max_length=512, return_tensors="pt").to(device)
            outputs = model(**inputs)
            emb = outputs.embeddings.mean(dim=1).squeeze(0)
            return _l2norm(emb).cpu()

        elif model_type == "all-minilm":
            emb = model.encode(query, convert_to_tensor=True)
            return _l2norm(emb).cpu()

        elif model_type == "siglip":
            # SigLIP provides aligned text/image spaces
            # get_text_features is available via forward helpers in HF >= 4.40
            inputs = processor(text=[query], return_tensors="pt", padding=True, truncation=True, max_length=64).to(device)
            try:
                emb = model.get_text_features(**inputs)
            except AttributeError:
                # fallback to forward and pool
                out = model(**inputs)
                emb = out.text_embeds
            emb = emb.squeeze(0)
            return _l2norm(emb).cpu()

        elif model_type == "clip":
            inputs = processor(text=[query], return_tensors="pt", padding=True, truncation=True, max_length=77).to(device)
            try:
                emb = model.get_text_features(**inputs)
            except AttributeError:
                out = model(**inputs)
                emb = out.text_embeds
            emb = emb.squeeze(0)
            return _l2norm(emb).cpu()

        else:
            raise ValueError(f"Unsupported model_type: {model_type}")


##################
# Scoring & Search
##################

def late_interaction_score(query_emb, doc_emb):
    q_vec = query_emb.view(-1)
    d_vec = doc_emb.view(-1)
    q_norm = q_vec / (q_vec.norm() + 1e-12)
    d_norm = d_vec / (d_vec.norm() + 1e-12)
    return float(torch.dot(q_norm, d_norm))


def retrieve(query, corpus, model, processor, top_k=3, model_type="colpali", device="cpu", text_model=None):
    # Use text_model for query embedding when available (for hybrid vision+text models)
    if model_type in ["siglip", "clip"] and text_model:
        query_embedding = text_model.encode(query, convert_to_tensor=True)
    else:
        query_embedding = embed_text(query, model, processor, model_type=model_type, device=device)
    scores = []
    for entry in corpus:
        score = late_interaction_score(query_embedding, entry['embedding'])
        scores.append(score)
    top_indices = np.argsort(scores)[-top_k:][::-1]
    return [corpus[i] for i in top_indices]


##################################
# Building a Corpus from a Folder
##################################

def _pool_mean(tensors):
    if not tensors:
        return None
    stacked = torch.stack([t.float() for t in tensors], dim=0)
    return _l2norm(stacked.mean(dim=0))


def _embed_long_text(text: str, model, processor, model_type: str, device: str, max_len=1200, stride=800):
    """Chunk long text to keep memory bounded; mean-pool chunk embeddings."""
    # Adjust max_len based on model type
    if model_type in ["siglip", "clip"]:
        max_len = 200  # Much shorter for vision models
        stride = 150
    elif model_type == "colpali":
        max_len = 400  # Medium for ColPali
        stride = 300
    
    chunks = []
    i = 0
    while i < len(text):
        chunk = text[i:i+max_len]
        i += stride
        chunks.append(chunk)
    embs = []
    for c in chunks:
        embs.append(embed_text(c, model, processor, model_type=model_type, device=device))
    return _pool_mean(embs)


def _embed_image(img: Image.Image, model, processor, model_type: str, device: str):
    with torch.no_grad():
        if model_type == "siglip":
            inputs = processor(images=img, return_tensors="pt").to(device)
            try:
                feats = model.get_image_features(**inputs)
            except AttributeError:
                out = model(**inputs)
                feats = out.image_embeds
            return _l2norm(feats.squeeze(0)).cpu()
        elif model_type == "clip":
            inputs = processor(images=img, return_tensors="pt").to(device)
            try:
                feats = model.get_image_features(**inputs)
            except AttributeError:
                out = model(**inputs)
                feats = out.image_embeds
            return _l2norm(feats.squeeze(0)).cpu()
        else:
            return None  # non-vision models


def _pdf_pages_to_images(pdf_path: str, max_pages: int = 4, dpi: int = 144):
    try:
        doc = fitz.open(pdf_path)
        pages = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(dpi=dpi)
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
            pages.append(img)
        return pages
    except Exception:
        return []


def load_corpus_from_dir(corpus_dir, model, processor, device="cpu", model_type="colpali", text_model=None):
    """
    Scan 'corpus_dir' for txt, pdf, and image files, embed their content,
    and return a list of { 'embedding': torch.Tensor(cpu), 'metadata':... }.
    - For VLMs (siglip/clip): images & PDF pages are embedded directly (no OCR needed).
    - For text-only models: text is extracted (OCR for images as fallback) and embedded.
    - PDFs: combine (mean-pool) text chunks + first few rendered pages (VLMs) for robustness.

    Args:
        text_model: Optional separate text model (e.g., all-MiniLM) for embedding text content
                    when using vision models (siglip/clip). This ensures dimension consistency.
    """
    corpus = []
    if not corpus_dir or not os.path.isdir(corpus_dir):
        return corpus

    for filename in os.listdir(corpus_dir):
        file_path = os.path.join(corpus_dir, filename)
        if not os.path.isfile(file_path):
            continue

        ext = filename.lower()
        text = ""
        img_embs = []

        # --- TXT ---
        if ext.endswith(".txt"):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            except Exception as e:
                print(f"[WARN] Failed to read TXT {file_path}: {e}")
                continue

        # --- PDF ---
        elif ext.endswith(".pdf"):
            # Extract text quickly
            try:
                doc = fitz.open(file_path)
                tparts = []
                for i, page in enumerate(doc):
                    if i >= 10:  # cap for speed
                        break
                    t = page.get_text("text").strip()
                    if not t:
                        t = page.get_text("blocks").strip() or ""
                    if t:
                        tparts.append(t)
                text = "\n".join(tparts)
            except Exception as e:
                print(f"[WARN] Failed to read PDF {file_path}: {e}")
                text = ""

            # For VLMs, also embed first few pages as images (fast, no OCR)
            if model_type in ("siglip", "clip"):
                for img in _pdf_pages_to_images(file_path, max_pages=4):
                    e = _embed_image(img, model, processor, model_type, device)
                    if e is not None:
                        img_embs.append(e)

        # --- Images ---
        elif ext.endswith((".png", ".jpg", ".jpeg")):
            if model_type in ("siglip", "clip"):
                try:
                    img = Image.open(file_path).convert("RGB")
                    e = _embed_image(img, model, processor, model_type, device)
                    if e is not None:
                        img_embs.append(e)
                except Exception as e:
                    print(f"[WARN] Image load failed {file_path}: {e}")
                    continue
            else:
                # Text-only models: use OCR fallback
                try:
                    import pytesseract
                    img = Image.open(file_path)
                    text = pytesseract.image_to_string(img)
                except Exception as e:
                    print(f"[WARN] OCR failed for image {file_path}: {e}")
                    continue
        else:
            # skip unsupported
            continue

        # Build final embedding
        try:
            embs = []

            # For text content, use text_model if available (for vision models)
            # This ensures dimension consistency across all embeddings
            if text.strip():
                if model_type in ("siglip", "clip") and text_model:
                    # Use text_model for text content to maintain consistent dimensions
                    text_emb = text_model.encode(text[:1000], convert_to_tensor=True, device=device)
                    text_emb = _l2norm(text_emb).cpu()
                    embs.append(text_emb)
                else:
                    # Use the main model for text embedding
                    text_emb = _embed_long_text(text, model, processor, model_type, device)
                    if text_emb is not None:
                        embs.append(text_emb)

            # For vision models, only add image embeddings if there's no text
            # This prevents dimension mismatch when pooling
            if model_type in ("siglip", "clip"):
                if not text.strip() and img_embs:
                    # Only images, no text - need to convert to text_model dimensions
                    if text_model:
                        # Can't mix image and text embeddings with different dimensions
                        # Skip image-only files or use OCR
                        if ext.endswith((".png", ".jpg", ".jpeg")):
                            # For pure images, try OCR to get text representation
                            try:
                                import pytesseract
                                img = Image.open(file_path)
                                ocr_text = pytesseract.image_to_string(img)
                                if ocr_text.strip():
                                    text_emb = text_model.encode(ocr_text[:1000], convert_to_tensor=True, device=device)
                                    embs.append(_l2norm(text_emb).cpu())
                            except Exception:
                                # Skip if OCR fails
                                continue
                    else:
                        embs.extend(img_embs)
            else:
                # For non-vision models, add image embeddings normally
                embs.extend(img_embs)

            if not embs:
                # Nothing usable
                continue

            final_emb = _pool_mean(embs) if len(embs) > 1 else embs[0]
            snippet = (text[:100].replace('\n', ' ') + "...") if text else ""

            corpus.append({
                "embedding": final_emb.cpu(),
                "metadata": {
                    "file_path": file_path,
                    "type": "local",
                    "snippet": snippet
                }
            })
        except Exception as e:
            print(f"[WARN] Skipping embedding for local file {file_path} due to error: {e}")

    return corpus


###########################
# KnowledgeBase Class (API)
###########################

class KnowledgeBase:
    """
    Same public API, faster VLM support under the hood.
    """
    def __init__(self, model, processor, model_type="colpali", device="cpu", text_model=None):
        self.model = model
        self.processor = processor
        self.model_type = model_type
        self.device = device
        self.text_model = text_model  # For hybrid vision+text models
        self.corpus = []

    def add_documents(self, entries):
        self.corpus.extend(entries)

    def search(self, query, top_k=3):
        return retrieve(
            query,
            self.corpus,
            self.model,
            self.processor,
            top_k=top_k,
            model_type=self.model_type,
            device=self.device,
            text_model=self.text_model
        )

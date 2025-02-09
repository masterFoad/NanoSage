# knowledge_base.py

import os
import torch
import numpy as np
import fitz  # PyMuPDF
from PIL import Image

############################
# Load & Configure Retrieval
############################
def load_retrieval_model(model_choice="colpali", device="cpu"):
    if model_choice == "colpali":
        from transformers import ColPaliForRetrieval, ColPaliProcessor
        model_name = "vidore/colpali-v1.2-hf"
        model = ColPaliForRetrieval.from_pretrained(
            model_name,
            torch_dtype=torch.bfloat16,
            device_map=device
        ).eval()
        processor = ColPaliProcessor.from_pretrained(model_name)
        model_type = "colpali"
    elif model_choice == "all-minilm":
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("all-MiniLM-L6-v2", device=device)
        processor = None
        model_type = "all-minilm"
    else:
        raise ValueError(f"Unsupported retrieval model choice: {model_choice}")
    return model, processor, model_type

def embed_text(query, model, processor, model_type="colpali", device="cpu"):
    if model_type == "colpali":
        inputs = processor(text=[query], truncation=True, max_length=512, return_tensors="pt").to(device)
        outputs = model(**inputs)
        # For simplicity, we take the mean over all tokens.
        embedding = outputs.embeddings.mean(dim=1).squeeze(0)
        return embedding
    elif model_type == "all-minilm":
        return model.encode(query, convert_to_tensor=True)
    else:
        raise ValueError(f"Unsupported model_type: {model_type}")

##################
# Scoring & Search
##################
def late_interaction_score(query_emb, doc_emb):
    q_vec = query_emb.view(-1)
    d_vec = doc_emb.view(-1)
    q_norm = q_vec / q_vec.norm()
    d_norm = d_vec / d_vec.norm()
    return float(torch.dot(q_norm, d_norm))

def retrieve(query, corpus, model, processor, top_k=3, model_type="colpali", device="cpu"):
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
def load_corpus_from_dir(corpus_dir, model, processor, device="cpu", model_type="colpali"):
    """
    Scan 'corpus_dir' for txt, pdf, and image files, embed their text,
    and return a list of { 'embedding':..., 'metadata':... } entries.
    """
    corpus = []
    if not corpus_dir or not os.path.isdir(corpus_dir):
        return corpus

    for filename in os.listdir(corpus_dir):
        file_path = os.path.join(corpus_dir, filename)
        if not os.path.isfile(file_path):
            continue
        text = ""
        if filename.endswith(".txt"):
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
        elif filename.endswith(".pdf"):
            try:
                doc = fitz.open(file_path)
                text = ""
                for page in doc:
                    text += page.get_text() + "\n"
            except Exception as e:
                print(f"[WARN] Failed to read PDF {file_path}: {e}")
                continue
        elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            # Optional OCR if needed
            try:
                import pytesseract
                from PIL import Image
                text = pytesseract.image_to_string(Image.open(file_path))
            except Exception as e:
                print(f"[WARN] OCR failed for image {file_path}: {e}")
                continue
        else:
            # skip unsupported file
            continue

        if not text.strip():
            continue

        snippet = text[:100].replace('\n', ' ') + "..."
        try:
            emb = None
            if model_type == "colpali":
                inputs = processor(text=[text], truncation=True, max_length=512, return_tensors="pt").to(device)
                outputs = model(**inputs)
                emb = outputs.embeddings.mean(dim=1).squeeze(0)
            elif model_type == "all-minilm":
                emb = model.encode(text, convert_to_tensor=True)

            corpus.append({
                "embedding": emb,
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
    Simplified example showing how you might wrap the retrieval logic
    into a class. You can add 'add_documents' or advanced chunking, etc.
    """
    def __init__(self, model, processor, model_type="colpali", device="cpu"):
        self.model = model
        self.processor = processor
        self.model_type = model_type
        self.device = device
        self.corpus = []

    def add_documents(self, entries):
        """
        entries is a list of dict with:
          {
            'embedding': <torch tensor or sentence-transformers vector>,
            'metadata': { ... }
          }
        """
        self.corpus.extend(entries)

    def search(self, query, top_k=3):
        return retrieve(
            query,
            self.corpus,
            self.model,
            self.processor,
            top_k=top_k,
            model_type=self.model_type,
            device=self.device
        )

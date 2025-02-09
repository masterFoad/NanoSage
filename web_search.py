import os
import asyncio
from urllib.parse import urlparse
import aiohttp
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
import fitz  # PyMuPDF

def sanitize_filename(filename):
    """Sanitize a filename by allowing only alphanumerics, dot, underscore, and dash."""
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in filename)

def sanitize_path(path):
    """
    Sanitize a full filesystem path by splitting it into components, sanitizing each component,
    and then rejoining them. This helps avoid Windows invalid characters in any folder names.
    """
    parts = path.split(os.sep)
    sanitized_parts = [sanitize_filename(part) for part in parts if part]
    if path.startswith(os.sep):
        return os.sep + os.sep.join(sanitized_parts)
    else:
        return os.sep.join(sanitized_parts)

async def download_page(session, url, headers, timeout, file_path):
    try:
        async with session.get(url, headers=headers, timeout=timeout) as response:
            response.raise_for_status()
            content_type = response.headers.get('Content-Type', '')
            # If it's a PDF or image (or other binary content), read as binary.
            if ('application/pdf' in content_type) or file_path.lower().endswith('.pdf') or \
               ('image/' in content_type):
                content = await response.read()
                mode = 'wb'
                open_kwargs = {}
            else:
                content = await response.text()
                mode = 'w'
                open_kwargs = {'encoding': 'utf-8'}  # write text as UTF-8 to avoid charmap errors
            with open(file_path, mode, **open_kwargs) as f:
                f.write(content)
            print(f"[INFO] Saved '{url}' -> '{file_path}'")
            return {'url': url, 'file_path': file_path, 'content_type': content_type}
    except Exception as e:
        print(f"[WARN] Couldn't fetch '{url}': {e}")
        return None

async def download_webpages_ddg(keyword, limit=5, output_dir='downloaded_webpages'):
    """
    Perform a DuckDuckGo text search and download pages asynchronously.
    Returns a list of dicts with 'url', 'file_path', and optionally 'content_type'.
    """
    # Sanitize the output directory
    output_dir = sanitize_path(output_dir)
    os.makedirs(output_dir, exist_ok=True)
    
    results_info = []
    if not keyword.strip():
        print("[WARN] Empty keyword provided to DuckDuckGo search; skipping search.")
        return []
    
    with DDGS() as ddgs:
        results = ddgs.text(keyword, max_results=limit)
    if not results:
        print(f"[WARN] No results found for '{keyword}'.")
        return []
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    timeout = aiohttp.ClientTimeout(total=10)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = []
        for idx, result in enumerate(results):
            url = result.get("href")
            if not url:
                continue
            # Determine file extension from URL
            ext = ".html"
            if ".pdf" in url.lower():
                ext = ".pdf"
            # Limit the sanitized keyword length for the filename
            short_keyword = sanitize_filename(keyword)[:50]  # up to 50 chars
            filename = f"{short_keyword}_{idx}{ext}"
            file_path = os.path.join(output_dir, filename)
            tasks.append(download_page(session, url, headers, timeout, file_path))
        pages = await asyncio.gather(*tasks)
        for page in pages:
            if page:
                results_info.append(page)
    return results_info

def parse_pdf_to_text(pdf_file_path, max_pages=10):
    """
    Extract text from a PDF using PyMuPDF.
    If text is found (even partially), return it.
    Otherwise, convert up to max_pages pages to images and save them.
    """
    try:
        doc = fitz.open(pdf_file_path)
        text = ""
        for i in range(min(max_pages, doc.page_count)):
            page = doc.load_page(i)
            page_text = page.get_text().strip()
            if page_text:
                text += page_text + "\n"
        if text.strip():
            print(f"[INFO] Extracted text from PDF: {pdf_file_path}")
            return text
        else:
            print(f"[INFO] No text found in PDF: {pdf_file_path}, converting pages to images")
            for i in range(min(max_pages, doc.page_count)):
                page = doc.load_page(i)
                pix = page.get_pixmap()
                image_file = pdf_file_path.replace('.pdf', f'_page_{i+1}.png')
                pix.save(image_file)
                print(f"[INFO] Saved page {i+1} as image: {image_file}")
            return ""
    except Exception as e:
        print(f"[WARN] Failed to parse PDF {pdf_file_path}: {e}")
        return ""

def parse_html_to_text(file_path, max_pdf_pages=10):
    """
    If the file is HTML, parse it and return its plain text.
    If it's a PDF, attempt to extract text with PyMuPDF.
    If the PDF has little or no text, convert up to max_pdf_pages to images.
    """
    try:
        if file_path.lower().endswith('.pdf'):
            return parse_pdf_to_text(file_path, max_pages=max_pdf_pages)
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            html_data = f.read()
        soup = BeautifulSoup(html_data, 'html.parser')
        for tag in soup(["script", "style"]):
            tag.decompose()
        return soup.get_text(separator=' ', strip=True)
    except Exception as e:
        print(f"[WARN] Failed to parse HTML {file_path}: {e}")
        return ""

def group_web_results_by_domain(web_results):
    """
    Takes a list of dicts, each with 'url', 'file_path', 'content_type', and groups them by domain.
    """
    grouped = {}
    for item in web_results:
        url = item.get('url')
        if not url:
            continue
        domain = urlparse(url).netloc
        grouped.setdefault(domain, []).append(item)
    return grouped

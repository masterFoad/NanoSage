# backend/services/export_service.py

import os
from typing import Optional
from datetime import datetime
from backend.api.models import ExportFormat, QueryResult


class ExportService:
    """Service for exporting query results to different formats"""

    def __init__(self, export_dir: str = "exports"):
        self.export_dir = export_dir
        os.makedirs(export_dir, exist_ok=True)

    def export_result(self, result: QueryResult, format: ExportFormat) -> str:
        """
        Export query result to specified format

        Args:
            result: Query result to export
            format: Export format (markdown, text, or pdf)

        Returns:
            file_path: Path to exported file
        """
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        query_slug = self._slugify(result.query_text)

        if format == ExportFormat.MARKDOWN:
            filename = f"{query_slug}_{timestamp}.md"
            file_path = os.path.join(self.export_dir, filename)
            self._export_markdown(result, file_path)
        elif format == ExportFormat.TEXT:
            filename = f"{query_slug}_{timestamp}.txt"
            file_path = os.path.join(self.export_dir, filename)
            self._export_text(result, file_path)
        elif format == ExportFormat.PDF:
            filename = f"{query_slug}_{timestamp}.pdf"
            file_path = os.path.join(self.export_dir, filename)
            self._export_pdf(result, file_path)
        else:
            raise ValueError(f"Unsupported export format: {format}")

        return file_path

    def _export_markdown(self, result: QueryResult, file_path: str):
        """Export to Markdown format"""
        content = []

        # Header
        content.append(f"# {result.query_text}\n")
        content.append(f"**Generated:** {result.created_at}\n")
        content.append(f"**Query ID:** {result.query_id}\n")

        if result.processing_time_ms:
            content.append(f"**Processing Time:** {result.processing_time_ms}ms\n")

        content.append("\n---\n\n")

        # Parameters
        content.append("## Query Parameters\n\n")
        content.append(f"- **Web Search:** {result.parameters.web_search}\n")
        content.append(f"- **Retrieval Model:** {result.parameters.retrieval_model.value}\n")
        content.append(f"- **Top K:** {result.parameters.top_k}\n")
        content.append(f"- **Max Depth:** {result.parameters.max_depth}\n")
        content.append("\n")

        # Final Answer
        if result.final_answer:
            content.append("## Result\n\n")
            content.append(result.final_answer)
            content.append("\n\n")

        # Web Results
        if result.web_results:
            content.append("## Web Sources\n\n")
            for idx, web_result in enumerate(result.web_results, 1):
                content.append(f"{idx}. **{web_result.title}**\n")
                content.append(f"   - URL: {web_result.url}\n")
                content.append(f"   - Snippet: {web_result.snippet}\n")
                if web_result.relevance:
                    content.append(f"   - Relevance: {web_result.relevance:.2f}\n")
                content.append("\n")

        # Local Results
        if result.local_results:
            content.append("## Local Sources\n\n")
            for idx, local_result in enumerate(result.local_results, 1):
                content.append(f"{idx}. **{local_result.source}**\n")
                content.append(f"   - Snippet: {local_result.snippet}\n")
                if local_result.relevance:
                    content.append(f"   - Relevance: {local_result.relevance:.2f}\n")
                content.append("\n")

        # Search Tree
        if result.search_tree:
            content.append("## Search Tree\n\n")
            content.append(self._format_search_tree(result.search_tree))

        # Footer
        content.append("\n---\n\n")
        content.append("*Generated with NanoSage*\n")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(''.join(content))

    def _export_text(self, result: QueryResult, file_path: str):
        """Export to plain text format"""
        content = []

        # Header
        content.append(f"QUERY: {result.query_text}\n")
        content.append(f"Generated: {result.created_at}\n")
        content.append(f"Query ID: {result.query_id}\n")
        content.append("=" * 80 + "\n\n")

        # Final Answer
        if result.final_answer:
            content.append("RESULT\n")
            content.append("-" * 80 + "\n")
            # Remove markdown formatting from final answer
            clean_answer = self._strip_markdown(result.final_answer)
            content.append(clean_answer)
            content.append("\n\n")

        # Web Results
        if result.web_results:
            content.append("WEB SOURCES\n")
            content.append("-" * 80 + "\n")
            for idx, web_result in enumerate(result.web_results, 1):
                content.append(f"{idx}. {web_result.title}\n")
                content.append(f"   URL: {web_result.url}\n")
                content.append(f"   {web_result.snippet}\n\n")

        # Local Results
        if result.local_results:
            content.append("LOCAL SOURCES\n")
            content.append("-" * 80 + "\n")
            for idx, local_result in enumerate(result.local_results, 1):
                content.append(f"{idx}. {local_result.source}\n")
                content.append(f"   {local_result.snippet}\n\n")

        content.append("-" * 80 + "\n")
        content.append("Generated with NanoSage\n")

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(''.join(content))

    def _export_pdf(self, result: QueryResult, file_path: str):
        """Export to PDF format"""
        try:
            from reportlab.lib.pagesizes import letter, A4
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib.units import inch
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
            from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_CENTER

            doc = SimpleDocTemplate(file_path, pagesize=letter)
            story = []
            styles = getSampleStyleSheet()

            # Custom styles
            title_style = ParagraphStyle(
                'CustomTitle',
                parent=styles['Heading1'],
                fontSize=24,
                textColor='#2c3e50',
                spaceAfter=30,
                alignment=TA_CENTER
            )

            heading_style = ParagraphStyle(
                'CustomHeading',
                parent=styles['Heading2'],
                fontSize=16,
                textColor='#34495e',
                spaceAfter=12,
                spaceBefore=12
            )

            # Title
            story.append(Paragraph(result.query_text, title_style))
            story.append(Spacer(1, 12))

            # Metadata
            story.append(Paragraph(f"Generated: {result.created_at}", styles['Normal']))
            story.append(Paragraph(f"Query ID: {result.query_id}", styles['Normal']))
            story.append(Spacer(1, 20))

            # Final Answer
            if result.final_answer:
                story.append(Paragraph("Result", heading_style))
                # Convert markdown to plain text for PDF
                clean_answer = self._strip_markdown(result.final_answer)
                for para in clean_answer.split('\n\n'):
                    if para.strip():
                        story.append(Paragraph(para, styles['BodyText']))
                        story.append(Spacer(1, 12))
                story.append(Spacer(1, 20))

            # Web Sources
            if result.web_results:
                story.append(Paragraph("Web Sources", heading_style))
                for idx, web_result in enumerate(result.web_results, 1):
                    story.append(Paragraph(f"{idx}. {web_result.title}", styles['Normal']))
                    story.append(Paragraph(f"URL: {web_result.url}", styles['Italic']))
                    story.append(Paragraph(web_result.snippet, styles['BodyText']))
                    story.append(Spacer(1, 12))

            # Local Sources
            if result.local_results:
                story.append(Paragraph("Local Sources", heading_style))
                for idx, local_result in enumerate(result.local_results, 1):
                    story.append(Paragraph(f"{idx}. {local_result.source}", styles['Normal']))
                    story.append(Paragraph(local_result.snippet, styles['BodyText']))
                    story.append(Spacer(1, 12))

            doc.build(story)

        except ImportError:
            # Fallback: create a text file with PDF extension
            # This happens if reportlab is not installed
            self._export_text(result, file_path.replace('.pdf', '.txt'))
            raise ImportError("reportlab package required for PDF export. Install with: pip install reportlab")

    def _format_search_tree(self, node, indent=0) -> str:
        """Format search tree as markdown"""
        lines = []
        prefix = "  " * indent + ("- " if indent > 0 else "")
        lines.append(f"{prefix}**{node.query_text}** (relevance: {node.relevance_score:.2f})\n")

        if node.summary:
            summary_prefix = "  " * (indent + 1)
            lines.append(f"{summary_prefix}{node.summary}\n")

        for child in node.children:
            lines.append(self._format_search_tree(child, indent + 1))

        return ''.join(lines)

    def _slugify(self, text: str, max_length: int = 50) -> str:
        """Convert text to safe filename"""
        import re
        text = text.lower()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[-\s]+', '_', text)
        return text[:max_length]

    def _strip_markdown(self, text: str) -> str:
        """Remove markdown formatting"""
        import re
        # Remove headers
        text = re.sub(r'#+\s', '', text)
        # Remove bold/italic
        text = re.sub(r'\*\*?(.*?)\*\*?', r'\1', text)
        # Remove links
        text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
        # Remove code blocks
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'`(.*?)`', r'\1', text)
        return text


# Global instance
export_service = ExportService()

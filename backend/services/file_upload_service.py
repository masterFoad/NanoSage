# backend/services/file_upload_service.py

import os
import uuid
import shutil
from typing import Dict, Optional
from fastapi import UploadFile
from datetime import datetime


class FileUploadService:
    """Service for managing file uploads"""

    def __init__(self, upload_dir: str = "uploads"):
        self.upload_dir = upload_dir
        self.file_metadata: Dict[str, Dict] = {}

        # Create uploads directory if it doesn't exist
        os.makedirs(self.upload_dir, exist_ok=True)

    def _get_file_extension(self, filename: str) -> str:
        """Extract file extension from filename"""
        return os.path.splitext(filename)[1].lower()

    def _is_allowed_file(self, filename: str) -> tuple[bool, str]:
        """Check if file type is allowed"""
        allowed_extensions = {
            '.pdf': 'application/pdf',
            '.txt': 'text/plain',
            '.png': 'image/png',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg'
        }

        ext = self._get_file_extension(filename)
        if ext in allowed_extensions:
            return True, allowed_extensions[ext]
        return False, ''

    async def upload_file(self, file: UploadFile) -> Dict:
        """
        Upload a file and store metadata

        Args:
            file: UploadFile object from FastAPI

        Returns:
            Dict with file metadata including file_id

        Raises:
            ValueError: If file type is not allowed
        """
        # Validate file type
        is_allowed, file_type = self._is_allowed_file(file.filename)
        if not is_allowed:
            raise ValueError(
                f"File type not allowed. Supported formats: PDF, TXT, PNG, JPG/JPEG"
            )

        # Generate unique file ID
        file_id = str(uuid.uuid4())

        # Preserve original extension
        ext = self._get_file_extension(file.filename)
        stored_filename = f"{file_id}{ext}"
        file_path = os.path.join(self.upload_dir, stored_filename)

        # Save file to disk
        try:
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
        finally:
            file.file.close()

        # Get file size
        file_size = os.path.getsize(file_path)

        # Store metadata
        metadata = {
            'file_id': file_id,
            'original_filename': file.filename,
            'stored_filename': stored_filename,
            'file_path': file_path,
            'file_type': file_type,
            'file_size': file_size,
            'uploaded_at': datetime.utcnow().isoformat(),
            'extension': ext
        }

        self.file_metadata[file_id] = metadata

        return metadata

    def get_file_path(self, file_id: str) -> Optional[str]:
        """Get the file path for a given file ID"""
        metadata = self.file_metadata.get(file_id)
        if metadata:
            return metadata['file_path']
        return None

    def get_file_metadata(self, file_id: str) -> Optional[Dict]:
        """Get metadata for a given file ID"""
        return self.file_metadata.get(file_id)

    def delete_file(self, file_id: str) -> bool:
        """Delete a file and its metadata"""
        metadata = self.file_metadata.get(file_id)
        if not metadata:
            return False

        # Delete physical file
        file_path = metadata['file_path']
        if os.path.exists(file_path):
            os.remove(file_path)

        # Remove metadata
        del self.file_metadata[file_id]
        return True

    def get_upload_directory(self) -> str:
        """Get the upload directory path"""
        return os.path.abspath(self.upload_dir)

    def cleanup_old_files(self, max_age_hours: int = 24):
        """Clean up files older than specified hours"""
        current_time = datetime.utcnow()

        for file_id, metadata in list(self.file_metadata.items()):
            uploaded_at_str = metadata['uploaded_at']
            # Handle both timezone-aware and naive datetimes
            uploaded_at = datetime.fromisoformat(uploaded_at_str.replace('Z', '+00:00'))
            # Make it naive if it has timezone info
            if uploaded_at.tzinfo is not None:
                uploaded_at = uploaded_at.replace(tzinfo=None)

            age_hours = (current_time - uploaded_at).total_seconds() / 3600

            if age_hours > max_age_hours:
                self.delete_file(file_id)


# Global instance
file_upload_service = FileUploadService()

import pdfplumber
from typing import Optional
from app.parsers.base import StatementParser
from app.parsers.dbs import DBSParser
from app.parsers.maybank import MaybankParser
from app.parsers.uob import UOBParser
import re


class ParserFactory:
    """
    Factory to automatically detect bank and return appropriate parser.
    """

    @staticmethod
    def detect_bank(file_path: str) -> Optional[str]:
        """
        Detect which bank issued the statement by reading the PDF content.

        Args:
            file_path: Path to the PDF file

        Returns:
            Bank name ('dbs', 'maybank', 'uob', 'ocbc', 'citibank') or None
        """
        try:
            with pdfplumber.open(file_path) as pdf:
                # Read first page text
                if len(pdf.pages) == 0:
                    return None

                text = pdf.pages[0].extract_text()
                if not text:
                    return None

                text_lower = text.lower()

                # Check for bank indicators
                if 'maybank' in text_lower:
                    return 'maybank'
                elif 'uob' in text_lower or 'united overseas bank' in text_lower:
                    return 'uob'
                elif 'dbs' in text_lower or 'posb' in text_lower:
                    return 'dbs'
                elif 'ocbc' in text_lower:
                    return 'ocbc'
                elif 'citibank' in text_lower or 'citi' in text_lower:
                    return 'citibank'

                return None

        except Exception as e:
            print(f"Error detecting bank: {e}")
            return None

    @staticmethod
    def get_parser(file_path: str) -> Optional[StatementParser]:
        """
        Get the appropriate parser for a statement PDF.

        Args:
            file_path: Path to the PDF file

        Returns:
            StatementParser instance or None if bank cannot be detected
        """
        bank = ParserFactory.detect_bank(file_path)

        parsers = {
            'dbs': DBSParser(),
            'maybank': MaybankParser(),
            'uob': UOBParser(),
            # Add more parsers as they're implemented
            # 'ocbc': OCBCParser(),
            # 'citibank': CitibankParser(),
        }

        return parsers.get(bank)

    @staticmethod
    def parse(file_path: str) -> Optional[dict]:
        """
        Automatically detect bank and parse the statement.

        Args:
            file_path: Path to the PDF file

        Returns:
            Parsed statement data or None if parsing fails
        """
        parser = ParserFactory.get_parser(file_path)

        if not parser:
            return None

        try:
            return parser.parse(file_path)
        except Exception as e:
            print(f"Error parsing statement: {e}")
            return None
